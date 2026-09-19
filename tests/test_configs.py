"""Evaluation configurations (spec §9.8): the full system and leave-one-out ablations."""

import json
from pathlib import Path

import configs
from metacompass.config import ALL_SIX_TOOLS, AgentConfig

ROOT = Path(__file__).resolve().parents[1]


def changed_fields(code: str) -> dict:
    full = configs.CONFIGS["A0"].model_dump(exclude={"name"})
    other = configs.CONFIGS[code].model_dump(exclude={"name"})
    return {k: v for k, v in other.items() if v != full[k]}


def test_a0_is_the_default_agent():
    assert configs.CONFIGS["A0"] == AgentConfig(name="full")
    assert configs.resolve("full") == configs.resolve("A0") == "A0"


def test_each_ablation_changes_only_its_component():
    without = lambda tool: [t for t in ALL_SIX_TOOLS if t != tool]  # noqa: E731
    assert changed_fields("A1") == {"retrieval_mode": "dense"}
    assert changed_fields("A2") == {"retrieval_mode": "bm25"}
    assert changed_fields("A3") == {"tools_enabled": without("resolve_owner")}
    assert changed_fields("A4") == {"abstain_instructions": False, "show_match_quality": False}
    assert changed_fields("A5") == {"tools_enabled": without("impact_analysis")}
    names = {code: c.name for code, c in configs.CONFIGS.items()}
    assert names == {
        "A0": "full", "A1": "dense-only", "A2": "bm25-only", "A3": "llm-walks-chain",
        "A4": "no-abstain", "A5": "no-composite-impact",
    }  # fmt: skip


def test_categories_repeats_and_total_runs_match_the_spec():
    items = json.loads((ROOT / "eval" / "test_set.json").read_text(encoding="utf-8"))["items"]
    assert configs.CATEGORIES["A3"] == ("L2", "L5", "MX")
    assert configs.CATEGORIES["A5"] == ("L5", "MX")
    runs = {
        code: configs.REPEATS[code] * sum(i["category"] in configs.CATEGORIES[code] for i in items)
        for code in configs.CONFIGS
    }
    # D25 (free tier): only the full system repeats; its spread is the noise yardstick.
    assert configs.REPEATS == {"A0": 3, "A1": 1, "A2": 1, "A3": 1, "A4": 1, "A5": 1}
    assert runs == {"A0": 300, "A1": 100, "A2": 100, "A3": 40, "A4": 100, "A5": 25}
    assert sum(runs.values()) == 665
