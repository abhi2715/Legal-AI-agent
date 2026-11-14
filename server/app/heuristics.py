"""Deterministic offline implementations of every model-backed step.

They are intentionally conservative: they extract and flag rather than interpret, they never
claim compliance they cannot verify (status `unverified`), and they report low confidence so
the human gate stays engaged.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from .retrieval import expand, tokenize
from .schemas import (
    Claim,
    ClauseAnalysis,
    ClauseAssessment,
    CorrectionLesson,
    DraftAnswer,
    Obligation,
    ObligationList,
    Party,
    PlaybookCheck,
    PlaybookResult,
    QueryPlan,
    Quote,
)

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "definitions": ["shall mean", "means", "definitions", "defined"],
    "termination": ["terminat", "cancel"],
    "renewal": ["renew", "automatically extend"],
    "term": ["term of this agreement", "commence", "effective date", "expire"],
    "payment": ["pay", "fee", "invoice", "price", "$", "compensation"],
    "liability": ["liabilit", "liable", "consequential", "damages"],
    "indemnification": ["indemn", "hold harmless", "defend"],
    "confidentiality": ["confidential", "non-disclosure", "nondisclosure"],
    "ip": ["intellectual property", "copyright", "license", "ownership", "trademark"],
    "non_compete": ["compete", "solicit"],
    "exclusivity": ["exclusive"],
    "governing_law": ["governing law", "governed by", "laws of the state"],
    "dispute_resolution": ["arbitrat", "mediat", "dispute", "venue", "jurisdiction"],
    "warranty": ["warrant", "represent", "as is"],
    "insurance": ["insurance", "insured"],
    "assignment": ["assign", "transfer this agreement"],
    "data_protection": ["personal data", "privacy", "hipaa", "security breach", "protected health"],
    "force_majeure": ["force majeure", "act of god"],
    "notices": ["notice shall", "notices", "written notice to"],
    "audit": ["audit", "inspect", "books and records"],
    "signature": ["/s/", "signature", "in witness whereof", "executed"],
    "parties": ["by and between", "entered into"],
}

RISK_PATTERNS: list[tuple[str, str, str, str, str, str]] = [
    # regex, category, risk, title, rationale, suggested redline
    (r"unlimited liability|uncapped|without limit(ation)? (of|on) liability", "liability", "high",
     "Uncapped liability", "Exposure is not limited to any amount.",
     "Each party's aggregate liability shall not exceed the fees paid in the twelve (12) months "
     "preceding the claim."),
    (r"any and all (claims|losses|damages|liabilities)", "indemnification", "high",
     "Broad indemnity", "The indemnity covers 'any and all' losses, which can reach well beyond "
     "third-party claims.",
     "…shall indemnify the other party against third-party claims to the extent caused by its "
     "breach or negligence."),
    (r"automatic(ally)? renew", "renewal", "medium", "Automatic renewal",
     "The contract renews by default; missing the notice window locks you in.",
     "This Agreement renews only upon mutual written agreement, or either party may opt out with "
     "30 days' notice."),
    (r"(terminate|cancel)[^.]{0,80}(at any time|for any reason|without cause|for convenience)",
     "termination", "medium", "Termination at will",
     "One party can end the agreement without cause; check whether that right is mutual.",
     "Either party may terminate for convenience on thirty (30) days' written notice."),
    (r"perpetu|irrevocabl", "ip", "medium", "Perpetual or irrevocable grant",
     "Rights granted forever cannot be withdrawn if the relationship ends.",
     "…a license for the term of this Agreement, revocable upon termination."),
    (r"non-?compet|shall not (directly or indirectly )?compete", "non_compete", "high",
     "Non-compete restriction", "Restricts future business; enforceability varies by jurisdiction.",
     "Limit the restriction to direct competitors, 12 months, and the territory actually served."),
    (r"exclusiv", "exclusivity", "medium", "Exclusivity",
     "Exclusivity limits who else you can work with.", "Make exclusivity conditional on minimum "
     "volumes and limited in time."),
    (r"liquidated damages", "liability", "medium", "Liquidated damages",
     "Pre-set damages apply regardless of actual loss.", "Cap liquidated damages and make them the "
     "sole remedy for the specific breach."),
    (r"sole (and absolute )?discretion", "other", "medium", "Sole discretion",
     "One party can decide unilaterally with no reasonableness standard.",
     "Replace 'sole discretion' with 'reasonable discretion, not to be unreasonably withheld'."),
    (r"waive[^.]{0,40}(jury|class action)", "dispute_resolution", "medium", "Waiver of rights",
     "Waives procedural rights such as jury trial or class actions.", ""),
    (r"without (prior )?notice", "other", "medium", "Action without notice",
     "Allows action without notice, leaving no time to cure.",
     "…upon thirty (30) days' prior written notice and an opportunity to cure."),
    (r"as is|disclaims? (all|any) warrant", "warranty", "medium", "Warranty disclaimer",
     "Warranties are disclaimed, so there is little recourse if the deliverable fails.",
     "Add a warranty that services will be performed in a professional and workmanlike manner."),
    (r"not be liable[^.]{0,120}(refund|any reason|cancel)", "liability", "medium",
     "One-sided liability exclusion", "One party excludes liability, possibly including refunds.",
     "Any cancellation by Promoter entitles Sponsor to a full refund of amounts paid."),
    (r"\d+(\.\d+)?\s?% (per|a) month|interest[^.]{0,40}\d+(\.\d+)?\s?%", "payment", "low",
     "Late payment interest", "Interest or late fees apply to overdue amounts.", ""),
    (r"arbitrat", "dispute_resolution", "low", "Arbitration",
     "Disputes go to arbitration rather than court; check seat, rules and cost allocation.", ""),
]


def categorize(text: str) -> str:
    low = text.lower()
    best, hits = "other", 0
    for cat, words in CATEGORY_KEYWORDS.items():
        n = sum(low.count(w) for w in words)
        if n > hits:
            best, hits = cat, n
    return best


def analyze_clauses(clauses: list[dict[str, Any]], parties: list[dict[str, str]],
                    perspective: str, dismissed_patterns: set[str]) -> ClauseAnalysis:
    out: list[ClauseAssessment] = []
    for c in clauses:
        low = c["text"].lower()
        category = categorize(c["text"])
        match = None
        for pattern, cat, risk, title, rationale, redline in RISK_PATTERNS:
            if re.search(pattern, low) and title not in dismissed_patterns:
                match = (cat, risk, title, rationale, redline)
                break
        if match:
            cat, risk, title, rationale, redline = match
            if perspective and perspective.lower() in low:
                rationale += f" The clause names {perspective} directly."
            out.append(ClauseAssessment(
                clause_id=c["id"], category=cat if category == "other" else category, risk=risk,
                issue_title=title, rationale=rationale, suggested_redline=redline, favours="unclear",
            ))
        else:
            out.append(ClauseAssessment(
                clause_id=c["id"], category=category, risk="none", issue_title="", rationale="",
                suggested_redline="", favours="unclear",
            ))
    first = clauses[0]["text"] if clauses else ""
    summary = (
        f"Offline extractive review of {len(clauses)} clauses. "
        f"{sum(1 for a in out if a.risk in ('medium', 'high'))} clauses matched known risk patterns. "
        "Connect a model for reasoning-based analysis. Opening text: "
        + (first[:220] + ("…" if len(first) > 220 else ""))
    )
    return ClauseAnalysis(
        parties=[Party(**p) for p in parties], executive_summary=summary, clauses=out,
    )


def check_playbook(rules: list[dict[str, Any]], clauses: list[dict[str, Any]],
                   analysis: dict[str, dict[str, Any]]) -> PlaybookCheck:
    results = []
    for rule in rules:
        matching = [c for c in clauses
                    if analysis.get(c["id"], {}).get("category") == rule["clause_type"]
                    or categorize(c["text"]) == rule["clause_type"]]
        if not matching:
            results.append(PlaybookResult(
                rule_id=rule["id"], status="missing", clause_ids=[],
                explanation=f"No clause addressing {rule['clause_type'].replace('_', ' ')} was found.",
                suggested_redline="",
            ))
            continue
        risky = [c for c in matching if analysis.get(c["id"], {}).get("risk") in ("medium", "high")]
        if risky:
            results.append(PlaybookResult(
                rule_id=rule["id"], status="deviation", clause_ids=[c["id"] for c in risky],
                explanation="A risk pattern was detected in the relevant clause. Check it against: "
                            + rule["requirement"],
                suggested_redline=analysis[risky[0]["id"]].get("suggested_redline", ""),
            ))
        else:
            results.append(PlaybookResult(
                rule_id=rule["id"], status="unverified", clause_ids=[c["id"] for c in matching],
                explanation="A relevant clause exists, but offline mode cannot judge whether it "
                            "meets the requirement. Verify manually.",
                suggested_redline="",
            ))
    return PlaybookCheck(results=results)


_DUE = re.compile(
    r"(within\s+\w+(?:\s*\(\d+\))?\s+(?:business\s+|calendar\s+)?(?:days?|weeks?|months?)"
    r"(?:\s+(?:of|after|from|following|prior to|before)\s+[^,.;]{3,60})?|"
    r"(?:no later than|by|before|on or before)\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4}|"
    r"\b(?:monthly|quarterly|annually|weekly|each month|each year)\b)",
    re.I,
)
_DATE = re.compile(r"([A-Z][a-z]+\.?\s+\d{1,2},\s+\d{4})")
_OBLIG = re.compile(r"\b(shall|must|agrees? to|is required to|will)\b", re.I)


def parse_date(s: str) -> str:
    s = s.replace(".", "")
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def extract_obligations(clauses: list[dict[str, Any]], parties: list[dict[str, str]]) -> ObligationList:
    aliases = [p["alias"] for p in parties] or []
    out: list[Obligation] = []
    for c in clauses:
        for sentence in re.split(r"(?<=[.;])\s+", c["text"]):
            if not _OBLIG.search(sentence) or len(sentence) < 25:
                continue
            if re.search(r"\bshall (not )?mean\b|\bshall be governed\b", sentence, re.I):
                continue
            head = sentence[: _OBLIG.search(sentence).start()]
            party = next((a for a in aliases if a.lower() in head.lower()), "")
            if not party:
                if re.search(r"\beach party|\bthe parties|\bboth parties", head, re.I):
                    party = "Both parties"
                else:
                    continue
            due_m = _DUE.search(sentence)
            due = due_m.group(0) if due_m else ""
            date_m = _DATE.search(due) if due else None
            recurring = next((w for w in ("monthly", "quarterly", "annually", "weekly")
                              if w in sentence.lower()), "")
            action = sentence.strip()
            if len(action) > 220:
                action = action[:217] + "…"
            out.append(Obligation(
                party=party, action=action, due=due,
                due_date=parse_date(date_m.group(1)) if date_m else "",
                recurring=recurring, clause_id=c["id"],
            ))
    return ObligationList(obligations=out[:60])


VAGUE = re.compile(r"^(is (this|it)|what about|explain|thoughts|ok(ay)?|good|bad|any issues?)\b", re.I)


def plan_query(question: str) -> QueryPlan:
    q = question.strip()
    words = tokenize(q)
    vague = len(words) <= 1 or (bool(VAGUE.match(q)) and len(words) <= 3)
    cats = []
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(k.strip() in q.lower() for k in kws):
            cats.append(cat)
    return QueryPlan(
        needs_clarification=vague,
        clarifying_question=(
            "Which part of the contract should I focus on?" if vague else ""
        ),
        clarifying_options=(
            ["Termination and exit rights", "Liability and indemnities", "Payment terms",
             "Overall risk summary"] if vague else []
        ),
        question_type="summary" if re.search(r"summar|overview", q, re.I) else "lookup",
        search_queries=[q],
        categories=cats[:4],
    )


def draft_answer(question: str, hits: list[dict[str, Any]], feedback: str) -> DraftAnswer:
    qtokens = set(expand(question))
    scored: list[tuple[float, str, str]] = []
    for h in hits:
        c = h["clause"]
        for sentence in re.split(r"(?<=[.;:])\s+", c["text"]):
            s = sentence.strip()
            if len(s) < 25:
                continue
            overlap = len(qtokens & set(tokenize(s)))
            if overlap:
                scored.append((overlap + h["score"], c["id"], s))
    scored.sort(key=lambda t: t[0], reverse=True)
    top = scored[:3]
    if not top:
        return DraftAnswer(
            answer="I could not find language in this contract that addresses the question. "
                   "The contract may be silent on it. Check the full text before relying on this.",
            answer_type="contract_silent", claims=[], confidence=0.35,
            caveats=["Offline extractive mode: no model reasoning was applied."],
            follow_up_questions=[],
        )
    titles = {h["clause"]["id"]: h["clause"]["title"] for h in hits}
    lines = [f"- **{titles[cid]}**: “{s}”" for _, cid, s in top]
    answer = "The most relevant contract language:\n\n" + "\n".join(lines)
    if feedback:
        answer += f"\n\n_Revised per reviewer feedback: {feedback}_"
    confidence = min(0.6, 0.25 + 0.08 * top[0][0])
    return DraftAnswer(
        answer=answer, answer_type="partially_answered",
        claims=[Claim(statement=f"Relevant language in {titles[cid]}",
                      quotes=[Quote(clause_id=cid, quote=s)]) for _, cid, s in top],
        confidence=round(confidence, 2),
        caveats=["Offline extractive mode: these are quoted passages, not an interpretation."],
        follow_up_questions=[],
    )


def correction_lesson(feedback: str, categories: list[str]) -> CorrectionLesson:
    text = feedback.strip()
    return CorrectionLesson(
        worth_remembering=len(text) > 12,
        lesson=text[:300],
        scope=(categories[0] if categories else "general"),  # type: ignore[arg-type]
    )


def memo(doc: dict[str, Any], findings: list[dict[str, Any]], playbook: list[dict[str, Any]],
         feedback: str) -> str:
    accepted = [f for f in findings if f["status"] in ("accepted", "edited", "escalated")]
    order = {"high": 0, "medium": 1, "low": 2, "none": 3}
    accepted.sort(key=lambda f: order.get(f["risk"], 3))
    lines = [
        f"# Review memo: {doc['name']}",
        "",
        f"**Our side:** {doc.get('perspective') or 'not set'}  ",
        f"**Counterparty:** {doc.get('counterparty') or 'not set'}  ",
        f"**Date:** {date.today().isoformat()}",
        "",
        "## Issues to negotiate",
    ]
    if not accepted:
        lines.append("No issues were confirmed by the reviewer.")
    for i, f in enumerate(accepted, 1):
        lines.append(f"{i}. **{f['title']}** ({f['risk']} risk). {f['rationale']}")
        if f.get("reviewer_note"):
            lines.append(f"   - Reviewer note: {f['reviewer_note']}")
        redline = f.get("final_suggestion") or f.get("suggestion")
        if redline:
            lines.append(f"   - Proposed language: “{redline}”")
        if f["status"] == "escalated":
            lines.append("   - **Escalated to senior counsel.**")
    missing = [p for p in playbook if p.get("status") == "missing"]
    if missing:
        lines += ["", "## Missing protections"]
        lines += [f"- {p['title']}: {p['requirement']}" for p in missing]
    if feedback:
        lines += ["", f"_Revision note: {feedback}_"]
    return "\n".join(lines)
