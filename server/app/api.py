"""HTTP API. Long-running graph runs stream progress as Server-Sent Events."""
from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel, Field

from . import db
from .config import BASE_DIR, MAX_REVISIONS, MAX_UPLOAD_BYTES
from .graphs import qa, review
from .graphs.common import snapshot_payload, stream_run, trace
from .ingest import IngestError, ingest
from .llm import engine

router = APIRouter()


def current_user(x_user_id: str = Header(default="local", max_length=64)) -> dict[str, Any]:
    uid = "".join(ch for ch in x_user_id if ch.isalnum() or ch in "-_") or "local"
    return db.ensure_user(uid)


def sse_response(gen) -> StreamingResponse:
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _doc_or_404(doc_id: str, user: dict) -> dict[str, Any]:
    doc = db.get_document(doc_id, user["id"])
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


# ── health & profile ─────────────────────────────────────────────────────────

@router.get("/health")
def health():
    return {"status": "ok", "engine": engine.status(), "storage": db.backend()}


class ProfilePatch(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    role: str | None = Field(default=None, max_length=80)
    expertise: Literal["plain", "professional", "expert"] | None = None
    jurisdiction: str | None = Field(default=None, max_length=80)
    review_policy: Literal["always", "smart", "never"] | None = None
    confidence_threshold: float | None = Field(default=None, ge=0.3, le=0.99)
    privacy_redact: bool | None = None
    ask_clarifications: bool | None = None


@router.get("/me")
def get_me(user=Depends(current_user)):
    return {**user, "engine": engine.status(), "storage": db.backend()}


@router.patch("/me")
def patch_me(body: ProfilePatch, user=Depends(current_user)):
    fields = body.model_dump(exclude_none=True)
    for k in ("privacy_redact", "ask_clarifications"):
        if k in fields:
            fields[k] = int(fields[k])
    updated = db.update_user(user["id"], fields)
    db.audit(user["id"], f"human:{updated['name']}", "settings.updated", fields)
    return updated


# ── documents ────────────────────────────────────────────────────────────────

def _summary(doc: dict[str, Any]) -> dict[str, Any]:
    with db.connect() as conn:
        counts = {r["status"]: r["n"] for r in db.rows(conn.execute(
            "SELECT status, COUNT(*) n FROM findings WHERE doc_id=? GROUP BY status", (doc["id"],)))}
        threads = conn.execute("SELECT COUNT(*) FROM threads WHERE doc_id=?",
                               (doc["id"],)).fetchone()[0]
    return {
        "id": doc["id"], "name": doc["name"], "created_at": doc["created_at"],
        "status": doc["status"], "risk_score": doc["risk_score"], "risk_level": doc["risk_level"],
        "perspective": doc["perspective"], "counterparty": doc["counterparty"],
        "clause_count": len(doc["clauses"]), "findings": counts, "threads": threads,
        "memo_status": doc["memo_status"],
    }


@router.get("/documents")
def list_documents(user=Depends(current_user)):
    with db.connect() as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM documents WHERE user_id=? ORDER BY created_at DESC", (user["id"],))]
    return [_summary(db.get_document(i)) for i in ids]


def _create_document(user: dict, filename: str, data: bytes) -> dict[str, Any]:
    try:
        parsed = ingest(filename, data)
    except IngestError as exc:
        raise HTTPException(422, str(exc)) from exc
    doc_id = db.new_id("doc")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id, user_id, name, created_at, text, clauses_json,"
            " defined_terms_json, parties_json) VALUES (?,?,?,?,?,?,?,?)",
            (doc_id, user["id"], filename, db.now(), parsed["text"], json.dumps(parsed["clauses"]),
             json.dumps(parsed["defined_terms"]), json.dumps(parsed["parties"])),
        )
    db.audit(user["id"], f"human:{user['name']}", "document.uploaded",
             {"name": filename, "clauses": len(parsed["clauses"]), "pages": parsed["pages"]},
             doc_id=doc_id)
    return get_document(doc_id, user)


@router.post("/documents")
async def upload_document(file: UploadFile = File(...), user=Depends(current_user)):
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    return _create_document(user, file.filename or "contract.txt", data)


SAMPLES = {
    "web-services": ("Website Design & Hosting Agreement.txt", "contract-1.txt"),
    "sponsorship": ("Sponsorship Agreement.txt", "contract-2.txt"),
    "affiliate": ("Business Affiliate Agreement.txt", "contract-3.txt"),
}


@router.get("/samples")
def list_samples():
    return [{"id": k, "name": v[0]} for k, v in SAMPLES.items()]


@router.post("/samples/{sample_id}")
def load_sample(sample_id: str, user=Depends(current_user)):
    if sample_id not in SAMPLES:
        raise HTTPException(404, "Unknown sample")
    name, file = SAMPLES[sample_id]
    return _create_document(user, name, (BASE_DIR / "data" / file).read_bytes())


@router.get("/documents/{doc_id}")
def get_document(doc_id: str, user=Depends(current_user)):
    doc = _doc_or_404(doc_id, user)
    with db.connect() as conn:
        findings = db.rows(conn.execute(
            "SELECT * FROM findings WHERE doc_id=? ORDER BY CASE risk WHEN 'high' THEN 0 WHEN "
            "'medium' THEN 1 WHEN 'low' THEN 2 ELSE 3 END, created_at, source, clause_id, title, id",
            (doc_id,)))
        obligations = db.rows(conn.execute(
            "SELECT * FROM obligations WHERE doc_id=? ORDER BY COALESCE(due_date, '9999'), party, id",
            (doc_id,)))
        threads = db.rows(conn.execute(
            "SELECT * FROM threads WHERE doc_id=? ORDER BY created_at DESC", (doc_id,)))
    review_state = None
    if doc["review_thread_id"]:
        review_state = snapshot_payload(review.graph.get_state(
            {"configurable": {"thread_id": doc["review_thread_id"]}}))
    return {**doc, "findings": findings, "obligations": obligations, "threads": threads,
            "review": review_state}


class DocumentPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    perspective: str | None = Field(default=None, max_length=120)
    counterparty: str | None = Field(default=None, max_length=120)


@router.patch("/documents/{doc_id}")
def patch_document(doc_id: str, body: DocumentPatch, user=Depends(current_user)):
    _doc_or_404(doc_id, user)
    fields = body.model_dump(exclude_none=True)
    db.update_document(doc_id, **fields)
    db.audit(user["id"], f"human:{user['name']}", "document.updated", fields, doc_id=doc_id)
    return get_document(doc_id, user)


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str, user=Depends(current_user)):
    doc = _doc_or_404(doc_id, user)
    with db.connect() as conn:
        for table in ("findings", "obligations", "threads"):
            conn.execute(f"DELETE FROM {table} WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    db.audit(user["id"], f"human:{user['name']}", "document.deleted", {"name": doc["name"]},
             doc_id=doc_id)
    return {"ok": True}


# ── review workflow ──────────────────────────────────────────────────────────

@router.post("/documents/{doc_id}/review")
def start_review(doc_id: str, user=Depends(current_user)):
    _doc_or_404(doc_id, user)
    thread_id = f"review_{doc_id}_{uuid.uuid4().hex[:6]}"
    db.update_document(doc_id, review_thread_id=thread_id, memo=None, memo_status=None)
    with db.connect() as conn:
        conn.execute("DELETE FROM findings WHERE doc_id=?", (doc_id,))
    config = {"configurable": {"thread_id": thread_id}}
    return sse_response(stream_run(review.graph, {"doc_id": doc_id, "user_id": user["id"]}, config))


class ReviewResume(BaseModel):
    action: Literal["submit", "approve", "edit", "revise"]
    memo: str | None = None
    feedback: str | None = Field(default=None, max_length=4000)
    note: str | None = Field(default=None, max_length=2000)


@router.post("/documents/{doc_id}/review/resume")
def resume_review(doc_id: str, body: ReviewResume, user=Depends(current_user)):
    doc = _doc_or_404(doc_id, user)
    if not doc["review_thread_id"]:
        raise HTTPException(409, "No review in progress")
    config = {"configurable": {"thread_id": doc["review_thread_id"]}}
    snap = snapshot_payload(review.graph.get_state(config))
    intr = snap["interrupt"]
    if not intr:
        raise HTTPException(409, "The review is not waiting for input")
    kind = intr["value"]["type"]
    if kind == "triage":
        if body.action != "submit":
            raise HTTPException(422, "Submit your triage decisions to continue")
        with db.connect() as conn:
            blocking = conn.execute(
                "SELECT COUNT(*) FROM findings WHERE doc_id=? AND status='pending' AND risk IN "
                "('medium','high')", (doc_id,)).fetchone()[0]
        if blocking:
            raise HTTPException(409, f"{blocking} medium or high risk finding(s) still need a decision")
    elif kind == "memo_review":
        if body.action not in ("approve", "edit", "revise"):
            raise HTTPException(422, "Approve, edit or request a revision of the memo")
        if body.action == "revise" and intr["value"]["revisions"] >= MAX_REVISIONS:
            raise HTTPException(409, "Revision limit reached; edit the memo directly instead")
        if body.action == "revise" and not (body.feedback or "").strip():
            raise HTTPException(422, "Tell the assistant what to change")
    return sse_response(stream_run(review.graph, Command(resume=body.model_dump()), config))


class FindingPatch(BaseModel):
    status: Literal["pending", "accepted", "dismissed", "edited", "escalated"] | None = None
    reviewer_note: str | None = Field(default=None, max_length=2000)
    final_suggestion: str | None = Field(default=None, max_length=4000)


def _finding_or_404(finding_id: str, user: dict) -> dict[str, Any]:
    with db.connect() as conn:
        f = db.row(conn.execute(
            "SELECT f.* FROM findings f JOIN documents d ON d.id=f.doc_id WHERE f.id=? AND"
            " d.user_id=?", (finding_id, user["id"])).fetchone())
    if not f:
        raise HTTPException(404, "Finding not found")
    return f


@router.patch("/findings/{finding_id}")
def patch_finding(finding_id: str, body: FindingPatch, user=Depends(current_user)):
    before = _finding_or_404(finding_id, user)
    fields = body.model_dump(exclude_none=True)
    if fields.get("status") == "dismissed" and before["risk"] == "high" and \
            not (fields.get("reviewer_note") or before["reviewer_note"]).strip():
        raise HTTPException(422, "Dismissing a high-risk finding requires a reason")
    if "status" in fields:
        fields["decided_by"] = user["name"]
        fields["decided_at"] = db.now()
    sets = ", ".join(f"{k}=?" for k in fields)
    with db.connect() as conn:
        conn.execute(f"UPDATE findings SET {sets} WHERE id=?", (*fields.values(), finding_id))
    db.audit(user["id"], f"human:{user['name']}", "finding.decided",
             {"finding": before["title"], "risk": before["risk"], "from": before["status"],
              **{k: v for k, v in fields.items() if k not in ('decided_by', 'decided_at')}},
             doc_id=before["doc_id"])
    return _finding_or_404(finding_id, user)


class BulkFindings(BaseModel):
    ids: list[str]
    status: Literal["accepted", "dismissed"]


@router.post("/documents/{doc_id}/findings/bulk")
def bulk_findings(doc_id: str, body: BulkFindings, user=Depends(current_user)):
    _doc_or_404(doc_id, user)
    with db.connect() as conn:
        risks = {r["id"]: r["risk"] for r in db.rows(conn.execute(
            f"SELECT id, risk FROM findings WHERE doc_id=? AND id IN ({','.join('?' * len(body.ids))})",
            (doc_id, *body.ids)))} if body.ids else {}
        if body.status == "dismissed" and "high" in risks.values():
            raise HTTPException(422, "High-risk findings must be dismissed one by one, with a reason")
        conn.executemany("UPDATE findings SET status=?, decided_by=?, decided_at=? WHERE id=?",
                         [(body.status, user["name"], db.now(), i) for i in risks])
    db.audit(user["id"], f"human:{user['name']}", "finding.bulk_decided",
             {"count": len(risks), "status": body.status}, doc_id=doc_id)
    return {"updated": len(risks)}


# ── obligations ──────────────────────────────────────────────────────────────

class ObligationPatch(BaseModel):
    done: bool | None = None
    due_date: str | None = None


@router.patch("/obligations/{obligation_id}")
def patch_obligation(obligation_id: str, body: ObligationPatch, user=Depends(current_user)):
    with db.connect() as conn:
        o = db.row(conn.execute(
            "SELECT o.* FROM obligations o JOIN documents d ON d.id=o.doc_id WHERE o.id=? AND"
            " d.user_id=?", (obligation_id, user["id"])).fetchone())
        if not o:
            raise HTTPException(404, "Obligation not found")
        if body.done is not None:
            conn.execute("UPDATE obligations SET done=? WHERE id=?", (int(body.done), obligation_id))
        if body.due_date is not None:
            if body.due_date:
                try:
                    date.fromisoformat(body.due_date)
                except ValueError as exc:
                    raise HTTPException(422, "due_date must be YYYY-MM-DD") from exc
            conn.execute("UPDATE obligations SET due_date=? WHERE id=?",
                         (body.due_date or None, obligation_id))
        return db.row(conn.execute("SELECT * FROM obligations WHERE id=?", (obligation_id,)).fetchone())


def _ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


@router.get("/documents/{doc_id}/obligations.ics")
def obligations_ics(doc_id: str, party: str = "", user=Depends(current_user)):
    doc = _doc_or_404(doc_id, user)
    with db.connect() as conn:
        items = db.rows(conn.execute(
            "SELECT * FROM obligations WHERE doc_id=? AND due_date IS NOT NULL AND done=0", (doc_id,)))
    if party:
        items = [o for o in items if o["party"] in (party, "Both parties")]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//LexiScan//Obligations//EN"]
    for o in items:
        d = date.fromisoformat(o["due_date"])
        lines += [
            "BEGIN:VEVENT", f"UID:{o['id']}@lexiscan", f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:{_ics_escape(o['party'] + ': ' + o['action'][:120])}",
            f"DESCRIPTION:{_ics_escape(doc['name'] + ' / ' + (o['due'] or '') + ' / ' + o['action'])}",
            "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:-P7D",
            f"DESCRIPTION:{_ics_escape('Due in 7 days: ' + o['action'][:80])}", "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return Response("\r\n".join(lines), media_type="text/calendar",
                    headers={"Content-Disposition": f'attachment; filename="{doc_id}-obligations.ics"'})


# ── Q&A workflow ─────────────────────────────────────────────────────────────

class AskBody(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    pinned: list[str] = []


def _thread_finish(thread_id: str):
    def on_finish(payload: dict[str, Any]) -> None:
        if payload["status"] == "interrupted":
            kind = payload["interrupt"]["value"]["type"]
            status = "awaiting_clarification" if kind == "clarify" else "awaiting_review"
        elif payload["status"] == "done":
            status = payload["values"].get("final", {}).get("status", "done")
        else:
            status = "running"
        with db.connect() as conn:
            conn.execute("UPDATE threads SET status=?, updated_at=? WHERE id=?",
                         (status, db.now(), thread_id))
    return on_finish


@router.post("/documents/{doc_id}/ask")
def ask(doc_id: str, body: AskBody, user=Depends(current_user)):
    _doc_or_404(doc_id, user)
    thread_id = db.new_id("thr")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO threads (id, user_id, doc_id, question, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?)", (thread_id, user["id"], doc_id, body.question, db.now(), db.now()))
    db.audit(user["id"], f"human:{user['name']}", "question.asked", {"question": body.question},
             doc_id=doc_id, thread_id=thread_id)
    config = {"configurable": {"thread_id": thread_id}}
    initial = {"thread_id": thread_id, "doc_id": doc_id, "user_id": user["id"],
               "question": body.question.strip(), "pinned": body.pinned, "excluded": [],
               "revisions": 0}
    return sse_response(stream_run(qa.graph, initial, config, _thread_finish(thread_id)))


def _thread_or_404(thread_id: str, user: dict) -> dict[str, Any]:
    with db.connect() as conn:
        t = db.row(conn.execute("SELECT * FROM threads WHERE id=? AND user_id=?",
                                (thread_id, user["id"])).fetchone())
    if not t:
        raise HTTPException(404, "Conversation not found")
    return t


@router.get("/threads/{thread_id}")
def get_thread(thread_id: str, user=Depends(current_user)):
    t = _thread_or_404(thread_id, user)
    snap = qa.graph.get_state({"configurable": {"thread_id": thread_id}})
    return {**t, "run": snapshot_payload(snap)}


class QAResume(BaseModel):
    action: Literal["answer", "approve", "edit", "revise", "reject"]
    answer: str | None = Field(default=None, max_length=8000)
    feedback: str | None = Field(default=None, max_length=4000)
    pinned: list[str] | None = None
    excluded: list[str] | None = None


@router.post("/threads/{thread_id}/resume")
def resume_thread(thread_id: str, body: QAResume, user=Depends(current_user)):
    _thread_or_404(thread_id, user)
    config = {"configurable": {"thread_id": thread_id}}
    snap = snapshot_payload(qa.graph.get_state(config))
    intr = snap["interrupt"]
    if not intr:
        raise HTTPException(409, "This conversation is not waiting for input")
    kind = intr["value"]["type"]
    if kind == "clarify" and body.action != "answer":
        raise HTTPException(422, "Answer the clarifying question to continue")
    if kind == "answer_review":
        if body.action not in ("approve", "edit", "revise", "reject"):
            raise HTTPException(422, "Approve, edit, revise or reject the draft")
        if body.action == "revise" and intr["value"]["revisions"] >= MAX_REVISIONS:
            raise HTTPException(409, "Revision limit reached; edit the answer directly instead")
        if body.action == "edit" and not (body.answer or "").strip():
            raise HTTPException(422, "Provide the edited answer")
        if body.action in ("revise", "reject") and not (body.feedback or "").strip():
            raise HTTPException(422, "Explain what is wrong so the assistant can learn from it")
    payload = body.model_dump(exclude_none=True)
    return sse_response(stream_run(qa.graph, Command(resume=payload), config,
                                   _thread_finish(thread_id)))


STEP_LABELS = {
    "plan": "Plan the question", "clarify": "Ask for clarification", "retrieve": "Retrieve clauses",
    "draft": "Draft the answer", "verify": "Verify quotes", "gate": "Apply review policy",
    "human_review": "Your review", "finalize": "Finalize",
}


@router.get("/threads/{thread_id}/history")
def thread_history(thread_id: str, user=Depends(current_user)):
    _thread_or_404(thread_id, user)
    out = []
    for snap in qa.graph.get_state_history({"configurable": {"thread_id": thread_id}}):
        if not snap.next or snap.next[0].startswith("__"):
            continue
        nxt = snap.next[0]
        v = snap.values or {}
        out.append({
            "checkpoint_id": snap.config["configurable"]["checkpoint_id"],
            "parent_id": (snap.parent_config or {}).get("configurable", {}).get("checkpoint_id"),
            "created_at": snap.created_at,
            "step": (snap.metadata or {}).get("step"),
            "next": nxt,
            "label": "Before: " + STEP_LABELS.get(nxt, nxt),
            "revision": v.get("revisions", 0),
            "question": v.get("question"),
            "has_draft": bool(v.get("draft")),
        })
    out.reverse()
    return out


class RewindBody(BaseModel):
    checkpoint_id: str
    question: str | None = Field(default=None, max_length=2000)
    pinned: list[str] | None = None
    excluded: list[str] | None = None


@router.post("/threads/{thread_id}/rewind")
def rewind(thread_id: str, body: RewindBody, user=Depends(current_user)):
    t = _thread_or_404(thread_id, user)
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": "",
                              "checkpoint_id": body.checkpoint_id}}
    snap = qa.graph.get_state(config)
    if not snap or not snap.values:
        raise HTTPException(404, "Checkpoint not found")
    patch: dict[str, Any] = {}
    if body.question and body.question.strip() != snap.values.get("question"):
        patch.update({"question": body.question.strip(), "clarification": ""})
    if body.pinned is not None:
        patch["pinned"] = body.pinned
    if body.excluded is not None:
        patch["excluded"] = body.excluded
    changes = ", ".join(patch) or "nothing"
    db.audit(user["id"], f"human:{user['name']}", "answer.rewound",
             {"checkpoint": body.checkpoint_id, "changed": list(patch)},
             doc_id=t["doc_id"], thread_id=thread_id)
    if patch:
        patch["trace"] = trace("rewind", f"{user['name']} rewound and changed {changes}; "
                               "re-planning from here.", actor="human")
        # Writing as 'clarify' routes the fork back through `plan`, so a changed question gets
        # a fresh plan and new pins/exclusions flow into retrieval.
        config = qa.graph.update_state(config, patch, as_node="clarify")
    else:
        config = qa.graph.update_state(
            config, {"trace": trace("rewind", f"{user['name']} re-ran from "
                                    f"'{STEP_LABELS.get(snap.next[0], snap.next[0]) if snap.next else 'end'}'.",
                                    actor="human")},
            as_node=_predecessor(snap))
    if body.question:
        with db.connect() as conn:
            conn.execute("UPDATE threads SET question=? WHERE id=?",
                         (body.question.strip(), thread_id))
    return sse_response(stream_run(qa.graph, None, config, _thread_finish(thread_id)))


def _predecessor(snap) -> str:
    nxt = snap.next[0] if snap.next else "finalize"
    return {"plan": "clarify", "clarify": "plan", "retrieve": "plan", "draft": "retrieve",
            "verify": "draft", "gate": "verify", "human_review": "gate",
            "finalize": "gate"}.get(nxt, "clarify")


# ── playbook ─────────────────────────────────────────────────────────────────

PRESETS: dict[str, list[tuple[str, str, str, str]]] = {
    "saas_customer": [
        ("liability", "Vendor liability is meaningful", "Vendor's cap must be at least 12 months of fees, with uncapped liability for data breaches and confidentiality.", "high"),
        ("data_protection", "Security commitments", "Vendor must commit to security standards (e.g. SOC 2), breach notice within 72 hours, and a DPA.", "high"),
        ("termination", "Exit and data return", "We can terminate for convenience and get our data back in a usable format within 30 days.", "medium"),
        ("renewal", "Price protection on renewal", "Renewal price increases are capped (e.g. 5% per year) and need 60 days' notice.", "medium"),
        ("warranty", "Service level", "An uptime SLA (99.9%+) with service credits is included.", "medium"),
    ],
    "vendor": [
        ("liability", "Our liability is capped", "Our total liability is capped at fees paid in the prior 12 months, excluding indirect damages.", "high"),
        ("payment", "We get paid on time", "Net 30 or shorter, with late interest and the right to suspend for non-payment.", "high"),
        ("ip", "We keep our IP", "We retain all pre-existing IP and tools; the customer gets a licence, not ownership.", "high"),
        ("warranty", "Limited warranties", "Warranties are limited to professional and workmanlike performance; implied warranties are disclaimed.", "medium"),
        ("indemnification", "Narrow indemnity", "Our indemnity is limited to third-party IP infringement claims.", "medium"),
    ],
    "employee": [
        ("non_compete", "Reasonable non-compete", "Any non-compete is 12 months or less, limited to direct competitors and to my region.", "high"),
        ("ip", "Personal projects are mine", "IP assignment excludes inventions made on my own time without company resources.", "high"),
        ("termination", "Notice and severance", "Clear notice period and severance terms for termination without cause.", "medium"),
        ("confidentiality", "Bounded confidentiality", "Confidentiality excludes general skills and publicly available information.", "low"),
    ],
    "nda": [
        ("confidentiality", "Time-limited", "Obligations last no more than 2-5 years, except for trade secrets.", "medium"),
        ("confidentiality", "Standard exclusions", "Excludes public info, prior knowledge, independent development and third-party disclosures.", "high"),
        ("ip", "No implied licence", "No licence or ownership transfers by disclosure.", "medium"),
        ("non_compete", "No hidden non-solicit", "No non-solicitation or non-compete in an NDA.", "medium"),
    ],
}


class RuleBody(BaseModel):
    clause_type: str = Field(max_length=40)
    title: str = Field(min_length=2, max_length=120)
    requirement: str = Field(min_length=5, max_length=1000)
    severity: Literal["low", "medium", "high"] = "medium"
    enabled: bool = True


class RulePatch(BaseModel):
    clause_type: str | None = Field(default=None, max_length=40)
    title: str | None = Field(default=None, max_length=120)
    requirement: str | None = Field(default=None, max_length=1000)
    severity: Literal["low", "medium", "high"] | None = None
    enabled: bool | None = None


@router.get("/playbook")
def list_rules(user=Depends(current_user)):
    with db.connect() as conn:
        return db.rows(conn.execute(
            "SELECT * FROM playbook_rules WHERE user_id=? ORDER BY created_at", (user["id"],)))


@router.post("/playbook")
def add_rule(body: RuleBody, user=Depends(current_user)):
    rid = db.new_id("rule")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO playbook_rules (id, user_id, clause_type, title, requirement, severity,"
            " enabled, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (rid, user["id"], body.clause_type, body.title, body.requirement, body.severity,
             int(body.enabled), db.now()))
    db.audit(user["id"], f"human:{user['name']}", "playbook.rule_added", body.model_dump())
    return list_rules(user)


@router.patch("/playbook/{rule_id}")
def patch_rule(rule_id: str, body: RulePatch, user=Depends(current_user)):
    fields = body.model_dump(exclude_none=True)
    if "enabled" in fields:
        fields["enabled"] = int(fields["enabled"])
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        with db.connect() as conn:
            conn.execute(f"UPDATE playbook_rules SET {sets} WHERE id=? AND user_id=?",
                         (*fields.values(), rule_id, user["id"]))
    return list_rules(user)


@router.delete("/playbook/{rule_id}")
def delete_rule(rule_id: str, user=Depends(current_user)):
    with db.connect() as conn:
        conn.execute("DELETE FROM playbook_rules WHERE id=? AND user_id=?", (rule_id, user["id"]))
    return list_rules(user)


@router.post("/playbook/presets/{preset}")
def apply_preset(preset: str, replace: bool = False, user=Depends(current_user)):
    if preset not in PRESETS:
        raise HTTPException(404, "Unknown preset")
    with db.connect() as conn:
        if replace:
            conn.execute("DELETE FROM playbook_rules WHERE user_id=?", (user["id"],))
        for clause_type, title, requirement, severity in PRESETS[preset]:
            conn.execute(
                "INSERT INTO playbook_rules (id, user_id, clause_type, title, requirement, severity,"
                " created_at) VALUES (?,?,?,?,?,?,?)",
                (db.new_id("rule"), user["id"], clause_type, title, requirement, severity, db.now()))
    db.audit(user["id"], f"human:{user['name']}", "playbook.preset_applied",
             {"preset": preset, "replace": replace})
    return list_rules(user)


# ── learned memory ───────────────────────────────────────────────────────────

class MemoryPatch(BaseModel):
    active: bool | None = None
    content: str | None = Field(default=None, min_length=3, max_length=1000)


@router.get("/memories")
def list_memories(user=Depends(current_user)):
    with db.connect() as conn:
        return db.rows(conn.execute(
            "SELECT * FROM memories WHERE user_id=? ORDER BY created_at DESC", (user["id"],)))


@router.post("/memories")
def add_memory(body: MemoryPatch, user=Depends(current_user)):
    if not body.content:
        raise HTTPException(422, "content is required")
    db.add_memory(user["id"], "instruction", "general", body.content.strip(), "manual")
    return list_memories(user)


@router.patch("/memories/{memory_id}")
def patch_memory(memory_id: str, body: MemoryPatch, user=Depends(current_user)):
    fields = body.model_dump(exclude_none=True)
    if "active" in fields:
        fields["active"] = int(fields["active"])
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        with db.connect() as conn:
            conn.execute(f"UPDATE memories SET {sets} WHERE id=? AND user_id=?",
                         (*fields.values(), memory_id, user["id"]))
    db.audit(user["id"], f"human:{user['name']}", "memory.updated", {"id": memory_id, **fields})
    return list_memories(user)


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: str, user=Depends(current_user)):
    with db.connect() as conn:
        conn.execute("DELETE FROM memories WHERE id=? AND user_id=?", (memory_id, user["id"]))
    db.audit(user["id"], f"human:{user['name']}", "memory.deleted", {"id": memory_id})
    return list_memories(user)


# ── audit trail ──────────────────────────────────────────────────────────────

@router.get("/audit")
def list_audit(doc_id: str | None = None, format: Literal["json", "csv"] = "json", limit: int = 500,
               user=Depends(current_user)):
    q = "SELECT * FROM audit WHERE user_id=?"
    args: list[Any] = [user["id"]]
    if doc_id:
        q += " AND doc_id=?"
        args.append(doc_id)
    q += " ORDER BY created_at DESC, id DESC LIMIT ?"
    args.append(max(1, min(limit, 5000)))
    with db.connect() as conn:
        items = db.rows(conn.execute(q, args))
    for i in items:
        i["detail"] = json.loads(i.pop("detail_json"))
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["time", "actor", "action", "document", "thread", "detail"])
        for i in items:
            w.writerow([i["created_at"], i["actor"], i["action"], i["doc_id"] or "",
                        i["thread_id"] or "", json.dumps(i["detail"])])
        return PlainTextResponse(buf.getvalue(), media_type="text/csv", headers={
            "Content-Disposition": 'attachment; filename="lexiscan-audit.csv"'})
    return items


@router.get("/insights")
def insights(user=Depends(current_user)):
    """How the reviewer and the assistant are working together."""
    with db.connect() as conn:
        finals = db.rows(conn.execute(
            "SELECT action, COUNT(*) n FROM audit WHERE user_id=? AND action LIKE 'answer.final.%'"
            " GROUP BY action", (user["id"],)))
        decisions = db.rows(conn.execute(
            "SELECT f.status, f.source, COUNT(*) n FROM findings f JOIN documents d ON d.id=f.doc_id"
            " WHERE d.user_id=? AND f.status!='pending' GROUP BY f.status, f.source", (user["id"],)))
        memories = conn.execute("SELECT COUNT(*), COALESCE(SUM(uses),0) FROM memories WHERE"
                                " user_id=? AND active=1", (user["id"],)).fetchone()
    answer_counts = {r["action"].split(".")[-1]: r["n"] for r in finals}
    total_answers = sum(answer_counts.values())
    accepted = answer_counts.get("approved", 0) + answer_counts.get("auto_approved", 0)
    finding_counts: dict[str, int] = {}
    for r in decisions:
        finding_counts[r["status"]] = finding_counts.get(r["status"], 0) + r["n"]
    total_findings = sum(finding_counts.values())
    return {
        "answers": answer_counts,
        "answer_acceptance": round(accepted / total_answers, 2) if total_answers else None,
        "findings": finding_counts,
        "false_positive_rate": round(finding_counts.get("dismissed", 0) / total_findings, 2)
        if total_findings else None,
        "memories_active": memories[0],
        "memory_applications": memories[1],
    }


def mount(app) -> None:
    app.include_router(router)

