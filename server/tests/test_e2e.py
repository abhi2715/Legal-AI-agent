"""End-to-end workflow tests in offline mode (no API key needed)."""
import json
import os
import tempfile

os.environ["LEXISCAN_DATA_DIR"] = tempfile.mkdtemp()
os.environ["LEXISCAN_OFFLINE"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

client = TestClient(main.app)
H = {"X-User-Id": "tester"}


def events(resp):
    out = []
    for block in resp.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        out.append((lines.get("event"), json.loads(lines.get("data", "null"))))
    return out


def final_state(resp):
    evs = events(resp)
    errors = [d for e, d in evs if e == "error"]
    assert not errors, errors
    return next(d for e, d in evs if e == "state")


def test_full_review_and_qa_flow():
    doc = client.post("/samples/affiliate", headers=H).json()
    assert len(doc["clauses"]) > 5
    assert {p["alias"] for p in doc["parties"]} == {"Business Affiliate", "UDC"}
    client.patch(f"/documents/{doc['id']}", headers=H,
                 json={"perspective": "Business Affiliate", "counterparty": "UDC"})

    # ── review graph: runs to the triage interrupt
    st = final_state(client.post(f"/documents/{doc['id']}/review", headers=H))
    assert st["interrupt"]["value"]["type"] == "triage"
    nodes = [t["node"] for t in st["values"]["trace"]]
    assert {"prepare", "analyze_clauses", "check_playbook", "extract_obligations", "score"} <= set(nodes)

    d = client.get(f"/documents/{doc['id']}", headers=H).json()
    assert d["findings"], "expected findings"
    assert d["playbook"], "expected playbook results"

    # cannot submit while medium/high findings are pending
    r = client.post(f"/documents/{doc['id']}/review/resume", headers=H, json={"action": "submit"})
    blocking = [f for f in d["findings"] if f["risk"] in ("medium", "high")]
    if blocking:
        assert r.status_code == 409

    # high-risk dismissal requires a reason
    high = [f for f in d["findings"] if f["risk"] == "high"]
    if high:
        r = client.patch(f"/findings/{high[0]['id']}", headers=H, json={"status": "dismissed"})
        assert r.status_code == 422

    first_ai = next((f["id"] for f in d["findings"] if f["source"] == "ai"), None)
    for i, f in enumerate(d["findings"]):
        if f["id"] == first_ai:
            body = {"status": "dismissed", "reviewer_note": "the obligation is mutual"}
        elif i == 1 or (first_ai is None and i == 0):
            body = {"status": "edited", "final_suggestion": "Either party may terminate on 30 days notice."}
        else:
            body = {"status": "accepted"}
        assert client.patch(f"/findings/{f['id']}", headers=H, json=body).status_code == 200

    st = final_state(client.post(f"/documents/{doc['id']}/review/resume", headers=H,
                                 json={"action": "submit"}))
    assert st["interrupt"]["value"]["type"] == "memo_review"
    assert "memo" in st["interrupt"]["value"]["memo"].lower() or st["interrupt"]["value"]["memo"]

    st = final_state(client.post(f"/documents/{doc['id']}/review/resume", headers=H,
                                 json={"action": "revise", "feedback": "Lead with the indemnity."}))
    assert st["interrupt"]["value"]["type"] == "memo_review"
    assert st["interrupt"]["value"]["revisions"] == 1

    st = final_state(client.post(f"/documents/{doc['id']}/review/resume", headers=H,
                                 json={"action": "approve"}))
    assert st["status"] == "done"
    d = client.get(f"/documents/{doc['id']}", headers=H).json()
    assert d["status"] == "reviewed" and d["memo_status"] == "approved"

    mems = client.get("/memories", headers=H).json()
    assert any(m["kind"] == "dismissal" for m in mems)

    # ── Q&A graph: clarification interrupt
    st = final_state(client.post(f"/documents/{doc['id']}/ask", headers=H,
                                 json={"question": "is this okay?"}))
    assert st["interrupt"]["value"]["type"] == "clarify"
    tid = st["values"]["thread_id"]
    st = final_state(client.post(f"/threads/{tid}/resume", headers=H,
                                 json={"action": "answer", "answer": "Termination and exit rights"}))
    assert st["interrupt"]["value"]["type"] == "answer_review"

    # ── Q&A: review → revise with pins → edit (learns)
    st = final_state(client.post(f"/documents/{doc['id']}/ask", headers=H,
                                 json={"question": "How can either party terminate the agreement?"}))
    tid = st["values"]["thread_id"]
    intr = st["interrupt"]["value"]
    assert intr["type"] == "answer_review"
    v = intr["verification"]
    assert v["quotes_verified"] == v["quotes_total"], v  # extractive quotes must verify
    hits = intr["hits"]
    r = client.post(f"/threads/{tid}/resume", headers=H, json={"action": "revise"})
    assert r.status_code == 422  # feedback required
    st = final_state(client.post(f"/threads/{tid}/resume", headers=H, json={
        "action": "revise", "feedback": "Focus on the termination clause only",
        "pinned": [hits[0]["clause_id"]], "excluded": [h["clause_id"] for h in hits[2:3]]}))
    assert st["interrupt"]["value"]["revisions"] == 1
    st = final_state(client.post(f"/threads/{tid}/resume", headers=H, json={
        "action": "edit", "answer": "Either party may terminate on 30 days' written notice."}))
    assert st["values"]["final"]["status"] == "edited"
    assert st["values"]["final"]["diff"]

    # ── time travel: history + rewind with a changed question
    hist = client.get(f"/threads/{tid}/history", headers=H).json()
    assert len(hist) >= 6
    before_retrieve = next(h for h in hist if h["next"] == "retrieve")
    st = final_state(client.post(f"/threads/{tid}/rewind", headers=H, json={
        "checkpoint_id": before_retrieve["checkpoint_id"],
        "question": "What are the confidentiality obligations?"}))
    assert st["interrupt"]["value"]["type"] == "answer_review"
    assert st["values"]["question"].startswith("What are the confidentiality")
    st = final_state(client.post(f"/threads/{tid}/resume", headers=H, json={"action": "approve"}))
    assert st["values"]["final"]["status"] == "approved"

    # ── policy: 'never' still escalates when quotes cannot be verified, else auto-approves
    client.patch("/me", headers=H, json={"review_policy": "never"})
    st = final_state(client.post(f"/documents/{doc['id']}/ask", headers=H,
                                 json={"question": "What does the indemnification clause require?"}))
    assert st["status"] == "done" and st["values"]["final"]["status"] == "auto_approved"
    client.patch("/me", headers=H, json={"review_policy": "always"})

    # ── outputs
    ics = client.get(f"/documents/{doc['id']}/obligations.ics", headers=H)
    assert ics.status_code == 200 and "BEGIN:VCALENDAR" in ics.text
    audit = client.get(f"/audit?doc_id={doc['id']}", headers=H).json()
    actions = {a["action"] for a in audit}
    assert {"review.triage_submitted", "memo.revise", "answer.final.edited", "answer.rewound"} <= actions
    assert client.get("/audit?format=csv", headers=H).text.startswith("time,actor")
    ins = client.get("/insights", headers=H).json()
    assert ins["memories_active"] >= 1


def test_playbook_presets_and_privacy():
    rules = client.post("/playbook/presets/nda?replace=true", headers=H).json()
    assert len(rules) == 4
    from app.privacy import Redactor
    r = Redactor()
    assert "[EMAIL_1]" in r.redact("mail a@b.co now")


def test_rejects_bad_upload():
    r = client.post("/documents", headers=H, files={"file": ("x.exe", b"MZ....", "application/octet-stream")})
    assert r.status_code == 422
