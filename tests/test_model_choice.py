"""Choosing the model by measurement (D25 branch B): the pre-registered rule, applied to the
candidates' dev runs, and the feasibility bound the free-tier quota puts on each of them."""

import json

import pytest

import model_choice


def dev_line(item_id, correct, *, stopped="final", calls=3, tokens=6000):
    steps = [{"kind": "llm", "summary": "x"}] * calls
    steps += [{"kind": "tool", "name": "search_assets", "arguments": {}, "summary": "{}"}]
    return {
        "set": "dev", "config": "A0", "repeat": 1, "item_id": item_id,
        "category": item_id.split("-")[1], "subtype": "x", "model": "m",
        "score": {"correct": correct},
        "result": {"stopped_reason": stopped, "steps": steps, "input_tokens": tokens,
                   "output_tokens": 300,
                   "answer": {"answer": "", "answer_ids": [], "evidence_ids": [],
                              "abstained": False}},
    }  # fmt: skip


def test_a_candidate_is_summarised_from_its_raw_dev_lines():
    lines = [
        dev_line("dev-L1-01", True),
        dev_line("dev-L1-02", False, stopped="parse_failure"),
        dev_line("dev-L2-01", False, stopped="tool_budget", calls=8),
    ]
    summary = model_choice.summarize("gemini-x", lines, planned=3, rpd=500)
    assert summary["answered"] == 3
    assert summary["accuracy"] == pytest.approx(1 / 3)
    assert summary["stop_reasons"] == {"final": 1, "parse_failure": 1, "tool_budget": 1}
    assert summary["machinery_losses"] == 2  # parse_failure + tool_budget, nothing unanswered
    assert summary["calls_per_answer"] == pytest.approx(14 / 3)


def test_questions_the_run_never_reached_count_as_losses():
    summary = model_choice.summarize("gemini-x", [dev_line("dev-L1-01", True)], planned=3, rpd=20)
    assert summary["unanswered"] == 2
    assert summary["machinery_losses"] == 2


def test_the_plan_length_comes_from_the_measured_calls_and_the_daily_limit():
    lines = [dev_line("dev-L1-01", True, calls=3)] * 2
    summary = model_choice.summarize("gemini-x", lines, planned=2, rpd=100, plan_answers=1000)
    # 3 calls per answer x 1000 answers = 3000 calls, 100 a day -> 30 days
    assert (summary["plan_calls"], summary["plan_days"]) == (3000, 30)
    assert summary["feasible"] is False  # over MAX_PLAN_DAYS


def candidate(model, losses, accuracy, *, feasible=True, lite=True, answered=30, planned=30):
    """A summarize() result, only the fields choose() reads."""
    return {
        "model": model, "machinery_losses": losses, "accuracy": accuracy, "feasible": feasible,
        "lite": lite, "answered": answered, "planned": planned,
        "unanswered": planned - answered, "rpd": 500 if feasible else 20,
        "plan_calls": 2400, "plan_days": 5 if feasible else 120,
    }  # fmt: skip


def test_the_rule_prefers_fewer_machinery_losses_then_accuracy():
    candidates = [candidate("a", 2, 0.9), candidate("b", 0, 0.5)]
    chosen, reason = model_choice.choose(candidates)
    assert chosen["model"] == "b"  # primary criterion first, accuracy only breaks a tie
    assert "parse_failure" in reason or "machinery" in reason


def test_a_model_that_cannot_finish_the_plan_is_not_a_candidate():
    candidates = [
        candidate("big", 0, 0.9, feasible=False, lite=False),
        candidate("lite", 1, 0.6),
    ]
    chosen, reason = model_choice.choose(candidates)
    assert chosen["model"] == "lite"
    assert "big" in reason and "days" in reason


def test_a_tie_on_both_criteria_keeps_the_non_lite_model():
    candidates = [candidate("lite", 0, 0.7), candidate("full", 0, 0.7, lite=False)]
    chosen, _ = model_choice.choose(candidates)
    assert chosen["model"] == "full"


def test_a_feasible_candidate_with_unanswered_questions_blocks_the_choice():
    candidates = [candidate("half", 1, 0.6, answered=18)]
    with pytest.raises(model_choice.NotReady, match="half"):
        model_choice.choose(candidates)


def test_the_summary_file_carries_the_rule_and_every_candidate(tmp_path):
    for model, correct in (("gemini-a", True), ("gemini-b", False)):
        folder = tmp_path / model
        folder.mkdir()
        (folder / "dev_A0_r1.jsonl").write_text(
            json.dumps(dev_line("dev-L1-01", correct)) + "\n", encoding="utf-8"
        )
        (tmp_path / f"quota_{model}.json").write_text(
            json.dumps({"observed_rpd": 500}), encoding="utf-8"
        )
    out = tmp_path / "model_choice.json"
    assert model_choice.main(["--dir", str(tmp_path), "--out", str(out), "--planned", "1"]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert [c["model"] for c in written["candidates"]] == ["gemini-a", "gemini-b"]
    assert written["chosen"] == "gemini-a"
    assert written["rule"] and written["reason"]
    assert written["candidates"][0]["observed_rpd"] == 500
