"""The eval runner (spec §9.9, §9.10): which questions run, the budget guard, and a dry run
of the whole pipeline with the fake LLM."""

import json

import pytest

import run_eval
from metacompass.agent.answer import abstained_answer
from metacompass.agent.loop import AgentResult


def items(n_per_category: int = 2) -> list[dict]:
    return [
        {"id": f"{c}-{i}", "category": c, "subtype": "x", "question": f"q {c} {i}"}
        for c in ("L1", "L2", "L3", "L4", "L5", "L6", "MX")
        for i in range(n_per_category)
    ]


def test_select_items_follows_the_config_categories():
    assert len(run_eval.select_items(items(), "A0")) == 14
    assert {i["category"] for i in run_eval.select_items(items(), "A3")} == {"L2", "L5", "MX"}
    assert {i["category"] for i in run_eval.select_items(items(), "A5")} == {"L5", "MX"}
    narrowed = run_eval.select_items(items(), "A0", categories=["L6"])
    assert {i["category"] for i in narrowed} == {"L6"}


SPEND = {"total_usd": 2.0, "runs": []}


def guard(**overrides):
    kwargs = {
        "set_name": "test", "dry_run": False, "confirm": True, "know_cost": False,
        "estimate": 1.0, "spend": SPEND, "budget": 25.0,
    }  # fmt: skip
    run_eval.guard(**{**kwargs, **overrides})


def test_guard_lets_an_affordable_confirmed_run_through():
    guard()  # 1.0 of 23.0 remaining


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"budget": None}, "EVAL_BUDGET_USD"),
        ({"confirm": False}, "--confirm"),
        ({"estimate": None}, "pilot"),
        ({"estimate": 12.0}, "--i-know-the-cost"),  # over half of the 23.0 left
        ({"spend": {"total_usd": 25.0, "runs": []}}, "budget"),
    ],
)
def test_guard_refuses(overrides, message):
    with pytest.raises(run_eval.RunRefused, match=message):
        guard(**overrides)


def test_guard_allows_what_the_rules_allow():
    guard(estimate=12.0, know_cost=True)  # the extra flag accepts the cost
    guard(set_name="dev", confirm=False, estimate=None)  # the dev pilot needs no approval
    guard(dry_run=True, confirm=False, budget=None, estimate=None)  # no money, no guard


def test_pilot_cost_comes_from_the_latest_dev_full_run():
    spend = {
        "total_usd": 3.0,
        "runs": [
            {"set": "dev", "config": "A0", "questions": 30, "cost_usd": 0.6},
            {"set": "dev", "config": "A1", "questions": 30, "cost_usd": 3.0},
            {"set": "dev", "config": "A0", "questions": 30, "cost_usd": 0.9},
        ],
    }
    assert run_eval.pilot_cost_per_question(spend) == pytest.approx(0.03)
    assert run_eval.pilot_cost_per_question({"total_usd": 0.0, "runs": []}) is None


class PricedAgent:
    """Stands in for the agent: every answer costs the same."""

    def __init__(self, cost: float) -> None:
        self.cost = cost

    def run(self, question: str) -> AgentResult:
        return AgentResult(
            question=question, config_name="full", answer=abstained_answer("-"), steps=[],
            stopped_reason="final", stripped_ids=[], tool_calls=0, input_tokens=10,
            output_tokens=5, cost_usd=self.cost, latency_ms=1,
        )  # fmt: skip


def test_a_run_stops_once_the_budget_is_spent_and_marks_the_rest():
    questions = [
        {**i, "gold": {"answer_ids": [], "forbidden_ids": [], "should_abstain": True},
         "scoring": "abstain"}
        for i in items(1)
    ]  # fmt: skip
    lines, spent = run_eval.run_items(
        PricedAgent(0.4), questions, set_name="dev", code="A0", repeat=1, budget_left=1.0
    )
    assert [line["incomplete"] for line in lines] == [False] * 3 + [True] * 4
    assert spent == pytest.approx(1.2)
    assert lines[0]["score"]["correct"] is True
    assert "result" not in lines[-1]


def test_record_spend_adds_up():
    spend = run_eval.record_spend(
        {"total_usd": 1.0, "runs": []}, {"set": "dev", "config": "A0", "cost_usd": 0.25}
    )
    assert spend["total_usd"] == pytest.approx(1.25)
    assert spend["runs"][-1]["cost_usd"] == 0.25


def test_dry_run_goes_end_to_end_without_network_or_money(generated_dir, tmp_path):
    spend_log = tmp_path / "spend_log.json"
    code = run_eval.main(
        [
            "--set", "dev", "--config", "full", "--llm", "fake", "--embedder", "hash",
            "--data", str(generated_dir), "--out-dir", str(tmp_path), "--limit", "3",
            "--spend-log", str(spend_log),
        ]
    )  # fmt: skip
    assert code == 0
    (path,) = tmp_path.glob("dev_A0_r1_*.jsonl")
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 3
    for line in lines:
        assert (line["model"], line["prompt_version"]) == ("fake", "v1")
        assert line["git_sha"] and line["date"]
        assert line["result"]["stopped_reason"] == "final"
        assert isinstance(line["score"]["correct"], bool)
        assert line["result"]["cost_usd"] == 0.0
    assert not spend_log.exists()  # a dry run spends nothing and logs nothing


def test_a_live_test_run_without_confirm_is_refused(tmp_path, capsys):
    code = run_eval.main(
        ["--set", "test", "--config", "full", "--llm", "provider", "--out-dir", str(tmp_path)]
    )
    assert code == 2
    assert "--confirm" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []
