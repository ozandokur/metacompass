"""The input-composition measurement (eval/measure_input.py): tool paths per gold type and
shares that add up."""

import json
from pathlib import Path

import pytest

import measure_input
from metacompass.config import AgentConfig
from metacompass.tools.registry import build_registry

ROOT = Path(__file__).resolve().parents[1]


def test_every_dev_question_has_a_tool_path(real_ctx):
    items = json.loads((ROOT / "eval" / "dev_set.json").read_text(encoding="utf-8"))["items"]
    for item in items:
        calls = measure_input.tool_path(item)
        assert calls and all(name and isinstance(args, dict) for name, args in calls), item["id"]
    with pytest.raises(ValueError):
        measure_input.tool_path({"gold_spec": {"type": "guess"}, "question": "?"})


def test_shares_add_up_and_tool_results_are_counted(real_ctx):
    items = json.loads((ROOT / "eval" / "dev_set.json").read_text(encoding="utf-8"))["items"]
    registry = build_registry(real_ctx.store, real_ctx.retrievers, real_ctx.graph, AgentConfig())
    result = measure_input.measure(registry, items[:6])
    assert result["questions"] == 6
    assert sum(result["share_by_source"].values()) == pytest.approx(1.0, abs=0.01)
    assert result["share_by_source"]["tool_results"] > 0
    assert result["share_by_source"]["system"] > 0
    for tool in result["tools"].values():
        assert sum(tool["fields"].values()) <= 1.0 + 1e-9


def test_token_composition_scales_each_source_by_its_own_ratio():
    # Real tokens per source = characters x the model's tokens-per-character for that source
    # (measured with countTokens); a version's shares then add up to one.
    composition = {
        "mean_input_chars_per_question": 1000,
        "share_by_source": {"system": 0.2, "tools": 0.6, "tool_results": 0.15, "other": 0.05},
    }
    ratios = {"system": 0.25, "tools": 0.2, "tool_results": 0.3, "other": 0.25}
    tokens = measure_input.compose_tokens(composition, ratios)
    assert tokens["tokens_per_question"] == pytest.approx(
        200 * 0.25 + 600 * 0.2 + 150 * 0.3 + 50 * 0.25
    )
    assert sum(tokens["share_by_source"].values()) == pytest.approx(1.0)
    assert tokens["share_by_source"]["tools"] == pytest.approx(120 / 227.5, abs=1e-3)
