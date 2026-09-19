"""The eval runner (spec §9.9, §9.10 as changed by D25): which questions run, writing each
answer as soon as it exists, resuming where a run stopped, and stopping cleanly when the
free-tier quota is used up."""

import json

import pytest

import run_eval
from metacompass.agent.answer import abstained_answer
from metacompass.agent.llm import FakeLLM, LLMResponse, QuotaExhausted
from metacompass.agent.loop import AgentResult


def items(n_per_category: int = 2) -> list[dict]:
    return [
        {
            "id": f"{c}-{i}", "category": c, "subtype": "x", "question": f"q {c} {i}",
            "gold": {"answer_ids": [], "forbidden_ids": [], "should_abstain": True},
            "scoring": "abstain",
        }
        for c in ("L1", "L2", "L3", "L4", "L5", "L6", "MX")
        for i in range(n_per_category)
    ]  # fmt: skip


def test_select_items_follows_the_config_categories():
    assert len(run_eval.select_items(items(), "A0")) == 14
    assert {i["category"] for i in run_eval.select_items(items(), "A3")} == {"L2", "L5", "MX"}
    assert {i["category"] for i in run_eval.select_items(items(), "A5")} == {"L5", "MX"}
    narrowed = run_eval.select_items(items(), "A0", categories=["L6"])
    assert {i["category"] for i in narrowed} == {"L6"}


class Agent:
    """Stands in for the agent; runs out of quota after `quota` answers."""

    def __init__(self, quota: int | None = None) -> None:
        self.quota, self.asked = quota, []

    def run(self, question: str) -> AgentResult:
        if self.quota is not None and len(self.asked) == self.quota:
            raise QuotaExhausted("daily requests used up")
        self.asked.append(question)
        return AgentResult(
            question=question, config_name="full", answer=abstained_answer("-"), steps=[],
            stopped_reason="final", stripped_ids=[], tool_calls=0, input_tokens=10,
            output_tokens=5, cost_usd=0.0, latency_ms=1,
        )  # fmt: skip


BASE = {"set": "dev", "config": "A0", "repeat": 1}


def test_each_answer_is_on_disk_before_the_next_question(tmp_path):
    path = tmp_path / "dev_A0_r1.jsonl"
    with pytest.raises(QuotaExhausted):
        run_eval.answer_all(Agent(quota=3), items(1), path=path, base_line=BASE)
    lines = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()]
    assert [line["item_id"] for line in lines] == ["L1-0", "L2-0", "L3-0"]
    assert lines[0]["score"]["correct"] is True
    assert (lines[0]["set"], lines[0]["config"], lines[0]["repeat"]) == ("dev", "A0", 1)


def test_a_second_run_answers_only_what_is_missing(tmp_path):
    path = tmp_path / "dev_A0_r1.jsonl"
    with pytest.raises(QuotaExhausted):
        run_eval.answer_all(Agent(quota=3), items(1), path=path, base_line=BASE)
    done = run_eval.completed_ids(path)
    assert done == {"L1-0", "L2-0", "L3-0"}
    todo = [i for i in items(1) if i["id"] not in done]
    second = Agent()
    assert run_eval.answer_all(second, todo, path=path, base_line=BASE) == 4
    assert second.asked == ["q L4 0", "q L5 0", "q L6 0", "q MX 0"]
    ids = [json.loads(row)["item_id"] for row in path.read_text(encoding="utf-8").splitlines()]
    assert sorted(ids) == sorted(i["id"] for i in items(1))  # every question exactly once


def test_completed_ids_of_a_missing_file_is_empty(tmp_path):
    assert run_eval.completed_ids(tmp_path / "nothing.jsonl") == set()


def dry_run(generated_dir, tmp_path, *extra) -> int:
    return run_eval.main(
        [
            "--set", "dev", "--config", "full", "--llm", "fake", "--embedder", "hash",
            "--data", str(generated_dir), "--out-dir", str(tmp_path), "--limit", "3",
            "--env-file", str(tmp_path / "no.env"), *extra,
        ]
    )  # fmt: skip


def test_dry_run_goes_end_to_end_and_resumes_to_nothing(generated_dir, tmp_path, capsys):
    assert dry_run(generated_dir, tmp_path) == 0
    path = tmp_path / "dev_A0_r1.jsonl"
    lines = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 3
    for line in lines:
        assert (line["model"], line["prompt_version"]) == ("fake", "v1")
        assert line["git_sha"] and line["date"]
        assert line["result"]["stopped_reason"] == "final"
        assert isinstance(line["score"]["correct"], bool)
    assert dry_run(generated_dir, tmp_path) == 0  # resume is the default: nothing left
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3
    assert "0 to answer" in capsys.readouterr().out


def test_no_resume_refuses_to_overwrite_answers(generated_dir, tmp_path, capsys):
    assert dry_run(generated_dir, tmp_path) == 0
    assert dry_run(generated_dir, tmp_path, "--no-resume") == 2
    assert "already has" in capsys.readouterr().err


def test_an_exhausted_quota_ends_the_run_cleanly(generated_dir, tmp_path, monkeypatch, capsys):
    answer = json.dumps({"answer": "-", "answer_ids": [], "evidence_ids": [], "abstained": True})
    done = LLMResponse(
        content=answer, tool_calls=[], input_tokens=1, output_tokens=1, raw_model="f"
    )
    monkeypatch.setattr(
        run_eval, "dry_run_llm", lambda: FakeLLM([done, done, QuotaExhausted("day over")])
    )
    assert dry_run(generated_dir, tmp_path) == 0  # a quota stop is not an error
    assert len((tmp_path / "dev_A0_r1.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    assert "quota" in capsys.readouterr().out


def test_a_live_run_without_llm_settings_is_refused(generated_dir, tmp_path, capsys):
    code = run_eval.main(
        [
            "--set", "dev", "--config", "full", "--llm", "provider", "--embedder", "hash",
            "--data", str(generated_dir), "--out-dir", str(tmp_path),
            "--env-file", str(tmp_path / "no.env"),
        ]
    )  # fmt: skip
    assert code == 2
    assert "LLM_" in capsys.readouterr().err
    assert list(tmp_path.glob("*.jsonl")) == []
