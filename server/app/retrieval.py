"""Lexical clause retrieval (BM25) with legal synonym expansion and human steering.

BM25 is deliberate: contracts are short, vocabulary-precise documents, and lexical matching
gives exact, explainable hits without an embedding provider. The reviewer can pin clauses
(always included) or exclude them (never included) when asking for a revision.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from rank_bm25 import BM25Okapi

STOPWORDS = set(
    "a an the and or of to in for on at by with from as is are was were be been being this that "
    "these those it its their there here what which who whom whose when where why how can could "
    "will would shall should may might must do does did not no yes any all each such than then "
    "if so we our us you your they them he she his her i me my about into under over per".split()
)

SYNONYMS = {
    "terminate": ["termination", "cancel", "cancellation", "expire", "expiration", "end"],
    "liability": ["liable", "damages", "cap", "limitation", "consequential"],
    "indemnify": ["indemnification", "indemnity", "hold", "harmless", "defend"],
    "confidential": ["confidentiality", "nondisclosure", "disclose", "disclosure", "secret"],
    "pay": ["payment", "fee", "fees", "invoice", "price", "compensation", "sum"],
    "renew": ["renewal", "automatically", "extend", "extension", "term"],
    "law": ["governing", "jurisdiction", "venue", "courts"],
    "dispute": ["arbitration", "mediation", "court", "litigation"],
    "own": ["ownership", "intellectual", "property", "license", "copyright"],
    "assign": ["assignment", "transfer", "successor"],
    "data": ["personal", "privacy", "security", "breach", "protection"],
    "notice": ["notify", "notification", "written"],
    "warranty": ["warrant", "warranties", "represent", "representation"],
    "compete": ["competition", "noncompete", "solicit", "exclusive", "exclusivity"],
}
_SYN_INDEX = {}
for root, words in SYNONYMS.items():
    for w in [root, *words]:
        _SYN_INDEX.setdefault(w, set()).update([root, *words])


def stem(word: str) -> str:
    for suffix in ("ations", "ation", "ities", "ings", "ing", "ies", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def tokenize(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS]


def expand(query: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", query.lower())
    extra: list[str] = []
    for w in words:
        extra.extend(_SYN_INDEX.get(w, ()))
    return tokenize(" ".join(words + extra))


@lru_cache(maxsize=64)
def _index(doc_key: str, texts: tuple[str, ...]) -> BM25Okapi:
    return BM25Okapi([tokenize(t) or ["_"] for t in texts])


def search(
    doc_key: str,
    clauses: list[dict[str, Any]],
    queries: list[str],
    k: int = 6,
    pinned: list[str] | None = None,
    excluded: list[str] | None = None,
) -> list[dict[str, Any]]:
    pinned = pinned or []
    excluded = set(excluded or [])
    texts = tuple(f"{c['title']}\n{c['text']}" for c in clauses)
    bm25 = _index(doc_key, texts)

    best: dict[int, float] = {}
    for q in queries:
        tokens = expand(q)
        if not tokens:
            continue
        for i, score in enumerate(bm25.get_scores(tokens)):
            if score > best.get(i, 0.0):
                best[i] = float(score)

    ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
    top = ranked[0][1] if ranked else 0.0
    results: list[dict[str, Any]] = []
    for cid in pinned:
        clause = next((c for c in clauses if c["id"] == cid), None)
        if clause and cid not in excluded:
            results.append({"clause": clause, "score": 1.0, "reason": "pinned by reviewer"})
    for i, score in ranked:
        if len(results) >= k + len(pinned):
            break
        clause = clauses[i]
        if clause["id"] in excluded or any(r["clause"]["id"] == clause["id"] for r in results):
            continue
        if score <= 0 or (top and score < top * 0.2):
            continue
        results.append({
            "clause": clause,
            "score": round(score / top, 3) if top else 0.0,
            "reason": "lexical match",
        })
    return results
