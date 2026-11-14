"""Reversible PII redaction applied before any text leaves the server for the model.

Tokens are stable within a document ([EMAIL_1] always means the same address), so the model can
still reason about "the same person", and every model output is restored before a human sees it.
"""
from __future__ import annotations

import re
from typing import Any

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")),
    ("ACCOUNT", re.compile(r"(?i)\b(?:account|acct|routing|swift|aba)\s*(?:no\.?|number|#|:)?\s*"
                           r"[:#]?\s*([A-Z0-9-]{6,20})\b")),
    ("PHONE", re.compile(r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")),
    ("ADDRESS", re.compile(r"\b\d{1,6}\s+(?:[A-Z][a-z]+\s){1,4}(?:Street|St|Avenue|Ave|Road|Rd|"
                           r"Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|Suite|Place|Pl)\b\.?")),
]


class Redactor:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.forward: dict[str, str] = {}
        self.reverse: dict[str, str] = {}
        self.counts: dict[str, int] = {}

    def _token(self, kind: str, value: str) -> str:
        if value in self.forward:
            return self.forward[value]
        self.counts[kind] = self.counts.get(kind, 0) + 1
        token = f"[{kind}_{self.counts[kind]}]"
        self.forward[value] = token
        self.reverse[token] = value
        return token

    def redact(self, text: str) -> str:
        if not self.enabled or not text:
            return text
        for kind, pattern in PATTERNS:
            def sub(m: re.Match[str], kind: str = kind) -> str:
                if m.groups():
                    value = m.group(1)
                    return m.group(0).replace(value, self._token(kind, value))
                return self._token(kind, m.group(0))
            text = pattern.sub(sub, text)
        return text

    def restore(self, value: Any) -> Any:
        if not self.reverse:
            return value
        if isinstance(value, str):
            for token, original in self.reverse.items():
                value = value.replace(token, original)
            return value
        if isinstance(value, list):
            return [self.restore(v) for v in value]
        if isinstance(value, dict):
            return {k: self.restore(v) for k, v in value.items()}
        return value

    def report(self) -> dict[str, int]:
        return dict(self.counts)


def redact_clauses(clauses: list[dict[str, Any]], enabled: bool) -> tuple[list[dict[str, Any]], Redactor]:
    r = Redactor(enabled)
    return [{**c, "text": r.redact(c["text"]), "title": r.redact(c["title"])} for c in clauses], r
