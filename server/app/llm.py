"""Thin Groq client used by every LangGraph node.

Design choices:
- Structured outputs: on models that support strict JSON schema (the gpt-oss family) the response is
  constrained to the Pydantic schema; other models use JSON mode with the schema in the prompt. Every
  response is validated with Pydantic before a node sees it.
- Groq's free tier has low tokens-per-minute limits, so calls run one at a time and rate-limit
  responses are retried with back-off by the SDK.
- Every call takes an offline `fallback`. If no key is configured, or a call fails, the node degrades
  to deterministic heuristics instead of crashing the graph, and the result is labelled with the engine
  that produced it so the reviewer always knows.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Callable, TypeVar

import groq
from pydantic import BaseModel, ValidationError

from .config import EFFORT, FORCE_OFFLINE, LLM_CONCURRENCY, MODEL
from .schemas import strict_json_schema

log = logging.getLogger("lexiscan.llm")
T = TypeVar("T", bound=BaseModel)

SYSTEM_PROMPT = """You are LexiScan, a meticulous contract analyst assisting a human legal reviewer.
The reviewer makes every final decision; your job is to give them accurate, checkable drafts.

Ground rules:
- Use only the contract provided. If the contract does not address something, say so plainly.
- Quotes must be copied verbatim from the contract text, character for character.
- Analyse from the reviewer's side of the deal (named in each task).
- Be concrete and brief. Prefer one precise sentence over three vague ones.
- Placeholders like [EMAIL_1] are redacted personal data. Keep them exactly as written.
- You are not giving legal advice to a layperson; flag where a qualified lawyer must decide."""

STRICT_SCHEMA_MODELS = ("openai/gpt-oss",)
REASONING_MODELS = ("openai/gpt-oss",)


class LLMUnavailable(RuntimeError):
    pass


class Engine:
    def __init__(self) -> None:
        self.disabled_reason: str | None = None
        self.client: groq.Groq | None = None
        self.key_source: str | None = None
        self._slots = threading.BoundedSemaphore(max(1, LLM_CONCURRENCY))
        self._strict = MODEL.startswith(STRICT_SCHEMA_MODELS)
        if FORCE_OFFLINE:
            self.disabled_reason = "Offline mode forced by LEXISCAN_OFFLINE"
            return
        name, key = self._find_api_key()
        if not key:
            self.disabled_reason = ("No Groq API key found on the server. Add GROQ_API_KEY "
                                    "(free at console.groq.com; it starts with gsk_).")
            log.warning(self.disabled_reason)
            return
        self.key_source = name
        self.client = groq.Groq(api_key=key, max_retries=5, timeout=120)
        log.info("Groq enabled (%s) with the key from %s", MODEL, name)

    @staticmethod
    def _clean(value: str | None) -> str:
        # Dashboards often keep pasted quotes, spaces or newlines around the value.
        return (value or "").strip().strip("'\"").strip()

    @classmethod
    def _find_api_key(cls) -> tuple[str | None, str | None]:
        """GROQ_API_KEY first; otherwise any variable whose value is a Groq key (gsk_...)."""
        preferred = cls._clean(os.getenv("GROQ_API_KEY"))
        if preferred:
            return "GROQ_API_KEY", preferred
        for name, value in sorted(os.environ.items()):
            if cls._clean(value).startswith("gsk_"):
                return name, cls._clean(value)
        return None, None

    @property
    def online(self) -> bool:
        return self.client is not None and self.disabled_reason is None

    @property
    def label(self) -> str:
        return MODEL if self.online else "offline-heuristics"

    def status(self) -> dict:
        return {"online": self.online, "model": MODEL if self.online else None,
                "engine": self.label, "reason": self.disabled_reason}

    def _request(self, messages: list[dict], schema: type[T], effort: str | None, strict: bool):
        assert self.client is not None
        if strict:
            response_format = {"type": "json_schema", "json_schema": {
                "name": schema.__name__, "strict": True, "schema": strict_json_schema(schema)}}
        else:
            response_format = {"type": "json_object"}
        extra = {}
        if MODEL.startswith(REASONING_MODELS):
            extra = {"reasoning_effort": effort or EFFORT, "include_reasoning": False}
        with self._slots:
            return self.client.chat.completions.create(
                model=MODEL,
                messages=messages,
                response_format=response_format,
                temperature=0.2,
                max_completion_tokens=8192,
                **extra,
            )

    def _call(self, task: str, document: str, schema: type[T], effort: str | None) -> T:
        user = (f"<contract>\n{document}\n</contract>\n\n" if document else "") + task
        system = SYSTEM_PROMPT
        if not self._strict:
            system += ("\n\nRespond with a single JSON object only, matching this JSON schema exactly:\n"
                       + json.dumps(strict_json_schema(schema)))
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            completion = self._request(messages, schema, effort, self._strict)
        except groq.BadRequestError as exc:
            if not self._strict:
                raise
            # Strict schema rejected or output failed validation: retry once in JSON mode.
            log.warning("Strict structured output failed (%s); retrying in JSON mode", exc.message)
            messages[0]["content"] += ("\n\nRespond with a single JSON object only, matching this JSON "
                                       "schema exactly:\n" + json.dumps(strict_json_schema(schema)))
            completion = self._request(messages, schema, effort, strict=False)
        choice = completion.choices[0]
        if choice.finish_reason == "length":
            raise LLMUnavailable("The model response was cut off (max tokens)")
        return schema.model_validate(json.loads(choice.message.content or ""))

    def structured(
        self,
        task: str,
        schema: type[T],
        fallback: Callable[[], T],
        document: str = "",
        effort: str | None = None,
    ) -> tuple[T, str]:
        """Run a structured call. Returns (result, engine_label)."""
        if not self.online:
            return fallback(), "offline-heuristics"
        try:
            return self._call(task, document, schema, effort), MODEL
        except groq.AuthenticationError:
            self.disabled_reason = "The Groq API key was rejected; running offline. Check GROQ_API_KEY."
            log.error(self.disabled_reason)
        except groq.PermissionDeniedError as exc:
            log.error("Permission denied by Groq: %s", exc.message)
        except groq.RateLimitError:
            log.warning("Groq rate limit reached; using offline fallback for this step")
        except groq.APIStatusError as exc:
            log.warning("Groq API error %s: %s", exc.status_code, exc.message)
        except groq.APIConnectionError:
            log.warning("Could not reach the Groq API; using offline fallback")
        except (LLMUnavailable, ValidationError, json.JSONDecodeError) as exc:
            log.warning("Unusable model output (%s); using offline fallback", exc)
        return fallback(), "offline-fallback"


engine = Engine()
