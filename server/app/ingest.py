"""Document ingestion: file parsing, clause segmentation, defined terms and party detection.

Clauses are the unit of everything downstream (retrieval, findings, citations), so each one keeps
stable character offsets into the normalized text and the page it starts on. That is what lets
the UI jump from a citation straight to the highlighted passage.
"""
from __future__ import annotations

import io
import re
from typing import Any

import docx
import pypdf


class IngestError(ValueError):
    pass


def extract_text(filename: str, data: bytes) -> tuple[str, list[int]]:
    """Return normalized text and the character offset at which each page starts."""
    name = filename.lower()
    pages: list[str]
    if name.endswith(".pdf"):
        try:
            reader = pypdf.PdfReader(io.BytesIO(data))
            pages = [(p.extract_text() or "") for p in reader.pages]
        except Exception as exc:  # pypdf raises many exception types for malformed files
            raise IngestError(f"Could not read PDF: {exc}") from exc
        if not "".join(pages).strip():
            raise IngestError(
                "This PDF has no extractable text (it may be a scanned image). "
                "Run OCR on it first, then upload again."
            )
    elif name.endswith(".docx"):
        try:
            document = docx.Document(io.BytesIO(data))
        except Exception as exc:
            raise IngestError(f"Could not read DOCX: {exc}") from exc
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for r in table.rows:
                parts.append(" | ".join(c.text.strip() for c in r.cells))
        pages = ["\n".join(parts)]
    elif name.endswith((".txt", ".md")):
        pages = [data.decode("utf-8", errors="replace")]
    else:
        raise IngestError("Unsupported file type. Upload a PDF, DOCX or TXT file.")

    text_parts: list[str] = []
    page_starts: list[int] = []
    offset = 0
    for page in pages:
        cleaned = normalize(page)
        page_starts.append(offset)
        text_parts.append(cleaned)
        offset += len(cleaned) + 2
    text = "\n\n".join(text_parts).strip()
    if len(text) < 20:
        raise IngestError("The document is empty or too short to analyze.")
    return text, page_starts


def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    lines = [re.sub(r"[ \t]{2,}", " ", ln).strip() for ln in text.split("\n")]
    out = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", out)


# ── clause segmentation ──────────────────────────────────────────────────────

_HEADING_PATTERNS = [
    re.compile(r"^(article|section|clause)\s+[\dIVXLC]+(\.\d+)*\b", re.I),
    re.compile(r"^\d{1,2}(\.\d{1,2})*[.)]?\s+[A-Z\"“]"),
    re.compile(r"^[A-Z][A-Z0-9 ,;&/'\-]{3,70}$"),
]
_SUBITEM = re.compile(r"^(\(?[a-z]{1,3}[.)]|\(?[ivx]{1,4}[.)])\s", re.I)
MAX_CLAUSE_CHARS = 2400


def _is_heading(line: str) -> bool:
    if not line or _SUBITEM.match(line):
        return False
    return any(p.match(line) for p in _HEADING_PATTERNS)


def _title_for(text: str, index: int) -> str:
    lines = [ln for ln in text.strip().split("\n") if ln.strip() and not ln.strip().isdigit()]
    first = lines[0] if lines else ""
    if first.isupper() and len(lines) > 1 and _HEADING_PATTERNS[1].match(lines[1]):
        first = lines[1]
    m = re.match(r"^((?:article|section|clause)?\s*[\dIVX]+(?:\.\d+)*[.)]?\s*)([^.:\n]{2,80})", first,
                 re.I)
    if m:
        return (m.group(1) + m.group(2)).strip().rstrip(".")
    if first.isupper() and len(first) <= 80:
        return first.title()
    words = first.split()
    return " ".join(words[:8]) + ("…" if len(words) > 8 else "") if words else f"Clause {index + 1}"


def segment_clauses(text: str, page_starts: list[int]) -> list[dict[str, Any]]:
    spans: list[tuple[int, int]] = []
    pos = 0
    current_start: int | None = None
    for line in text.split("\n"):
        line_start = pos
        pos += len(line) + 1
        if _is_heading(line.strip()):
            if current_start is not None and text[current_start:line_start].strip():
                spans.append((current_start, line_start))
            current_start = line_start
        elif current_start is None and line.strip():
            current_start = line_start
    if current_start is not None:
        spans.append((current_start, len(text)))

    # Too few headings → fall back to paragraphs.
    if len(spans) < 3:
        spans = [(m.start(), m.end()) for m in re.finditer(r"[^\n](?:.|\n(?!\n))*", text)]

    # Merge tiny fragments (e.g. a lone all-caps heading line) into the following span.
    merged: list[tuple[int, int]] = []
    carry: int | None = None
    for s, e in spans:
        s = carry if carry is not None else s
        if len(text[s:e].strip()) < 60:
            carry = s
            continue
        carry = None
        merged.append((s, e))
    if carry is not None:
        if merged:
            merged[-1] = (merged[-1][0], len(text))
        else:
            merged.append((carry, len(text)))

    # Split oversized spans on paragraph, then sentence, boundaries.
    final: list[tuple[int, int]] = []
    for s, e in merged:
        final.extend(_split_long(text, s, e))

    clauses = []
    for i, (s, e) in enumerate(final):
        chunk = text[s:e]
        lead = len(chunk) - len(chunk.lstrip())
        trail = len(chunk.rstrip())
        s2, e2 = s + lead, s + trail
        body = text[s2:e2]
        if not body:
            continue
        page = 1
        for p_index, p_start in enumerate(page_starts):
            if s2 >= p_start:
                page = p_index + 1
        clauses.append({
            "id": f"c{len(clauses) + 1}",
            "index": len(clauses),
            "title": _title_for(body, len(clauses)),
            "text": body,
            "start": s2,
            "end": e2,
            "page": page,
        })
    return clauses


def _split_long(text: str, s: int, e: int) -> list[tuple[int, int]]:
    if e - s <= MAX_CLAUSE_CHARS:
        return [(s, e)]
    out: list[tuple[int, int]] = []
    cut_start = s
    while e - cut_start > MAX_CLAUSE_CHARS:
        window = text[cut_start:cut_start + MAX_CLAUSE_CHARS]
        cut = window.rfind("\n\n")
        if cut < MAX_CLAUSE_CHARS // 3:
            cut = max(window.rfind(". "), window.rfind(".\n"))
            cut = cut + 1 if cut > MAX_CLAUSE_CHARS // 3 else MAX_CLAUSE_CHARS
        out.append((cut_start, cut_start + cut))
        cut_start += cut
    out.append((cut_start, e))
    return out


# ── defined terms & parties ──────────────────────────────────────────────────

_QUOTE = r"[\"“”']"
_DEF_PATTERNS = [
    re.compile(rf"{_QUOTE}([A-Z][\w\- ]{{1,40}}){_QUOTE}\s+(?:shall\s+)?(?:mean|means|refers? to|"
               r"includes?)\b"),
    re.compile(rf"\((?:the\s+|hereinafter\s+(?:referred\s+to\s+as\s+)?(?:the\s+)?|each\s+a\s+|"
               rf"collectively\s+)?{_QUOTE}([A-Z][\w\- ]{{1,40}}){_QUOTE}\)"),
]
_GENERIC_TERMS = {"agreement", "party", "parties", "effective date", "this agreement"}


def _sentence_around(text: str, idx: int, limit: int = 360) -> str:
    start = max(text.rfind(". ", 0, idx), text.rfind("\n", 0, idx)) + 1
    end_candidates = [i for i in (text.find(". ", idx), text.find("\n", idx)) if i != -1]
    end = min(end_candidates) + 1 if end_candidates else len(text)
    sentence = text[start:end].strip()
    return sentence if len(sentence) <= limit else sentence[: limit - 1] + "…"


def defined_terms(text: str, clauses: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    terms: dict[str, dict[str, Any]] = {}
    for pattern in _DEF_PATTERNS:
        for m in pattern.finditer(text):
            term = m.group(1).strip()
            if term.lower() in _GENERIC_TERMS or term in terms:
                continue
            clause_id = next((c["id"] for c in clauses if c["start"] <= m.start() < c["end"]), None)
            terms[term] = {
                "definition": _sentence_around(text, m.start()),
                "clause_id": clause_id,
            }
    return dict(list(terms.items())[:80])


def detect_parties(text: str) -> list[dict[str, str]]:
    head = text[:4000]
    m = re.search(r"\bbetween\b(.{10,900}?)(?:\)\s*\.|\n|WHEREAS|RECITALS)", head, re.I | re.S)
    if not m:
        return []
    segment = m.group(1)
    parties: list[dict[str, str]] = []
    for am in re.finditer(rf"{_QUOTE}([A-Z][\w\-& ]{{1,40}}){_QUOTE}", segment):
        alias = am.group(1).strip()
        if alias.lower() in _GENERIC_TERMS or any(p["alias"] == alias for p in parties):
            continue
        before = segment[: am.start()]
        paren = before.rfind("(")
        if paren != -1:
            before = before[:paren]
        cut = max(before.rfind(" and "), before.rfind(" between "), before.rfind(")"))
        name = before[cut + 1:].strip(" ,;:") if cut != -1 else before.strip(" ,;:")
        name = re.sub(r"^(and|between)\s+", "", name, flags=re.I).strip(" ,")
        parties.append({"alias": alias, "name": name[:120] or alias})
        if len(parties) == 4:
            break
    return parties


def ingest(filename: str, data: bytes) -> dict[str, Any]:
    text, page_starts = extract_text(filename, data)
    clauses = segment_clauses(text, page_starts)
    return {
        "text": text,
        "clauses": clauses,
        "defined_terms": defined_terms(text, clauses),
        "parties": detect_parties(text),
        "pages": len(page_starts),
    }
