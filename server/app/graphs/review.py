"""Contract review workflow.

    prepare ──► analyze_clauses ──► check_playbook ──┐
        └─────► extract_obligations ─────────────────┴─► score ──► human_triage ⏸
                                                                        │
                       ┌──── revise ◄── memo_review ⏸ ◄── draft_memo ◄── learn
                       └──────────────► draft_memo           │
                                                     approve/edit ──► finalize

⏸ = LangGraph interrupt. The run pauses, is checkpointed to SQLite and can resume days later,
from any server process. Nothing reaches the memo until a human has triaged the findings, and
the memo is not final until a human approves it.
"""
from __future__ import annotations

import json
import math
import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .. import db, heuristics
from ..config import MAX_REVISIONS
from ..llm import engine
from ..schemas import CATEGORIES, ClauseAnalysis, MemoDraft, ObligationList, PlaybookCheck
from .common import Context, checkpointer, memories_block, merge_dict, trace

RISK_WEIGHT = {"high": 25, "medium": 10, "low": 3, "none": 0}


class ReviewState(TypedDict, total=False):
    doc_id: str
    user_id: str
    analysis: dict[str, dict[str, Any]]
    summary: str
    playbook: list[dict[str, Any]]
    obligation_count: int
    risk_score: int
    risk_level: str
    triage: dict[str, Any]
    memo: str
    memo_feedback: str
    memo_revisions: int
    memo_decision: dict[str, Any]
    engines: Annotated[dict[str, str], merge_dict]
    trace: Annotated[list[dict[str, Any]], operator.add]


# ── nodes ────────────────────────────────────────────────────────────────────

def prepare(state: ReviewState) -> dict:
    ctx = Context(state["doc_id"], state["user_id"])
    redactions = ctx.redactor.report()
    db.update_document(ctx.doc["id"], status="analyzing",
                       redactions_json=json.dumps(redactions))
    db.audit(ctx.user["id"], "ai", "review.started",
             {"clauses": len(ctx.clauses), "redactions": redactions, "engine": engine.label},
             doc_id=ctx.doc["id"])
    msg = f"Loaded {len(ctx.clauses)} clauses."
    if redactions:
        msg += " Redacted before analysis: " + ", ".join(f"{v} {k.lower()}" for k, v in
                                                          redactions.items()) + "."
    elif ctx.user["privacy_redact"]:
        msg += " No personal data found to redact."
    return {"trace": trace("prepare", msg)}


def analyze_clauses(state: ReviewState) -> dict:
    ctx = Context(state["doc_id"], state["user_id"])
    dismissals = [m for m in db.active_memories(ctx.user["id"]) if m["kind"] == "dismissal"]
    task = f"""Review every clause of the contract from our side of the deal.

{ctx.perspective_brief()}

The reviewer has previously taught you these preferences. Follow them; they override your defaults:
{memories_block(dismissals)}

For EACH clause id in the contract ([c1], [c2], ...), return one assessment:
- category: the best-fitting category from the allowed list.
- risk: risk to OUR side. 'none' for boilerplate or clauses that favour us.
- issue_title / rationale: what is wrong for us and why, concretely (amounts, time limits, one-sidedness).
- suggested_redline: precise replacement language we could propose, or '' if no change is needed.
Also return the contracting parties and a 3-5 sentence executive summary written for the reviewer."""

    def fallback() -> ClauseAnalysis:
        return heuristics.analyze_clauses(
            ctx.clauses, ctx.doc["parties"], ctx.doc["perspective"],
            {m["source_ref"] for m in dismissals},
        )

    result, label = engine.structured(task, ClauseAnalysis, fallback, document=ctx.document_text,
                                      effort="high")
    result = ClauseAnalysis.model_validate(ctx.restore(result.model_dump()))
    db.mark_memories_used([m["id"] for m in dismissals])

    known = {c["id"] for c in ctx.clauses}
    analysis = {a.clause_id: a.model_dump() for a in result.clauses if a.clause_id in known}

    with db.connect() as conn:
        conn.execute("DELETE FROM findings WHERE doc_id=? AND source='ai'", (ctx.doc["id"],))
        for a in analysis.values():
            if a["risk"] == "none":
                continue
            conn.execute(
                "INSERT INTO findings (id, doc_id, clause_id, category, title, risk, rationale,"
                " suggestion, source, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (db.new_id("fnd"), ctx.doc["id"], a["clause_id"], a["category"],
                 a["issue_title"] or "Review clause", a["risk"], a["rationale"],
                 a["suggested_redline"], "ai", db.now()),
            )
    updates: dict[str, Any] = {"summary": result.executive_summary}
    if not ctx.doc["parties"] and result.parties:
        updates["parties_json"] = json.dumps([p.model_dump() for p in result.parties])
    db.update_document(ctx.doc["id"], **updates)

    flagged = sum(1 for a in analysis.values() if a["risk"] in ("medium", "high"))
    return {
        "analysis": analysis,
        "summary": result.executive_summary,
        "engines": {"analyze_clauses": label},
        "trace": trace("analyze_clauses",
                       f"Assessed {len(analysis)} clauses; {flagged} need attention."
                       + (f" Applied {len(dismissals)} learned preference(s)." if dismissals else ""),
                       label),
    }


def check_playbook(state: ReviewState) -> dict:
    ctx = Context(state["doc_id"], state["user_id"])
    with db.connect() as conn:
        rules = db.rows(conn.execute(
            "SELECT * FROM playbook_rules WHERE user_id=? AND enabled=1 ORDER BY created_at",
            (ctx.user["id"],)))
    if not rules:
        db.update_document(ctx.doc["id"], playbook_json="[]")
        return {"playbook": [], "trace": trace("check_playbook", "No playbook rules enabled.")}

    analysis = state.get("analysis", {})
    category_map = "\n".join(f"[{cid}] {a['category']}" for cid, a in analysis.items())
    rule_lines = "\n".join(f"- rule_id={r['id']} | {r['clause_type']} | {r['title']}: "
                           f"{r['requirement']}" for r in rules)
    task = f"""Check the contract against the reviewer's negotiation playbook.

{ctx.perspective_brief()}

Playbook rules:
{rule_lines}

Clause categories from the first pass:
{category_map}

For each rule return: status (compliant / deviation / missing / unverified / not_applicable), the
clause_ids you relied on, a one-to-two sentence explanation that cites the specific wording or
number, and suggested_redline language that would make the contract compliant ('' if compliant).
Use 'missing' when the contract has no clause on the topic at all; that is often the biggest risk."""

    def fallback() -> PlaybookCheck:
        return heuristics.check_playbook(rules, ctx.clauses, analysis)

    result, label = engine.structured(task, PlaybookCheck, fallback, document=ctx.document_text)
    result = PlaybookCheck.model_validate(ctx.restore(result.model_dump()))
    by_id = {r["id"]: r for r in rules}
    rows = []
    with db.connect() as conn:
        conn.execute("DELETE FROM findings WHERE doc_id=? AND source IN ('playbook','missing')",
                     (ctx.doc["id"],))
        for res in result.results:
            rule = by_id.get(res.rule_id)
            if not rule:
                continue
            rows.append({**res.model_dump(), "title": rule["title"], "requirement": rule["requirement"],
                         "severity": rule["severity"], "clause_type": rule["clause_type"]})
            if res.status in ("deviation", "missing"):
                conn.execute(
                    "INSERT INTO findings (id, doc_id, clause_id, category, title, risk, rationale,"
                    " suggestion, source, rule_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (db.new_id("fnd"), ctx.doc["id"], res.clause_ids[0] if res.clause_ids else None,
                     rule["clause_type"] if rule["clause_type"] in CATEGORIES else "other",
                     ("Missing: " if res.status == "missing" else "Playbook: ") + rule["title"],
                     rule["severity"], res.explanation, res.suggested_redline,
                     "missing" if res.status == "missing" else "playbook", rule["id"], db.now()),
                )
    db.update_document(ctx.doc["id"], playbook_json=json.dumps(rows))
    deviations = sum(1 for r in rows if r["status"] in ("deviation", "missing"))
    return {
        "playbook": rows,
        "engines": {"check_playbook": label},
        "trace": trace("check_playbook",
                       f"Checked {len(rows)} playbook rules; {deviations} deviation(s) or gap(s).",
                       label),
    }


def extract_obligations(state: ReviewState) -> dict:
    ctx = Context(state["doc_id"], state["user_id"])
    task = f"""Extract every obligation, deadline and recurring duty in the contract.

{ctx.perspective_brief()}

Include notice periods, payment dates, renewal/opt-out windows, reporting duties, and obligations
that survive termination. Use the party aliases. Compute due_date only when the contract gives
enough information for an exact calendar date; otherwise leave it ''."""

    def fallback() -> ObligationList:
        return heuristics.extract_obligations(ctx.clauses, ctx.doc["parties"])

    result, label = engine.structured(task, ObligationList, fallback, document=ctx.document_text)
    result = ObligationList.model_validate(ctx.restore(result.model_dump()))
    known = {c["id"] for c in ctx.clauses}
    with db.connect() as conn:
        conn.execute("DELETE FROM obligations WHERE doc_id=?", (ctx.doc["id"],))
        for o in result.obligations:
            conn.execute(
                "INSERT INTO obligations (id, doc_id, party, action, due, due_date, recurring,"
                " clause_id) VALUES (?,?,?,?,?,?,?,?)",
                (db.new_id("obl"), ctx.doc["id"], o.party, o.action, o.due, o.due_date or None,
                 o.recurring, o.clause_id if o.clause_id in known else None),
            )
    return {
        "obligation_count": len(result.obligations),
        "engines": {"extract_obligations": label},
        "trace": trace("extract_obligations",
                       f"Found {len(result.obligations)} obligations and deadlines.", label),
    }


def score(state: ReviewState) -> dict:
    with db.connect() as conn:
        findings = db.rows(conn.execute("SELECT risk FROM findings WHERE doc_id=?",
                                        (state["doc_id"],)))
    # Saturating curve: one high-risk issue ≈ 34, three ≈ 71; never pinned at 100 by volume alone.
    raw = sum(RISK_WEIGHT.get(f["risk"], 0) for f in findings)
    total = round(100 * (1 - math.exp(-raw / 60)))
    level = "High" if total >= 60 else "Medium" if total >= 30 else "Low"
    db.update_document(state["doc_id"], status="awaiting_triage", risk_score=total,
                       risk_level=level, engines_json=json.dumps(state.get("engines", {})))
    return {
        "risk_score": total,
        "risk_level": level,
        "trace": trace("score", f"Risk score {total}/100 ({level}) from {len(findings)} findings. "
                                "Waiting for human triage."),
    }


def human_triage(state: ReviewState) -> dict:
    with db.connect() as conn:
        pending = conn.execute(
            "SELECT COUNT(*) FROM findings WHERE doc_id=? AND status='pending'",
            (state["doc_id"],)).fetchone()[0]
    decision = interrupt({
        "type": "triage",
        "doc_id": state["doc_id"],
        "pending": pending,
        "message": "Accept, edit, dismiss or escalate each finding. Only findings you keep will "
                   "reach the memo.",
    })
    ctx = Context(state["doc_id"], state["user_id"])
    with db.connect() as conn:
        counts = {r["status"]: r["n"] for r in db.rows(conn.execute(
            "SELECT status, COUNT(*) n FROM findings WHERE doc_id=? GROUP BY status",
            (state["doc_id"],)))}
    db.update_document(state["doc_id"], status="drafting_memo")
    db.audit(ctx.user["id"], f"human:{ctx.reviewer}", "review.triage_submitted",
             {"counts": counts, "note": (decision or {}).get("note", "")}, doc_id=state["doc_id"])
    return {
        "triage": {"counts": counts},
        "trace": trace("human_triage", f"{ctx.reviewer} completed triage: " +
                       ", ".join(f"{v} {k}" for k, v in counts.items()), actor="human"),
    }


def learn(state: ReviewState) -> dict:
    """Turn triage decisions into transparent, editable reviewer preferences."""
    ctx = Context(state["doc_id"], state["user_id"])
    with db.connect() as conn:
        decided = db.rows(conn.execute(
            "SELECT * FROM findings WHERE doc_id=? AND status IN ('dismissed','edited')",
            (state["doc_id"],)))
    learned = 0
    for f in decided:
        if f["status"] == "dismissed" and f["source"] == "ai":
            reason = f["reviewer_note"].strip() or "the reviewer judged it acceptable"
            content = f"Do not flag '{f['title']}' ({f['category']}) as an issue when {reason}."
            db.add_memory(ctx.user["id"], "dismissal", f["category"], content, f["title"])
            learned += 1
        elif f["status"] == "edited" and f.get("final_suggestion"):
            content = (f"For {f['category'].replace('_', ' ')} issues like '{f['title']}', the reviewer "
                       f"prefers redlines in this style: \"{f['final_suggestion'][:400]}\"")
            db.add_memory(ctx.user["id"], "style", f["category"], content, f["id"])
            learned += 1
    if learned:
        db.audit(ctx.user["id"], "ai", "memory.learned", {"count": learned}, doc_id=state["doc_id"])
    return {"trace": trace("learn", f"Learned {learned} preference(s) from your decisions."
                           if learned else "No new preferences to learn.")}


def draft_memo(state: ReviewState) -> dict:
    ctx = Context(state["doc_id"], state["user_id"])
    with db.connect() as conn:
        findings = db.rows(conn.execute(
            "SELECT * FROM findings WHERE doc_id=? ORDER BY risk", (state["doc_id"],)))
    kept = [f for f in findings if f["status"] in ("accepted", "edited", "escalated")]
    feedback = state.get("memo_feedback", "")
    previous = state.get("memo", "")
    styles = [m for m in db.active_memories(ctx.user["id"]) if m["kind"] in ("style", "correction")]
    issue_lines = "\n".join(
        f"- [{f['status']}] {f['title']} ({f['risk']}, clause {f['clause_id'] or 'n/a'}): "
        f"{f['rationale']} | reviewer note: {f['reviewer_note'] or '-'} | redline: "
        f"{f['final_suggestion'] or f['suggestion'] or '-'}" for f in kept)
    task = f"""Draft a negotiation memo for the reviewer to send to their team or client.

{ctx.perspective_brief()}

Use ONLY these reviewer-confirmed issues (dismissed findings must not appear):
{issue_lines or '- none confirmed'}

Missing protections from the playbook:
{chr(10).join('- ' + p['title'] for p in state.get('playbook', []) if p['status'] == 'missing') or '- none'}

Reviewer style preferences:
{memories_block(styles)}

Structure: title, a two-sentence bottom line, issues ordered by priority with proposed language,
escalations called out, then next steps. Markdown. No preamble."""
    if feedback:
        task += f"\n\nThe reviewer asked for changes to the previous draft:\n{feedback}\n\nPrevious draft:\n{previous}"

    def fallback() -> MemoDraft:
        return MemoDraft(memo=heuristics.memo(ctx.doc, findings, state.get("playbook", []), feedback))

    result, label = engine.structured(task, MemoDraft, fallback, document=ctx.document_text)
    memo = ctx.restore(result.memo)
    db.update_document(state["doc_id"], memo=memo, memo_status="pending_approval",
                       status="awaiting_memo_approval")
    return {
        "memo": memo,
        "engines": {"draft_memo": label},
        "trace": trace("draft_memo", ("Revised" if feedback else "Drafted") +
                       f" memo from {len(kept)} confirmed issue(s). Waiting for approval.", label),
    }


def memo_review(state: ReviewState) -> dict:
    decision = interrupt({
        "type": "memo_review",
        "doc_id": state["doc_id"],
        "memo": state.get("memo", ""),
        "revisions": state.get("memo_revisions", 0),
        "max_revisions": MAX_REVISIONS,
    }) or {}
    ctx = Context(state["doc_id"], state["user_id"])
    action = decision.get("action", "approve")
    db.audit(ctx.user["id"], f"human:{ctx.reviewer}", f"memo.{action}",
             {"feedback": decision.get("feedback", ""), "edited": action == "edit"},
             doc_id=state["doc_id"])
    out: dict[str, Any] = {"memo_decision": decision,
                           "trace": trace("memo_review", f"{ctx.reviewer} chose to {action} the memo.",
                                          actor="human")}
    if action == "revise":
        out["memo_feedback"] = decision.get("feedback", "")
        out["memo_revisions"] = state.get("memo_revisions", 0) + 1
    elif action == "edit":
        out["memo"] = decision.get("memo", state.get("memo", ""))
    return out


def finalize(state: ReviewState) -> dict:
    ctx = Context(state["doc_id"], state["user_id"])
    decision = state.get("memo_decision", {})
    status = "edited" if decision.get("action") == "edit" else "approved"
    db.update_document(state["doc_id"], memo=state.get("memo", ""), memo_status=status,
                       status="reviewed")
    db.audit(ctx.user["id"], f"human:{ctx.reviewer}", "review.completed",
             {"memo_status": status}, doc_id=state["doc_id"])
    return {"trace": trace("finalize", f"Review complete. Memo {status} by {ctx.reviewer}.")}


def after_memo_review(state: ReviewState) -> str:
    decision = state.get("memo_decision", {})
    if decision.get("action") == "revise" and state.get("memo_revisions", 0) <= MAX_REVISIONS:
        return "draft_memo"
    return "finalize"


def build():
    g = StateGraph(ReviewState)
    for name, fn in [
        ("prepare", prepare), ("analyze_clauses", analyze_clauses),
        ("check_playbook", check_playbook), ("extract_obligations", extract_obligations),
        ("score", score), ("human_triage", human_triage), ("learn", learn),
        ("draft_memo", draft_memo), ("memo_review", memo_review), ("finalize", finalize),
    ]:
        g.add_node(name, fn)
    g.add_edge(START, "prepare")
    g.add_edge("prepare", "analyze_clauses")
    g.add_edge("prepare", "extract_obligations")
    g.add_edge("analyze_clauses", "check_playbook")
    g.add_edge(["check_playbook", "extract_obligations"], "score")
    g.add_edge("score", "human_triage")
    g.add_edge("human_triage", "learn")
    g.add_edge("learn", "draft_memo")
    g.add_edge("draft_memo", "memo_review")
    g.add_conditional_edges("memo_review", after_memo_review, ["draft_memo", "finalize"])
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


graph = build()
