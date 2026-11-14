"""Thin Claude client used by every LangGraph node.

Design choices:
- Structured outputs (`output_config.format`) so nodes receive validated Pydantic objects.
- The contract is sent as the first user block with `cache_control`, so every node that works on
  the same document (analysis, playbook, obligations, Q&A drafts, revisions) reuses the cache.
- Server-side refusal fallbacks are enabled.
- Every call takes an offline `fallback`. If no credentials are configured, or a call fails, the
  node degrades to deterministic heuristics instead of crashing the graph, and the result is
  labelled with the engine that produced it so the reviewer always knows.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Callable, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from .config import EFFORT, FORCE_OFFLINE, MODEL
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


class LLMUnavailable(RuntimeError):
    pass


class Engine:
    def __init__(self) -> None:
        self.disabled_reason: str | None = None
        self.client: anthropic.Anthropic | None = None
        self.key_source: str | None = None
        if FORCE_OFFLINE:
            self.disabled_reason = "Offline mode forced by LEXISCAN_OFFLINE"
            return
        name, key = self._find_api_key()
        if key:
            self.key_source = name
            self.client = anthropic.Anthropic(api_key=key, max_retries=3)
            log.info("Claude enabled with the key from %s", name)
        elif os.getenv("ANTHROPIC_AUTH_TOKEN") or (Path.home() / ".config" / "anthropic").exists():
            self.client = anthropic.Anthropic(max_retries=3)
        else:
            self.disabled_reason = self._missing_key_reason()
            log.warning(self.disabled_reason)

    @staticmethod
    def _clean(value: str | None) -> str:
        # Dashboards often keep pasted quotes, spaces or newlines around the value.
        return (value or "").strip().strip("'\"").strip()

    @classmethod
    def _find_api_key(cls) -> tuple[str | None, str | None]:
        """ANTHROPIC_API_KEY first; otherwise any variable whose value is an Anthropic key (sk-ant-...)."""
        preferred = cls._clean(os.getenv("ANTHROPIC_API_KEY"))
        if preferred:
            return "ANTHROPIC_API_KEY", preferred
        for name, value in sorted(os.environ.items()):
            value = cls._clean(value)
            if value.startswith("sk-ant-"):
                return name, value
        return None, None

    @staticmethod
    def _missing_key_reason() -> str:
        # Report variable names and providers only, never values.
        providers = {"sk-proj-": "OpenAI", "gsk_": "Groq", "AIza": "Google Gemini", "hf_": "Hugging Face",
                     "sk-or-": "OpenRouter", "pplx-": "Perplexity", "xai-": "xAI", "sk-": "OpenAI-style"}
        found = []
        for name, value in sorted(os.environ.items()):
            if not any(t in name.upper() for t in ("KEY", "TOKEN", "SECRET")):
                continue
            value = value.strip().strip("'\"")
            provider = next((p for prefix, p in providers.items() if value.startswith(prefix)), None)
            if provider:
                found.append(f"{name} ({provider} key)")
        if found:
            return ("No Anthropic API key found. The server has " + ", ".join(found) +
                    ", but LexiScan runs on Claude and needs an Anthropic key (it starts with sk-ant-). "
                    "Add it as ANTHROPIC_API_KEY on the server.")
        return "No Anthropic API key found on the server. Add ANTHROPIC_API_KEY (it starts with sk-ant-)."

    @property
    def online(self) -> bool:
        return self.client is not None and self.disabled_reason is None

    @property
    def label(self) -> str:
        return MODEL if self.online else "offline-heuristics"

    def status(self) -> dict:
        return {"online": self.online, "model": MODEL if self.online else None,
                "engine": self.label, "reason": self.disabled_reason}

    def _call(self, task: str, document: str, schema: type[T], effort: str | None) -> T:
        assert self.client is not None
        content = []
        if document:
            content.append({
                "type": "text",
                "text": f"<contract>\n{document}\n</contract>",
                "cache_control": {"type": "ephemeral"},
            })
        content.append({"type": "text", "text": task})
        with self.client.beta.messages.stream(
            model=MODEL,
            max_tokens=32000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={
                "effort": effort or EFFORT,
                "format": {"type": "json_schema", "schema": strict_json_schema(schema)},
            },
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        ) as stream:
            message = stream.get_final_message()

        if message.stop_reason == "refusal":
            raise LLMUnavailable("The model declined this request")
        if message.stop_reason == "max_tokens":
            raise LLMUnavailable("The model response was cut off (max_tokens)")
        text = "".join(b.text for b in message.content if b.type == "text")
        return schema.model_validate(json.loads(text))

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
        except anthropic.AuthenticationError:
            self.disabled_reason = "Anthropic credentials were rejected; running offline"
            log.error(self.disabled_reason)
        except anthropic.PermissionDeniedError as exc:
            log.error("Permission denied by API: %s", exc.message)
        except anthropic.RateLimitError:
            log.warning("Rate limited; using offline fallback for this step")
        except anthropic.APIStatusError as exc:
            log.warning("API error %s (request %s): %s", exc.status_code,
                        exc.response.headers.get("request-id"), exc.message)
        except anthropic.APIConnectionError:
            log.warning("Could not reach the Anthropic API; using offline fallback")
        except (LLMUnavailable, ValidationError, json.JSONDecodeError) as exc:
            log.warning("Unusable model output (%s); using offline fallback", exc)
        return fallback(), "offline-fallback"


engine = Engine()
