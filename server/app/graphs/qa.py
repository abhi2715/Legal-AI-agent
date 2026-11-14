"""Question-answering workflow with grounded drafting and a policy-driven human gate.

    plan ─► clarify ⏸ ─► plan (only when the question is ambiguous)
      └──► retrieve ─► draft ─► verify ──(bad quotes, retry once)──► draft
                                  └─► gate ──(auto-approve allowed)──► finalize
                                        └─► human_review ⏸ ─ approve / edit / reject ─► finalize
                                                      └── revise (feedback, pins) ─► retrieve

Checkpoints from every step are kept, so the reviewer can rewind to any earlier point (for
example, before retrieval), change the question or pinned clauses, and fork a new branch.
"""
from __future__ import annotations

import difflib
import operator
import re
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .. import db, heuristics
from ..config import MAX_REVISIONS
from ..llm import engine
from ..retrieval import search
from ..schemas import CorrectionLesson, DraftAnswer, QueryPlan
from .common import Context, checkpointer, memories_block, merge_dict, trace


class QAState(TypedDict, total=False):
    thread_id: str
    doc_id: str
    user_id: str
    question: str
    clarification: str
    plan: dict[str, Any]
    hits: list[dict[str, Any]]
    pinned: list[str]
    excluded: list[str]
    draft: dict[str, Any]
    verification: dict[str, Any]
    attempts: int
    revisions: int
    feedback: str
    gate: dict[str, Any]
    review: dict[str, Any]
    final: dict[str, Any]
    memories_used: list[str]
    engines: Annotated[dict[str, str], merge_dict]
    trace: Annotated[list[dict[str, Any]], operator.add]


def _question(state: QAState) -> str:
    q = state["question"]
    if state.get("clarification"):
        q += f"\n(Reviewer clarified: {state['clarification']})"
    return q


# ── nodes ────────────────────────────────────────────────────────────────────

def plan(state: QAState) -> dict:
    ctx = Context(state["doc_id"], state["user_id"])
    allow_clarify = bool(ctx.user["ask_clarifications"]) and not state.get("clarification")
    task = f"""Plan how to answer the reviewer's question about the contract.

{ctx.perspective_brief()}

Question: {_question(state)}

Set needs_clarification=true ONLY if a competent lawyer could not answer without asking first
(for example "is this okay?" with no indication of what "this" is or okay by what standard).
{'' if allow_clarify else 'Clarification is not available: set needs_clarification=false.'}
search_queries should use the vocabulary the contract itself uses."""

    def fallback() -> QueryPlan:
        p = heuristics.plan_query(state["question"])
        if not allow_clarify:
            p.needs_clarification = False
        return p

    result, label = engine.structured(task, QueryPlan, fallback, document=ctx.document_text,
                                      effort="low")
    if not allow_clarify:
        result.needs_clarification = False
    msg = ("The question is ambiguous; asking the reviewer to clarify."
           if result.needs_clarification else
           f"Classified as {result.question_type}; searching for: " +
           "; ".join(result.search_queries[:3]))
    return {"plan": result.model_dump(), "engines": {"plan": label},
            "trace": trace("plan", msg, label)}


def clarify(state: QAState) -> dict:
    p = state["plan"]
    answer = interrupt({
        "type": "clarify",
        "question": p["clarifying_question"],
        "options": p["clarifying_options"],
    }) or {}
    text = (answer.get("answer") or "").strip() or "No clarification given; use best judgement."
    return {"clarification": text,
            "trace": trace("clarify", f"Reviewer clarified: {text}", actor="human")}


def retrieve(state: QAState) -> dict:
    ctx = Context(state["doc_id"], state["user_id"])
    p = state.get("plan", {})
    queries = [_question(state), *p.get("search_queries", [])]
    if state.get("feedback"):
        queries.append(state["feedback"])
    q_lower = state["question"].lower()
    term_clauses = [v["clause_id"] for t, v in ctx.doc["defined_terms"].items()
                    if t.lower() in q_lower and v.get("clause_id")]
    pinned = list(dict.fromkeys([*state.get("pinned", []), *term_clauses]))
    hits = search(ctx.doc["id"], ctx.clauses, queries, k=6, pinned=pinned,
                  excluded=state.get("excluded", []))
    out = [{"clause_id": h["clause"]["id"], "title": h["clause"]["title"], "score": h["score"],
            "reason": "defined term" if h["clause"]["id"] in term_clauses and
            h["clause"]["id"] not in state.get("pinned", []) else h["reason"]}
           for h in hits]
    msg = f"Retrieved {len(out)} clause(s): " + ", ".join(h["title"] for h in out[:4])
    if state.get("pinned") or state.get("excluded"):
        msg += (f" (honouring {len(state.get('pinned', []))} pinned, "
                f"{len(state.get('excluded', []))} excluded by reviewer)")
    return {"hits": out, "attempts": 0, "trace": trace("retrieve", msg)}


def draft(state: QAState) -> dict:
    ctx = Context(state["doc_id"], state["user_id"])
    p = state.get("plan", {})
    memories = [m for m in db.active_memories(ctx.user["id"], p.get("categories", []))
                if m["kind"] in ("correction", "style")]
    hits = state.get("hits", [])
    focus = "\n".join(f"- [{h['clause_id']}] {h['title']} ({h['reason']})" for h in hits)
    task = f"""Answer the reviewer's question about the contract.

{ctx.perspective_brief()}

Question: {_question(state)}

Most relevant clauses (retrieved and reviewer-steered):
{focus or '- none found'}
{('Do NOT rely on these clauses, the reviewer excluded them: ' + ', '.join(state['excluded'])) if state.get('excluded') else ''}

Lessons from this reviewer's past corrections. Apply them:
{memories_block(memories)}

Requirements:
- Every factual claim about the contract needs at least one verbatim quote with its clause_id.
- If the contract does not address the question, use answer_type 'contract_silent' and say so.
- Use 'needs_counsel' when the answer turns on law or facts outside the contract.
- confidence must be calibrated: below 0.6 if any material doubt remains.
- Keep the answer under 250 words unless the question needs more."""
    if state.get("feedback"):
        prev = state.get("draft", {}).get("answer", "")
        task += (f"\n\nThe reviewer sent back your previous draft with this feedback:\n"
                 f"{state['feedback']}\n\nPrevious draft:\n{prev}")
    bad = [q for c in state.get("verification", {}).get("claims", []) for q in c["quotes"]
           if not q["verified"]] if state.get("attempts", 0) else []
    if bad:
        task += ("\n\nYour last draft contained quotes that do not appear in the contract. Copy "
                 "text exactly or drop the claim:\n" + "\n".join(f"- {q['quote']}" for q in bad))

    def fallback() -> DraftAnswer:
        full = [{"clause": ctx.clause_map[h["clause_id"]], "score": h["score"]}
                for h in hits if h["clause_id"] in ctx.clause_map]
        return heuristics.draft_answer(state["question"], full, state.get("feedback", ""))

    result, label = engine.structured(task, DraftAnswer, fallback, document=ctx.document_text,
                                      effort="high" if p.get("question_type") in
                                      ("interpretation", "comparison") else None)
    data = ctx.restore(result.model_dump())
    data["confidence"] = max(0.0, min(1.0, float(data["confidence"])))
    db.mark_memories_used([m["id"] for m in memories])
    attempt = state.get("attempts", 0) + 1
    return {
        "draft": data,
        "attempts": attempt,
        "memories_used": [m["id"] for m in memories],
        "engines": {"draft": label},
        "trace": trace("draft", f"Draft {'revision ' + str(state.get('revisions', 0)) + ' ' if state.get('revisions') else ''}"
                       f"ready ({data['answer_type'].replace('_', ' ')}, confidence "
                       f"{data['confidence']:.0%})" + (f"; applied {len(memories)} learned lesson(s)"
                                                       if memories else "") + ".", label),
    }


_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    s = s.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    return _WS.sub(" ", s).strip().strip('"').strip("…").strip()


def locate(quote: str, clause: dict[str, Any] | None, doc_text: str,
           clauses: list[dict[str, Any]]) -> dict[str, Any]:
    q = _norm(quote)
    if len(q) < 4:
        return {"verified": False, "match": 0.0, "clause_id": None, "start": None, "end": None}
    candidates = ([clause] if clause else []) + [c for c in clauses if c is not clause]
    for c in candidates:
        text = _norm(c["text"])
        idx = text.lower().find(q.lower())
        if idx != -1:
            start = doc_text.lower().find(q.lower(), c["start"])
            return {"verified": True, "match": 1.0, "clause_id": c["id"],
                    "start": start if start != -1 else None,
                    "end": start + len(q) if start != -1 else None,
                    "moved": c is not clause}
    # Fuzzy: tolerate small transcription differences inside the cited clause.
    if clause:
        text = _norm(clause["text"])
        sm = difflib.SequenceMatcher(None, text.lower(), q.lower(), autojunk=False)
        blocks = sm.get_matching_blocks()
        matched = sum(b.size for b in blocks)
        ratio = matched / max(1, len(q))
        if ratio >= 0.9:
            return {"verified": True, "match": round(ratio, 2), "clause_id": clause["id"],
                    "start": None, "end": None, "fuzzy": True}
        return {"verified": False, "match": round(ratio, 2), "clause_id": clause["id"],
                "start": None, "end": None}
    return {"verified": False, "match": 0.0, "clause_id": None, "start": None, "end": None}


def verify(state: QAState) -> dict:
    """Deterministic check that every quote exists in the contract. No model involved."""
    ctx = Context(state["doc_id"], state["user_id"])
    d = state["draft"]
    claims_out = []
    total = ok = 0
    unsupported_claims = 0
    for claim in d.get("claims", []):
        quotes = []
        for q in claim.get("quotes", []):
            loc = locate(q["quote"], ctx.clause_map.get(q["clause_id"]), ctx.doc["text"], ctx.clauses)
            quotes.append({**q, **loc, "cited_clause_id": q["clause_id"],
                           "clause_id": loc["clause_id"] or q["clause_id"]})
            total += 1
            ok += int(loc["verified"])
        if not quotes:
            unsupported_claims += 1
        claims_out.append({"statement": claim["statement"], "quotes": quotes})
    grounded = ok / total if total else (1.0 if d["answer_type"] == "contract_silent" else 0.0)
    verification = {
        "claims": claims_out,
        "quotes_total": total,
        "quotes_verified": ok,
        "unsupported_claims": unsupported_claims,
        "grounded_ratio": round(grounded, 2),
    }
    msg = (f"Verified {ok}/{total} quotes against the contract text."
           if total else "No quotes to verify.")
    if unsupported_claims:
        msg += f" {unsupported_claims} claim(s) have no supporting quote."
    return {"verification": verification, "trace": trace("verify", msg)}


def after_verify(state: QAState) -> str:
    v = state["verification"]
    if v["quotes_verified"] < v["quotes_total"] and state.get("attempts", 0) < 2 and engine.online:
        return "draft"
    return "gate"


def gate(state: QAState) -> dict:
    ctx = Context(state["doc_id"], state["user_id"])
    policy = ctx.user["review_policy"]
    threshold = float(ctx.user["confidence_threshold"])
    d, v = state["draft"], state["verification"]
    reasons = []
    if d["confidence"] < threshold:
        reasons.append(f"confidence {d['confidence']:.0%} is below your {threshold:.0%} threshold")
    if v["quotes_verified"] < v["quotes_total"]:
        reasons.append(f"{v['quotes_total'] - v['quotes_verified']} quote(s) could not be verified")
    if v["unsupported_claims"]:
        reasons.append("some claims have no supporting quote")
    if d["answer_type"] == "needs_counsel":
        reasons.append("the answer depends on law or facts outside the contract")
    if state.get("plan", {}).get("question_type") == "interpretation":
        reasons.append("interpretation questions need a lawyer's judgement")

    # A safety floor that no policy can switch off.
    floor = [r for r in reasons if "could not be verified" in r or "outside the contract" in r]
    if policy == "always":
        required, why = True, "Your policy requires review of every answer."
    elif policy == "never":
        required = bool(floor)
        why = ("Review required despite your policy: " + "; ".join(floor)) if floor else \
            "Auto-approved by your policy."
    else:  # smart
        required = bool(reasons)
        why = ("Review needed: " + "; ".join(reasons)) if reasons else \
            "Auto-approved: high confidence and every quote verified."
    return {"gate": {"required": required, "reason": why, "policy": policy},
            "trace": trace("gate", why)}


def human_review(state: QAState) -> dict:
    decision = interrupt({
        "type": "answer_review",
        "draft": state["draft"],
        "verification": state["verification"],
        "hits": state.get("hits", []),
        "gate": state["gate"],
        "revisions": state.get("revisions", 0),
        "max_revisions": MAX_REVISIONS,
    }) or {}
    ctx = Context(state["doc_id"], state["user_id"])
    action = decision.get("action", "approve")
    db.audit(ctx.user["id"], f"human:{ctx.reviewer}", f"answer.{action}",
             {"feedback": decision.get("feedback", ""),
              "pinned": decision.get("pinned", []), "excluded": decision.get("excluded", []),
              "revision": state.get("revisions", 0)},
             doc_id=state["doc_id"], thread_id=state["thread_id"])
    out: dict[str, Any] = {
        "review": decision,
        "trace": trace("human_review", f"{ctx.reviewer} chose to {action}"
                       + (f": “{decision['feedback']}”" if decision.get("feedback") else "") + ".",
                       actor="human"),
    }
    if action == "revise":
        out.update({
            "feedback": decision.get("feedback", ""),
            "pinned": decision.get("pinned", state.get("pinned", [])),
            "excluded": decision.get("excluded", state.get("excluded", [])),
            "revisions": state.get("revisions", 0) + 1,
        })
    return out


def after_review(state: QAState) -> str:
    review = state.get("review", {})
    if review.get("action") == "revise" and state.get("revisions", 0) <= MAX_REVISIONS:
        return "retrieve"
    return "finalize"


def finalize(state: QAState) -> dict:
    ctx = Context(state["doc_id"], state["user_id"])
    gate_info = state.get("gate", {})
    review = state.get("review", {}) if gate_info.get("required") else {}
    draft_answer = state["draft"]["answer"]
    if not gate_info.get("required"):
        status, answer = "auto_approved", draft_answer
    else:
        action = review.get("action", "approve")
        status = {"approve": "approved", "edit": "edited", "reject": "rejected"}.get(action, "approved")
        answer = review.get("answer") or draft_answer

    lessons = []
    teach = (status == "edited" and answer.strip() != draft_answer.strip()) or \
        (status == "rejected" and review.get("feedback"))
    if teach:
        cats = state.get("plan", {}).get("categories", [])
        task = f"""The reviewer corrected an AI draft. Extract ONE reusable lesson for future drafts.

Question: {state['question']}
AI draft:
{draft_answer}

Reviewer's {'edited version' if status == 'edited' else 'rejection reason'}:
{answer if status == 'edited' else review.get('feedback')}

If the change only fixes a one-off fact, set worth_remembering=false. Otherwise phrase the lesson as
an instruction (e.g. "Always state notice periods in calendar days and cite the clause.")."""
        lesson, label = engine.structured(
            task, CorrectionLesson,
            lambda: heuristics.correction_lesson(review.get("feedback") or
                                                 _edit_summary(draft_answer, answer), cats),
            effort="low")
        if lesson.worth_remembering and lesson.lesson.strip():
            db.add_memory(ctx.user["id"], "correction", lesson.scope, lesson.lesson.strip(),
                          state["thread_id"])
            lessons.append(lesson.lesson.strip())

    final = {
        "status": status,
        "answer": answer,
        "reviewer": ctx.reviewer if status != "auto_approved" else None,
        "diff": _diff(draft_answer, answer) if status == "edited" else None,
        "lessons": lessons,
    }
    with db.connect() as conn:
        conn.execute("UPDATE threads SET status=?, answer=?, updated_at=? WHERE id=?",
                     (status, answer, db.now(), state["thread_id"]))
    db.audit(ctx.user["id"], "ai" if status == "auto_approved" else f"human:{ctx.reviewer}",
             f"answer.final.{status}",
             {"question": state["question"], "confidence": state["draft"]["confidence"],
              "grounded_ratio": state.get("verification", {}).get("grounded_ratio"),
              "lessons": lessons, "engine": state.get("engines", {}).get("draft")},
             doc_id=state["doc_id"], thread_id=state["thread_id"])
    msg = f"Answer {status.replace('_', ' ')}."
    if lessons:
        msg += f" Learned: “{lessons[0]}”"
    return {"final": final, "trace": trace("finalize", msg)}


def _diff(a: str, b: str) -> list[dict[str, str]]:
    sm = difflib.SequenceMatcher(None, a.split(), b.split())
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            out.append({"op": "eq", "text": " ".join(a.split()[i1:i2])})
        else:
            if i2 > i1:
                out.append({"op": "del", "text": " ".join(a.split()[i1:i2])})
            if j2 > j1:
                out.append({"op": "ins", "text": " ".join(b.split()[j1:j2])})
    return out


def _edit_summary(a: str, b: str) -> str:
    added = " ".join(d["text"] for d in _diff(a, b) if d["op"] == "ins")
    return f"Reviewer prefers answers that include: {added[:250]}" if added else ""


def route_plan(state: QAState) -> str:
    return "clarify" if state["plan"].get("needs_clarification") else "retrieve"


def route_gate(state: QAState) -> str:
    return "human_review" if state["gate"]["required"] else "finalize"


def build():
    g = StateGraph(QAState)
    for name, fn in [("plan", plan), ("clarify", clarify), ("retrieve", retrieve),
                     ("draft", draft), ("verify", verify), ("gate", gate),
                     ("human_review", human_review), ("finalize", finalize)]:
        g.add_node(name, fn)
    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", route_plan, ["clarify", "retrieve"])
    g.add_edge("clarify", "plan")
    g.add_edge("retrieve", "draft")
    g.add_edge("draft", "verify")
    g.add_conditional_edges("verify", after_verify, ["draft", "gate"])
    g.add_conditional_edges("gate", route_gate, ["human_review", "finalize"])
    g.add_conditional_edges("human_review", after_review, ["retrieve", "finalize"])
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


graph = build()
