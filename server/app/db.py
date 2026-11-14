"""Persistence for application data: SQLite locally, Postgres when DATABASE_URL is set.

Hosts with an ephemeral disk (Render's free tier) lose SQLite files on every deploy or restart,
so production should point DATABASE_URL at a hosted Postgres. The SQL is written once in SQLite
style; `_PgConnection` translates the few differences.

LangGraph checkpoints live alongside (see graphs/common.py). This store holds the things a human
reviewer owns: profiles, documents, findings and their review decisions, obligations, playbook
rules, learned preferences and the audit trail.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable

from .config import APP_DB, DATABASE_URL

if DATABASE_URL:
    from psycopg_pool import ConnectionPool

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT 'Reviewer',
    role TEXT NOT NULL DEFAULT 'Legal reviewer',
    expertise TEXT NOT NULL DEFAULT 'professional',
    jurisdiction TEXT NOT NULL DEFAULT '',
    review_policy TEXT NOT NULL DEFAULT 'always',
    confidence_threshold REAL NOT NULL DEFAULT 0.8,
    privacy_redact INTEGER NOT NULL DEFAULT 1,
    ask_clarifications INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    text TEXT NOT NULL,
    clauses_json TEXT NOT NULL,
    defined_terms_json TEXT NOT NULL DEFAULT '{}',
    parties_json TEXT NOT NULL DEFAULT '[]',
    perspective TEXT NOT NULL DEFAULT '',
    counterparty TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'uploaded',
    risk_score INTEGER,
    risk_level TEXT,
    review_thread_id TEXT,
    memo TEXT,
    memo_status TEXT,
    summary TEXT,
    playbook_json TEXT NOT NULL DEFAULT '[]',
    redactions_json TEXT NOT NULL DEFAULT '{}',
    engines_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    clause_id TEXT,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    risk TEXT NOT NULL,
    rationale TEXT NOT NULL,
    suggestion TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    rule_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    reviewer_note TEXT NOT NULL DEFAULT '',
    final_suggestion TEXT,
    decided_by TEXT,
    decided_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS obligations (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    party TEXT NOT NULL,
    action TEXT NOT NULL,
    due TEXT NOT NULL DEFAULT '',
    due_date TEXT,
    recurring TEXT NOT NULL DEFAULT '',
    clause_id TEXT,
    done INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS playbook_rules (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    clause_type TEXT NOT NULL,
    title TEXT NOT NULL,
    requirement TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'medium',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    scope TEXT NOT NULL,
    content TEXT NOT NULL,
    source_ref TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    uses INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    doc_id TEXT,
    thread_id TEXT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    question TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    answer TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_findings_doc ON findings(doc_id);
CREATE INDEX IF NOT EXISTS idx_obligations_doc ON obligations(doc_id);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_threads_doc ON threads(doc_id);
"""

DEFAULT_PLAYBOOK = [
    ("liability", "Liability is capped",
     "Our liability must be capped (typically at 12 months of fees). No uncapped liability for us.",
     "high"),
    ("indemnification", "Indemnities are balanced",
     "Indemnities must be mutual, or limited to third-party claims caused by the indemnifying party.",
     "high"),
    ("termination", "We can exit",
     "We must be able to terminate for convenience on no more than 30 days' notice.", "medium"),
    ("renewal", "No silent auto-renewal",
     "Automatic renewal is acceptable only with at least 30 days' notice to opt out.", "medium"),
    ("confidentiality", "Confidentiality is time-limited",
     "Confidentiality obligations should end within 5 years, except for trade secrets.", "medium"),
    ("data_protection", "Personal data is protected",
     "If personal data is processed, the contract must include security and data protection duties.",
     "medium"),
    ("payment", "Fair payment terms",
     "Payment terms of at least Net 30, and late fees no higher than 1.5% per month.", "low"),
    ("governing_law", "Acceptable governing law",
     "Governing law and venue should be our home jurisdiction or a neutral one.", "low"),
]


def now() -> str:
    # Microseconds keep rows created in the same second (seeded rules, audit bursts) in order.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Row(dict):
    """Postgres row that, like sqlite3.Row, can be read by column name or by position."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def _row_factory(cursor):
    names = [c.name for c in cursor.description or []]
    return lambda values: Row(zip(names, values))


class _PgConnection:
    """Accepts SQLite-style SQL (`?` placeholders, INSERT OR IGNORE) and runs it on Postgres."""

    def __init__(self, conn):
        self._conn = conn

    @staticmethod
    def _sql(sql: str) -> str:
        sql = sql.replace("%", "%%").replace("?", "%s")
        if "INSERT OR IGNORE INTO" in sql:
            sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO") + " ON CONFLICT DO NOTHING"
        return sql

    @staticmethod
    def _params(params) -> tuple:
        # SQLite stores booleans as integers; the schema keeps INTEGER columns for them.
        return tuple(int(p) if isinstance(p, bool) else p for p in params)

    def execute(self, sql: str, params=()):
        cur = self._conn.cursor(row_factory=_row_factory)
        cur.execute(self._sql(sql), self._params(params))
        return cur

    def executemany(self, sql: str, seq):
        cur = self._conn.cursor()
        cur.executemany(self._sql(sql), [self._params(p) for p in seq])
        return cur


_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        # prepare_threshold=None keeps it compatible with PgBouncer-style poolers (Supabase, Neon).
        _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=5, open=True,
                               kwargs={"prepare_threshold": None}, check=ConnectionPool.check_connection)
    return _pool


@contextmanager
def connect():
    if DATABASE_URL:
        with _get_pool().connection() as conn:  # commits on success, rolls back on error
            yield _PgConnection(conn)
        return
    conn = sqlite3.connect(APP_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        if DATABASE_URL:
            for statement in filter(str.strip, SCHEMA.split(";")):
                conn.execute(statement)
        else:
            conn.executescript(SCHEMA)


def backend() -> str:
    return "postgres" if DATABASE_URL else "sqlite"


def row(r) -> dict[str, Any] | None:
    return dict(r) if r is not None else None


def rows(rs: Iterable) -> list[dict[str, Any]]:
    return [dict(r) for r in rs]


# ── users ────────────────────────────────────────────────────────────────────

def ensure_user(user_id: str) -> dict[str, Any]:
    with connect() as conn:
        existing = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if existing:
            return dict(existing)
        created = conn.execute("INSERT OR IGNORE INTO users (id, created_at) VALUES (?, ?)",
                               (user_id, now())).rowcount
        for clause_type, title, requirement, severity in (DEFAULT_PLAYBOOK if created else []):
            conn.execute(
                "INSERT INTO playbook_rules (id, user_id, clause_type, title, requirement, severity,"
                " created_at) VALUES (?,?,?,?,?,?,?)",
                (new_id("rule"), user_id, clause_type, title, requirement, severity, now()),
            )
        return dict(conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())


USER_FIELDS = {
    "name", "role", "expertise", "jurisdiction", "review_policy", "confidence_threshold",
    "privacy_redact", "ask_clarifications",
}


def update_user(user_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    fields = {k: v for k, v in fields.items() if k in USER_FIELDS}
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        with connect() as conn:
            conn.execute(f"UPDATE users SET {sets} WHERE id=?", (*fields.values(), user_id))
    return ensure_user(user_id)


# ── documents ────────────────────────────────────────────────────────────────

def get_document(doc_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    with connect() as conn:
        if user_id:
            r = conn.execute(
                "SELECT * FROM documents WHERE id=? AND user_id=?", (doc_id, user_id)
            ).fetchone()
        else:
            r = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    d = row(r)
    if d:
        d["clauses"] = json.loads(d.pop("clauses_json"))
        d["defined_terms"] = json.loads(d.pop("defined_terms_json"))
        d["parties"] = json.loads(d.pop("parties_json"))
        d["playbook"] = json.loads(d.pop("playbook_json"))
        d["redactions"] = json.loads(d.pop("redactions_json"))
        d["engines"] = json.loads(d.pop("engines_json"))
    return d


def update_document(doc_id: str, **fields: Any) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE documents SET {sets} WHERE id=?", (*fields.values(), doc_id))


# ── audit ────────────────────────────────────────────────────────────────────

def audit(
    user_id: str,
    actor: str,
    action: str,
    detail: dict[str, Any] | None = None,
    doc_id: str | None = None,
    thread_id: str | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO audit (id, user_id, doc_id, thread_id, actor, action, detail_json,"
            " created_at) VALUES (?,?,?,?,?,?,?,?)",
            (new_id("aud"), user_id, doc_id, thread_id, actor, action,
             json.dumps(detail or {}), now()),
        )


# ── memories (learned reviewer preferences) ─────────────────────────────────

def add_memory(user_id: str, kind: str, scope: str, content: str, source_ref: str = "") -> str:
    mid = new_id("mem")
    with connect() as conn:
        conn.execute(
            "INSERT INTO memories (id, user_id, kind, scope, content, source_ref, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (mid, user_id, kind, scope, content, source_ref, now()),
        )
    return mid


def active_memories(user_id: str, scopes: Iterable[str] | None = None) -> list[dict[str, Any]]:
    with connect() as conn:
        rs = rows(conn.execute(
            "SELECT * FROM memories WHERE user_id=? AND active=1 ORDER BY created_at DESC",
            (user_id,),
        ))
    if scopes is not None:
        wanted = set(scopes) | {"general"}
        rs = [m for m in rs if m["scope"] in wanted]
    return rs[:40]


def mark_memories_used(ids: list[str]) -> None:
    if not ids:
        return
    with connect() as conn:
        conn.executemany("UPDATE memories SET uses = uses + 1 WHERE id=?", [(i,) for i in ids])
