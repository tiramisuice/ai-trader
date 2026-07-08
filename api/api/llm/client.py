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


# ---------------------------------------------------------------------------
# Schema helpers for OpenAI strict mode
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
        """Use Anthropic tool_use to enforce a JSON schema."""
        schema = response_model.model_json_schema()

        tool_name = "structured_output"
        tool_def = {
            "name": tool_name,
            "description": f"Return the result as a {response_model.__name__} JSON object.",
            "input_schema": schema,
        }

        resp = self.anthropic_client.messages.create(
            model=spec.model_id,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            tools=[tool_def],
            tool_choice={"type": "tool", "name": tool_name},
        )
        self._track_anthropic(spec, resp)

        # Extract tool_use block
        for block in resp.content:
            if block.type == "tool_use":
                return response_model.model_validate(block.input)

        raise RuntimeError("No tool_use block returned by Anthropic")

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
        cost_tracker.record(spec.key, input_tokens, output_tokens, cost)
        try:
            from api.db.sqlite import db

            db.save_llm_cost(spec.key, input_tokens, output_tokens, cost)
        except Exception as e:
            logger.warning("Failed to persist LLM cost: %s", e)
        logger.info(
            "LLM call: model=%s in=%d out=%d cost=$%.4f",
            spec.key, input_tokens, output_tokens, cost,
        )
