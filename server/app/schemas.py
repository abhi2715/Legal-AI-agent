"""Structured-output contracts between LangGraph nodes and the model.

Every model call returns one of these validated shapes; nothing downstream parses free text.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "parties", "term", "termination", "renewal", "payment", "liability", "indemnification",
    "confidentiality", "ip", "non_compete", "exclusivity", "governing_law", "dispute_resolution",
    "warranty", "insurance", "assignment", "data_protection", "force_majeure", "notices",
    "audit", "definitions", "signature", "other",
]
CATEGORIES: list[str] = list(Category.__args__)  # type: ignore[attr-defined]
Risk = Literal["none", "low", "medium", "high"]


class Party(BaseModel):
    alias: str = Field(description="Short name used in the contract, e.g. 'Client'")
    name: str = Field(description="Full legal name as written")


class ClauseAssessment(BaseModel):
    clause_id: str
    category: Category
    risk: Risk = Field(description="Risk to OUR side (the reviewer's perspective)")
    issue_title: str = Field(description="Short headline of the issue, or '' when risk is none")
    rationale: str = Field(description="Why this matters for our side, 1-3 sentences")
    suggested_redline: str = Field(
        description="Replacement wording we could propose, or '' if no change is needed"
    )
    favours: Literal["us", "counterparty", "balanced", "unclear"]


class ClauseAnalysis(BaseModel):
    parties: list[Party]
    executive_summary: str = Field(description="3-5 sentences, plain language")
    clauses: list[ClauseAssessment]


class PlaybookResult(BaseModel):
    rule_id: str
    status: Literal["compliant", "deviation", "missing", "unverified", "not_applicable"]
    clause_ids: list[str]
    explanation: str
    suggested_redline: str


class PlaybookCheck(BaseModel):
    results: list[PlaybookResult]


class Obligation(BaseModel):
    party: str = Field(description="Alias of the obligated party")
    action: str = Field(description="What must be done, imperative, under 25 words")
    due: str = Field(description="Timing as written in the contract, or ''")
    due_date: str = Field(description="ISO date YYYY-MM-DD if a calendar date can be computed, else ''")
    recurring: str = Field(description="e.g. 'monthly', 'annually', or ''")
    clause_id: str


class ObligationList(BaseModel):
    obligations: list[Obligation]


class QueryPlan(BaseModel):
    needs_clarification: bool = Field(
        description="True only if the question cannot be answered well without more information"
    )
    clarifying_question: str
    clarifying_options: list[str] = Field(description="2-4 short answer options, or []")
    question_type: Literal["lookup", "interpretation", "comparison", "summary", "drafting"]
    search_queries: list[str] = Field(description="2-4 retrieval queries using contract vocabulary")
    categories: list[Category]


class Quote(BaseModel):
    clause_id: str
    quote: str = Field(description="Verbatim excerpt copied exactly from the clause")


class Claim(BaseModel):
    statement: str
    quotes: list[Quote]


class DraftAnswer(BaseModel):
    answer: str = Field(description="Markdown answer for the reviewer")
    answer_type: Literal["answered", "partially_answered", "contract_silent", "needs_counsel"]
    claims: list[Claim]
    confidence: float = Field(description="0.0-1.0 calibrated confidence the answer is correct")
    caveats: list[str]
    follow_up_questions: list[str]


class CorrectionLesson(BaseModel):
    worth_remembering: bool = Field(
        description="False if the edit was a one-off fact fix with no reusable lesson"
    )
    lesson: str = Field(description="A reusable instruction for future drafts, one sentence")
    scope: Category | Literal["general"]


class MemoDraft(BaseModel):
    memo: str = Field(description="Negotiation memo in Markdown")


def strict_json_schema(model: type[BaseModel]) -> dict:
    """Pydantic schema → strict JSON schema accepted by structured outputs."""
    schema = model.model_json_schema()

    def walk(node):
        if isinstance(node, dict):
            node.pop("default", None)
            node.pop("title", None)
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    return schema
