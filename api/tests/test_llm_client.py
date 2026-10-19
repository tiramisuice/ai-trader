"""Tests for the LLM client: Anthropic structured outputs, strict schemas,
model registry, and cost tracking (incl. web search fees).

All provider calls are mocked — nothing here hits a real API."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api.llm import client as client_mod
from api.llm.client import LLMClient, _strict_schema_anthropic
from api.llm.models import MODEL_REGISTRY, get_model
from api.trading.models import TradeDecision

VALID_DECISION_JSON = (
    '{"market_analysis": "calm", "orders": [], "reasoning": "wait", '
    '"conditional_orders": [], "wake_triggers": [], "next_check_hours": 24, '
    '"journal": "patience", "watchlist_add": [], "watchlist_remove": []}'
)


def _walk(node):
    """Yield every dict in a JSON schema tree."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


# --- Strict schema for Anthropic structured outputs ---

def test_decision_schema_hides_system_fields_from_llm():
    props = TradeDecision.model_json_schema()["properties"]
    assert "strategy" not in props
    assert "timestamp" not in props


def test_strict_schema_meets_anthropic_limits():
    schema = _strict_schema_anthropic(TradeDecision.model_json_schema())
    unsupported = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
                   "multipleOf", "minLength", "maxLength"}
    for node in _walk(schema):
        if node.get("type") == "object" and "properties" in node:
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
        assert not unsupported & set(node), f"unsupported keyword left in {node}"


def test_strict_schema_keeps_constraints_as_descriptions():
    schema = _strict_schema_anthropic(TradeDecision.model_json_schema())
    hours = schema["properties"]["next_check_hours"]
    assert ">= 0.25" in hours["description"] and "<= 48" in hours["description"]


def test_strict_schema_does_not_mutate_input():
    raw = TradeDecision.model_json_schema()
    _strict_schema_anthropic(raw)
    assert "maximum" in raw["properties"]["next_check_hours"]


# --- Decision model robustness ---

def test_out_of_range_sleep_is_clamped_not_rejected():
    d = TradeDecision.model_validate_json(VALID_DECISION_JSON.replace('"next_check_hours": 24', '"next_check_hours": 72'))
    assert d.next_check_hours == 48
    d = TradeDecision.model_validate_json(VALID_DECISION_JSON.replace('"next_check_hours": 24', '"next_check_hours": 0.1'))
    assert d.next_check_hours == 0.25


# --- Anthropic request/response handling ---

def _anthropic_resp(content, stop_reason="end_turn", in_tok=1000, out_tok=200, searches=0):
    usage = SimpleNamespace(
        input_tokens=in_tok, output_tokens=out_tok,
        server_tool_use=SimpleNamespace(web_search_requests=searches) if searches else None,
    )
    return SimpleNamespace(content=content, stop_reason=stop_reason, usage=usage)


@pytest.fixture
def llm(monkeypatch):
    saved = []
    monkeypatch.setattr(client_mod, "_persist_cost", lambda *a: saved.append(a))
    c = LLMClient()
    c._anthropic = MagicMock()
    c._openai = MagicMock()
    c.saved_costs = saved
    return c


def test_anthropic_decision_uses_structured_outputs_not_forced_tools(llm):
    llm._anthropic.messages.create.return_value = _anthropic_resp([
        SimpleNamespace(type="thinking", thinking="hmm"),
        SimpleNamespace(type="text", text=VALID_DECISION_JSON),
    ])
    d = llm.complete_json("claude-opus", "sys", "prompt", TradeDecision, max_tokens=16000)

    assert d.journal == "patience" and d.next_check_hours == 24
    kwargs = llm._anthropic.messages.create.call_args.kwargs
    assert "tool_choice" not in kwargs and "tools" not in kwargs
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    assert kwargs["output_config"]["effort"] == "medium"
    assert kwargs["model"] == "claude-opus-5-5"


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal"])
def test_anthropic_incomplete_decision_raises_clear_error(llm, stop_reason):
    llm._anthropic.messages.create.return_value = _anthropic_resp(
        [SimpleNamespace(type="text", text='{"market_analysis": "cut')], stop_reason=stop_reason,
    )
    with pytest.raises(RuntimeError, match=stop_reason):
        llm.complete_json("claude-sonnet", "sys", "prompt", TradeDecision)


def test_research_persists_web_search_fees(llm):
    llm._anthropic.messages.create.return_value = _anthropic_resp(
        [SimpleNamespace(type="text", text="notes")], searches=3,
    )
    notes = llm.research("claude-sonnet", "sys", "prompt")
    assert notes == "notes"
    assert ("web_search", 0, 0, pytest.approx(0.03)) in llm.saved_costs
    assert llm._anthropic.messages.create.call_args.kwargs["output_config"] == {"effort": "medium"}


def test_token_costs_use_registry_prices(llm):
    llm._anthropic.messages.create.return_value = _anthropic_resp(
        [SimpleNamespace(type="text", text=VALID_DECISION_JSON)], in_tok=1_000_000, out_tok=100_000,
    )
    llm.complete_json("claude-opus", "sys", "prompt", TradeDecision)
    # Opus 5.5: $4/M input + $20/M output
    assert ("claude-opus", 1_000_000, 100_000, pytest.approx(4.0 + 2.0)) in llm.saved_costs


# --- Model registry (verified against official docs 2026-10-19) ---

@pytest.mark.parametrize("key, model_id, price_in, price_out", [
    ("claude-opus", "claude-opus-5-5", 4.0, 20.0),
    ("claude-sonnet", "claude-sonnet-5-5", 2.0, 10.0),
    ("gpt-6.1-sol", "gpt-6.1-sol", 2.0, 10.0),
])
def test_registry_models_and_prices(key, model_id, price_in, price_out):
    spec = get_model(key)
    assert (spec.model_id, spec.input_cost_per_m, spec.output_cost_per_m) == (model_id, price_in, price_out)


def test_every_strategy_uses_a_registered_model():
    from api.trading.strategies import ALL_STRATEGIES
    from api.trading.strategies_tw import ALL_TW_STRATEGIES
    for s in ALL_STRATEGIES + ALL_TW_STRATEGIES:
        assert s.model in MODEL_REGISTRY, f"{s.name} uses unregistered model {s.model}"


def test_research_declines_unknown_client_tool_and_keeps_notes(llm):
    llm._anthropic.messages.create.side_effect = [
        _anthropic_resp([
            SimpleNamespace(type="text", text="Market fell "),
            SimpleNamespace(type="text", text="2%."),
            SimpleNamespace(type="tool_use", id="toolu_1", name="web_fetch", input={"url": "x"}),
        ], stop_reason="tool_use"),
        _anthropic_resp([SimpleNamespace(type="text", text="Conclusion: hold.")]),
    ]
    notes = llm.research("claude-sonnet", "sys", "prompt")

    assert notes == "Market fell 2%.\nConclusion: hold."
    second_call_messages = llm._anthropic.messages.create.call_args_list[1].kwargs["messages"]
    tool_result = second_call_messages[-1]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "toolu_1"
    assert tool_result["is_error"] is True


def test_research_stops_after_three_rounds(llm):
    llm._anthropic.messages.create.return_value = _anthropic_resp(
        [SimpleNamespace(type="text", text="...")], stop_reason="pause_turn",
    )
    llm.research("claude-opus", "sys", "prompt")
    assert llm._anthropic.messages.create.call_count == 3
