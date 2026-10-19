"""LLM model registry for the AI trading simulator."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    """Specification for a single LLM model."""

    key: str
    model_id: str
    provider: str  # "anthropic" | "openai"
    input_cost_per_m: float  # USD per 1M input tokens
    output_cost_per_m: float  # USD per 1M output tokens (thinking/reasoning tokens bill as output)
    # Anthropic `effort` (thinking depth). None = provider default.
    # OpenAI models run at their default reasoning effort (medium for gpt-6.1-sol).
    effort: str | None = None


MODEL_REGISTRY: dict[str, ModelSpec] = {
    # IDs and pricing verified against the official model docs on 2026-10-19.
    # All three run at "medium" thinking/reasoning effort so agents are compared
    # on equal footing (Sonnet 5.5 would default to "high").
    "claude-opus": ModelSpec(
        key="claude-opus",
        model_id="claude-opus-5-5",
        provider="anthropic",
        input_cost_per_m=4.0,
        output_cost_per_m=20.0,
        effort="medium",
    ),
    "claude-sonnet": ModelSpec(
        key="claude-sonnet",
        model_id="claude-sonnet-5-5",
        provider="anthropic",
        input_cost_per_m=2.0,
        output_cost_per_m=10.0,
        effort="medium",
    ),
    "gpt-6.1-sol": ModelSpec(
        key="gpt-6.1-sol",
        model_id="gpt-6.1-sol",
        provider="openai",
        input_cost_per_m=2.0,
        output_cost_per_m=10.0,
    ),
}


def get_model(key: str) -> ModelSpec:
    """Get a model spec by its registry key."""
    if key not in MODEL_REGISTRY:
        raise ValueError(f"Unknown model key: {key!r}. Available: {list(MODEL_REGISTRY)}")
    return MODEL_REGISTRY[key]
