"""The eval audit (V6): what must hold in the raw result files before a report is written."""

import json
from pathlib import Path

import audit_eval
from scoring import score

ITEMS = [
    {"id": "L1-001", "category": "L1", "scoring": "contains_all",
     "gold": {"answer_ids": ["RPT-0001"], "forbidden_ids": [], "should_abstain": False}},
    {"id": "L6-001", "category": "L6", "scoring": "abstain",
     "gold": {"answer_ids": [], "forbidden_ids": [], "should_abstain": True}},
]  # fmt: skip
PLAN_REPEATS = {"A0": 1}
PLAN_CATEGORIES = {"A0": ("L1", "L6")}


def line(item_id="L1-001", *, ids=("RPT-0001",), abstained=False, correct=None, config="A0",
         repeat=1, frozen="h1", date="2026-09-21", stopped="final", calls=2):  # fmt: skip
    """A result line as the runner writes it; `correct` forces a stored score that disagrees."""
    answer = {"answer": "", "answer_ids": list(ids), "evidence_ids": [], "abstained": abstained}
    stored = score(next(i for i in ITEMS if i["id"] == item_id), answer)
    if correct is not None:
        stored = {**stored, "correct": correct}
    return {
        "set": "test", "config": config, "repeat": repeat, "model": "m", "api_version": "v1",
        "prompt_version": "v5", "frozen_tree_hash": frozen, "git_sha": "abc", "date": date,
        "item_id": item_id, "category": item_id.split("-")[0], "score": stored,
        "result": {"stopped_reason": stopped,
                   "steps": [{"kind": "llm", "summary": "x"}] * calls, "answer": answer},
    }  # fmt: skip


def write(folder: Path, name: str, lines: list[dict]) -> None:
    (folder / name).write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")


def quota(folder: Path, days: dict, observed_rpd=500) -> None:
    body = {"days": {d: {"requests": r, "tokens": 0} for d, r in days.items()},
            "observed_rpd": observed_rpd}  # fmt: skip
    (folder / "quota_log.json").write_text(json.dumps(body), encoding="utf-8")


def audit(folder: Path) -> audit_eval.Audit:
    return audit_eval.audit(folder, ITEMS, PLAN_REPEATS, PLAN_CATEGORIES)


def clean(tmp_path: Path) -> Path:
    write(tmp_path, "test_A0_r1.jsonl", [line(), line("L6-001", ids=(), abstained=True)])
    quota(tmp_path, {"2026-09-21": 10})
    return tmp_path


def test_clean_results_pass(tmp_path):
    result = audit(clean(tmp_path))
    assert result.failures == []
    assert result.missing == {("A0", 1): 0}


def test_two_identities_in_one_file_fail(tmp_path):
    folder = clean(tmp_path)
    write(folder, "test_A0_r1.jsonl", [line(), line("L6-001", ids=(), abstained=True, frozen="h2")])
    assert any("identit" in f for f in audit(folder).failures)


def test_a_question_answered_twice_fails(tmp_path):
    folder = clean(tmp_path)
    write(folder, "test_A0_r1.jsonl", [line(), line()])
    assert any("twice" in f for f in audit(folder).failures)


def test_a_line_filed_under_the_wrong_repeat_fails(tmp_path):
    folder = clean(tmp_path)
    write(folder, "test_A0_r1.jsonl", [line(repeat=2)])
    assert any("file name" in f for f in audit(folder).failures)


def test_a_stored_score_that_rescoring_does_not_reproduce_fails(tmp_path):
    folder = clean(tmp_path)
    write(folder, "test_A0_r1.jsonl", [line(correct=False)])  # the answer is in fact right
    assert any("score" in f for f in audit(folder).failures)


def test_unanswered_questions_are_counted_against_the_plan_not_failed(tmp_path):
    folder = clean(tmp_path)
    write(folder, "test_A0_r1.jsonl", [line()])
    result = audit(folder)
    assert result.failures == []
    assert result.missing == {("A0", 1): 1}


def test_llm_errors_are_counted(tmp_path):
    folder = clean(tmp_path)
    write(folder, "test_A0_r1.jsonl", [line(stopped="llm_error", ids=())])
    assert audit(folder).llm_errors == 1


def test_more_model_calls_than_requests_points_at_a_shared_cache(tmp_path):
    # r2 served from r1's cache would show many model calls the provider never received.
    folder = clean(tmp_path)
    write(
        folder,
        "test_A0_r1.jsonl",
        [line(calls=40), line("L6-001", ids=(), abstained=True, calls=40)],
    )
    quota(folder, {"2026-09-21": 10})
    assert any("cache" in f for f in audit(folder).failures)


def test_a_day_over_the_daily_limit_fails(tmp_path):
    folder = clean(tmp_path)
    quota(folder, {"2026-09-21": 900}, observed_rpd=500)
    assert any("limit" in f for f in audit(folder).failures)
