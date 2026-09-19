"""Trivial baselines without an LLM (eval/baselines.py): where the agent must beat a guess."""

import json
from pathlib import Path

import pytest

import baselines
from conftest import SEED
from metacompass.config import AgentConfig
from metacompass.tools.registry import build_registry

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(SEED != 42, reason="the committed sets describe the seed-42 data")


@pytest.fixture(scope="module")
def result(real_ctx):
    items = json.loads((ROOT / "eval" / "test_set.json").read_text(encoding="utf-8"))["items"]
    registry = build_registry(real_ctx.store, real_ctx.retrievers, real_ctx.graph, AgentConfig())
    return baselines.run_baselines(registry, real_ctx.store, items)


def acc(result, name, category):
    return result[name]["accuracy"].get(category)


def test_every_baseline_is_scored_only_where_it_applies(result):
    assert set(result) == {
        "always_abstain", "retrieval_top1", "recorded_owner", "all_heads", "default_depth_lineage",
    }  # fmt: skip
    assert set(result["always_abstain"]["accuracy"]) == {"L1", "L2", "L3", "L4", "L5", "L6", "MX"}
    assert set(result["retrieval_top1"]["accuracy"]) == {"L1", "L4"}
    assert set(result["recorded_owner"]["accuracy"]) == {"L2"}
    assert set(result["all_heads"]["accuracy"]) == {"L5"}
    assert set(result["default_depth_lineage"]["accuracy"]) == {"L3"}


def test_abstaining_is_right_exactly_on_the_unanswerable_questions(result):
    assert acc(result, "always_abstain", "L6") == {"accuracy": 1.0, "n": 15}
    assert acc(result, "always_abstain", "L1")["accuracy"] == 0.0


def test_the_recorded_owner_is_right_only_while_the_owner_is_still_here(result):
    # L2 has 3 active-owner questions out of 15; every other question needs the walk.
    assert acc(result, "recorded_owner", "L2") == {"accuracy": pytest.approx(3 / 15), "n": 15}


def test_naming_every_head_fails_every_broadcast_question(result):
    # The heads of unaffected departments are forbidden (Q-F5-2b), so the guess never passes.
    assert acc(result, "all_heads", "L5") == {"accuracy": 0.0, "n": 3}
