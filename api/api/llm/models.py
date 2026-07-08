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
    output_cost_per_m: float  # USD per 1M output tokens


MODEL_REGISTRY: dict[str, ModelSpec] = {
    "claude-opus": ModelSpec(
        key="claude-opus",
        model_id="claude-opus-4-6",
        provider="anthropic",
        input_cost_per_m=5.0,
        output_cost_per_m=25.0,
    ),
    "claude-sonnet": ModelSpec(
        key="claude-sonnet",
        model_id="claude-sonnet-4-6",
        provider="anthropic",
        input_cost_per_m=3.0,
        output_cost_per_m=15.0,
    ),
    "claude-haiku": ModelSpec(
        key="claude-haiku",
        model_id="claude-haiku-4-5",
        provider="anthropic",
        input_cost_per_m=1.0,
        output_cost_per_m=5.0,
    ),
    "gpt-5.4": ModelSpec(
        key="gpt-5.4",
        model_id="gpt-5.4",
        provider="openai",
        input_cost_per_m=2.50,
        output_cost_per_m=10.0,
    ),
    "gpt-5.4-mini": ModelSpec(
        key="gpt-5.4-mini",
        model_id="gpt-5.4-mini",
        provider="openai",
        input_cost_per_m=0.15,
        output_cost_per_m=0.60,
    ),
}


def get_model(key: str) -> ModelSpec:
    """Get a model spec by its registry key."""
    if key not in MODEL_REGISTRY:
        raise ValueError(f"Unknown model key: {key!r}. Available: {list(MODEL_REGISTRY)}")
    return MODEL_REGISTRY[key]
