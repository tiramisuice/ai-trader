"""LLM client with support for Anthropic and OpenAI, plus cost tracking."""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
from typing import Any

import anthropic
import openai
from pydantic import BaseModel

from api.llm.models import ModelSpec, get_model

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cost Tracker
# ---------------------------------------------------------------------------

class CostTracker:
    """Thread-safe tracker for LLM token usage and cost."""

    # The process runs for weeks — keep only recent records in memory while
    # totals accumulate separately so they stay accurate.
    MAX_RECORDS = 1000

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[dict[str, Any]] = []
        self._total_cost = 0.0
        self._total_tokens = 0

    def record(
        self,
        model_key: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        with self._lock:
            self._records.append(
                {
                    "timestamp": time.time(),
                    "model": model_key,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": cost_usd,
                }
            )
            if len(self._records) > self.MAX_RECORDS:
                del self._records[: -self.MAX_RECORDS]
            self._total_cost += cost_usd
            self._total_tokens += input_tokens + output_tokens

    @property
    def total_cost(self) -> float:
        with self._lock:
            return self._total_cost

    @property
    def total_tokens(self) -> int:
        with self._lock:
            return self._total_tokens

    @property
    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._records)


# Singleton cost tracker
cost_tracker = CostTracker()


def _persist_cost(model_key: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
    """Write one cost record to the DB (llm_costs). Never raises."""
    try:
        from api.db.sqlite import db

        db.save_llm_cost(model_key, input_tokens, output_tokens, cost_usd)
    except Exception as e:
        logger.warning("Failed to persist LLM cost: %s", e)


# ---------------------------------------------------------------------------
# Schema helpers for strict structured outputs (OpenAI + Anthropic)
# ---------------------------------------------------------------------------

def _make_all_required(schema: dict) -> dict:
    """Recursively make all properties required and add
    additionalProperties: false (OpenAI strict structured output).

    Deep-copies the input so the caller's schema is never mutated."""
    schema = copy.deepcopy(schema)

    if schema.get("type") == "object" and "properties" in schema:
        schema["required"] = list(schema["properties"].keys())
        schema["additionalProperties"] = False
        for prop_name, prop_schema in schema["properties"].items():
            schema["properties"][prop_name] = _make_all_required(prop_schema)

    # Handle nested arrays
    if schema.get("type") == "array" and "items" in schema:
        schema["items"] = _make_all_required(schema["items"])

    # Handle anyOf / oneOf
    for combo_key in ("anyOf", "oneOf"):
        if combo_key in schema:
            schema[combo_key] = [_make_all_required(s) for s in schema[combo_key]]

    # Handle $defs
    if "$defs" in schema:
        schema["$defs"] = {
            k: _make_all_required(v) for k, v in schema["$defs"].items()
        }

    return schema


# JSON Schema keywords Anthropic structured outputs reject (400). Numeric bounds
# are kept as human-readable descriptions so the model still sees them.
_ANTHROPIC_BOUND_KEYWORDS = {
    "minimum": ">=", "maximum": "<=", "exclusiveMinimum": ">", "exclusiveMaximum": "<",
}
_ANTHROPIC_DROPPED_KEYWORDS = ("multipleOf", "minLength", "maxLength", "maxItems")


def _strip_unsupported_keywords(node: Any) -> None:
    if isinstance(node, list):
        for item in node:
            _strip_unsupported_keywords(item)
        return
    if not isinstance(node, dict):
        return

    bounds = [f"{sym} {node.pop(kw)}" for kw, sym in _ANTHROPIC_BOUND_KEYWORDS.items() if kw in node]
    for kw in _ANTHROPIC_DROPPED_KEYWORDS:
        node.pop(kw, None)
    if node.get("minItems", 0) > 1:
        node.pop("minItems")
    if bounds:
        note = "Must be " + " and ".join(bounds) + "."
        node["description"] = f"{node['description']} {note}" if node.get("description") else note

    for key, value in node.items():
        if key in ("properties", "$defs", "definitions") and isinstance(value, dict):
            for sub_schema in value.values():  # keys here are names, not keywords
                _strip_unsupported_keywords(sub_schema)
        else:
            _strip_unsupported_keywords(value)


def _strict_schema_anthropic(schema: dict) -> dict:
    """Adapt a Pydantic JSON schema to Anthropic structured outputs: every
    property required, `additionalProperties: false`, and no numeric/string
    constraint keywords. Returns a new schema; the input is not mutated."""
    strict = _make_all_required(schema)
    _strip_unsupported_keywords(strict)
    return strict


# ---------------------------------------------------------------------------
# LLM Client
# ---------------------------------------------------------------------------

class LLMClient:
    """Unified LLM client for Anthropic and OpenAI."""

    def __init__(self) -> None:
        self._anthropic: anthropic.Anthropic | None = None
        self._openai: openai.OpenAI | None = None

    @property
    def anthropic_client(self) -> anthropic.Anthropic:
        if self._anthropic is None:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise RuntimeError("ANTHROPIC_API_KEY not set")
            self._anthropic = anthropic.Anthropic(api_key=api_key)
        return self._anthropic

    @property
    def openai_client(self) -> openai.OpenAI:
        if self._openai is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY not set")
            self._openai = openai.OpenAI(api_key=api_key)
        return self._openai

    # ------- research phase (server-side web search) -------

    # $10 per 1,000 searches on the Claude API (docs, verified 2026-10-19)
    WEB_SEARCH_COST_PER_QUERY = 0.01

    def research(
        self,
        model_key: str,
        system: str,
        prompt: str,
        max_searches: int = 3,
        max_tokens: int = 16000,
    ) -> str:
        """Let the model research with live web search before deciding.

        Runs as a separate free-form phase so the decision call stays a single
        schema-constrained JSON response. `max_tokens` covers thinking + text.
        Only Anthropic models support this; others return "" (no research).
        Returns the model's research notes as text.
        """
        spec = get_model(model_key)
        if spec.provider != "anthropic":
            return ""

        tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": max_searches}]
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

        # Continue the turn when the API pauses a long search, or when the model
        # asks for a client tool we don't offer (bounded to avoid loops).
        notes: list[str] = []
        for _ in range(3):
            resp = self.anthropic_client.messages.create(
                model=spec.model_id,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                tools=tools,
                **self._anthropic_effort(spec),
            )
            self._track(spec, resp.usage.input_tokens, resp.usage.output_tokens)
            searches = getattr(resp.usage, "server_tool_use", None)
            n_searches = getattr(searches, "web_search_requests", 0) if searches else 0
            if n_searches:
                self._record_cost("web_search", 0, 0, n_searches * self.WEB_SEARCH_COST_PER_QUERY)
            # Citations split the answer into many text blocks — join them seamlessly
            notes.append("".join(b.text for b in resp.content if getattr(b, "type", "") == "text"))

            if resp.stop_reason == "pause_turn":
                messages = messages + [{"role": "assistant", "content": resp.content}]
                continue
            declined = [
                {
                    "type": "tool_result",
                    "tool_use_id": b.id,
                    "is_error": True,
                    "content": "This tool is not available. Finish your research notes with what you have.",
                }
                for b in resp.content
                if getattr(b, "type", "") == "tool_use"
            ]
            if resp.stop_reason == "tool_use" and declined:
                # Seen on Sonnet 5.5: without this the notes stop mid-way
                messages = messages + [
                    {"role": "assistant", "content": resp.content},
                    {"role": "user", "content": declined},
                ]
                continue
            break

        return "\n".join(n for n in notes if n).strip()

    # ------- structured JSON completion -------

    def complete_json(
        self,
        model_key: str,
        system: str,
        prompt: str,
        response_model: type[BaseModel],
        max_tokens: int = 4096,
    ) -> BaseModel:
        """Return a validated Pydantic model from the LLM response."""
        spec = get_model(model_key)

        if spec.provider == "anthropic":
            return self._complete_json_anthropic(spec, system, prompt, response_model, max_tokens)
        else:
            return self._complete_json_openai(spec, system, prompt, response_model, max_tokens)

    # ===================================================================
    # Anthropic implementations
    # ===================================================================

    def _complete_json_anthropic(
        self,
        spec: ModelSpec,
        system: str,
        prompt: str,
        response_model: type[BaseModel],
        max_tokens: int,
    ) -> BaseModel:
        """Use Anthropic structured outputs (grammar-constrained JSON).

        Replaces the old forced-tool_choice approach: Claude Opus 5.5 / Sonnet 5.5
        reject forced tool use, and unconstrained tool input let models return the
        wrong shape (e.g. a bare TradeOrder), which failed validation and burned
        a full research + decide cycle on every retry."""
        schema = _strict_schema_anthropic(response_model.model_json_schema())
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
        output_config.update(self._anthropic_effort(spec).get("output_config", {}))

        resp = self.anthropic_client.messages.create(
            model=spec.model_id,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config=output_config,
        )
        self._track_anthropic(spec, resp)

        if resp.stop_reason != "end_turn":
            raise RuntimeError(
                f"Anthropic {spec.model_id} stopped with {resp.stop_reason!r} "
                f"before finishing the {response_model.__name__}"
            )
        # Thinking blocks come first; the JSON is in the text block(s)
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return response_model.model_validate_json(text)

    @staticmethod
    def _anthropic_effort(spec: ModelSpec) -> dict[str, Any]:
        return {"output_config": {"effort": spec.effort}} if spec.effort else {}

    def _track_anthropic(self, spec: ModelSpec, resp: Any) -> None:
        usage = resp.usage
        self._track(spec, usage.input_tokens, usage.output_tokens)

    # ===================================================================
    # OpenAI implementations
    # ===================================================================

    def _complete_json_openai(
        self,
        spec: ModelSpec,
        system: str,
        prompt: str,
        response_model: type[BaseModel],
        max_tokens: int,
    ) -> BaseModel:
        """Use OpenAI structured outputs (strict mode) to enforce JSON schema."""
        raw_schema = response_model.model_json_schema()
        strict_schema = _make_all_required(raw_schema)

        # Remove title at top level to satisfy OpenAI
        strict_schema.pop("title", None)

        resp = self.openai_client.chat.completions.create(
            model=spec.model_id,
            max_completion_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "strict": True,
                    "schema": strict_schema,
                },
            },
        )
        self._track_openai(spec, resp)

        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        return response_model.model_validate(data)

    def _track_openai(self, spec: ModelSpec, resp: Any) -> None:
        usage = resp.usage
        if usage is None:
            return
        self._track(spec, usage.prompt_tokens or 0, usage.completion_tokens or 0)

    def _track(self, spec: ModelSpec, input_tokens: int, output_tokens: int) -> None:
        cost = (
            input_tokens * spec.input_cost_per_m / 1_000_000
            + output_tokens * spec.output_cost_per_m / 1_000_000
        )
        self._record_cost(spec.key, input_tokens, output_tokens, cost)

    @staticmethod
    def _record_cost(key: str, input_tokens: int, output_tokens: int, cost: float) -> None:
        """Record a cost in memory and in the DB. `key` is a model key, or
        "web_search" for per-search fees ($10 / 1,000 searches)."""
        cost_tracker.record(key, input_tokens, output_tokens, cost)
        _persist_cost(key, input_tokens, output_tokens, cost)
        logger.info(
            "LLM cost: %s in=%d out=%d cost=$%.4f", key, input_tokens, output_tokens, cost,
        )
