"""Shared plumbing for the LangGraph workflows: checkpointer, context loading, tracing, SSE."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Iterator

from langgraph.checkpoint.sqlite import SqliteSaver

from .. import db
from ..config import CHECKPOINT_DB, DATABASE_URL
from ..llm import engine
from ..privacy import Redactor, redact_clauses

log = logging.getLogger("lexiscan.graph")

if DATABASE_URL:
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=5, open=True,
                           check=ConnectionPool.check_connection,
                           kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row})
    checkpointer = PostgresSaver(_pool)
else:
    _conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
    checkpointer = SqliteSaver(_conn)
checkpointer.setup()

# One run per thread at a time; a second request for the same thread waits instead of corrupting
# the checkpoint sequence.
_thread_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def thread_lock(thread_id: str) -> threading.Lock:
    with _locks_guard:
        return _thread_locks.setdefault(thread_id, threading.Lock())


def merge_dict(a: dict | None, b: dict | None) -> dict:
    return {**(a or {}), **(b or {})}


def trace(node: str, message: str, engine_label: str | None = None, **extra: Any) -> list[dict]:
    entry = {
        "node": node,
        "message": message,
        "engine": engine_label,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    entry.update(extra)
    return [entry]


class Context:
    """Everything a node needs about the document and the reviewer, rebuilt deterministically.

    The redactor is not stored in graph state (it holds raw PII); rebuilding it from the same
    inputs yields the same tokens, so cached prompts stay byte-identical across nodes.
    """

    def __init__(self, doc_id: str, user_id: str):
        doc = db.get_document(doc_id, user_id)
        if doc is None:
            raise LookupError(f"Document {doc_id} not found")
        self.doc = doc
        self.user = db.ensure_user(user_id)
        self.clauses: list[dict[str, Any]] = doc["clauses"]
        self.redacted, self.redactor = redact_clauses(self.clauses, bool(self.user["privacy_redact"]))
        self.clause_map = {c["id"]: c for c in self.clauses}

    @property
    def document_text(self) -> str:
        return "\n\n".join(f"[{c['id']}] {c['text']}" for c in self.redacted)

    @property
    def reviewer(self) -> str:
        return self.user["name"] or "Reviewer"

    def perspective_brief(self) -> str:
        d, u = self.doc, self.user
        parties = ", ".join(f"{p['alias']} ({p['name']})" for p in d["parties"]) or "not detected"
        lines = [
            f"Parties: {parties}",
            f"Our side (the reviewer represents): {d['perspective'] or 'not specified, stay neutral'}",
            f"Counterparty: {d['counterparty'] or 'the other party'}",
            f"Reviewer: {u['name']}, {u['role']}",
            f"Write for expertise level: {u['expertise']} "
            + ("(plain English, define legal terms)" if u["expertise"] == "plain" else
               "(precise legal language is fine)"),
        ]
        if u["jurisdiction"]:
            lines.append(f"Reviewer's jurisdiction of interest: {u['jurisdiction']}")
        return "\n".join(lines)

    def restore(self, value: Any) -> Any:
        return self.redactor.restore(value)


def memories_block(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return "None yet."
    return "\n".join(f"- ({m['scope']}) {m['content']}" for m in memories)


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(_jsonable(data))}\n\n"


def stream_run(graph, graph_input: Any, config: dict, on_finish=None) -> Iterator[str]:
    """Run a graph and translate LangGraph updates into Server-Sent Events."""
    thread_id = config["configurable"]["thread_id"]
    lock = thread_lock(thread_id)
    if not lock.acquire(timeout=1):
        yield sse("error", {"message": "This run is already in progress. Try again in a moment."})
        return
    try:
        yield sse("start", {"thread_id": thread_id})
        for chunk in graph.stream(graph_input, config, stream_mode="updates"):
            for node, update in chunk.items():
                if node == "__interrupt__":
                    continue
                entries = (update or {}).get("trace", []) if isinstance(update, dict) else []
                yield sse("node", {"node": node, "trace": entries})
        # Read the thread head, not the checkpoint we may have started from (rewinds pin one).
        snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
        payload = snapshot_payload(snapshot)
        if on_finish:
            on_finish(payload)
        yield sse("state", payload)
    except Exception as exc:  # surface failures to the client instead of a dropped stream
        log.exception("Graph run failed")
        yield sse("error", {"message": f"{type(exc).__name__}: {exc}"})
    finally:
        lock.release()


def snapshot_payload(snapshot) -> dict[str, Any]:
    interrupts = []
    for task in snapshot.tasks or ():
        for intr in getattr(task, "interrupts", ()) or ():
            interrupts.append({"id": getattr(intr, "id", None), "value": intr.value})
    return {
        "values": _jsonable(snapshot.values or {}),
        "next": list(snapshot.next or ()),
        "interrupt": interrupts[0] if interrupts else None,
        "checkpoint_id": snapshot.config["configurable"].get("checkpoint_id"),
        "status": "interrupted" if interrupts else ("running" if snapshot.next else "done"),
        "engine": engine.status(),
    }


def redaction_summary(redactor: Redactor) -> dict[str, int]:
    return redactor.report()
