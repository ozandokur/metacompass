"""The eval runner (spec §9.9, §9.10 as changed by D25): which questions run, writing each
answer as soon as it exists, resuming where a run stopped, and stopping cleanly when the
free-tier quota is used up."""

import json

import pytest

import run_eval
from metacompass.agent.answer import abstained_answer
from metacompass.agent.llm import FakeLLM, LLMResponse, QuotaExhausted
from metacompass.agent.loop import AgentResult


@pytest.fixture(scope="module")
def generated_dir(writable_data_dir):
    """This module writes caches next to the data, so it gets a copy of the shared set."""
    return writable_data_dir


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
    """Stands in for the agent; runs out of quota after `quota` answers. `reasons` scripts
    the stop reason of each answer (default: all "final")."""

    def __init__(self, quota: int | None = None, reasons: list[str] | None = None) -> None:
        self.quota, self.asked, self.reasons = quota, [], list(reasons or [])

    def run(self, question: str) -> AgentResult:
        if self.quota is not None and len(self.asked) == self.quota:
            raise QuotaExhausted("daily requests used up")
        self.asked.append(question)
        reason = self.reasons.pop(0) if self.reasons else "final"
        return AgentResult(
            question=question, config_name="full", answer=abstained_answer("-"), steps=[],
            stopped_reason=reason, stripped_ids=[], tool_calls=0, input_tokens=10,
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
        assert (line["model"], line["api_version"]) == ("fake", "fake")
        assert line["prompt_version"] == run_eval.CONFIGS["A0"].prompt_version
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


def test_result_lines_end_in_lf_on_every_platform(tmp_path):
    path = tmp_path / "dev_A0_r1.jsonl"
    run_eval.answer_all(Agent(), items(1)[:2], path=path, base_line=BASE)
    assert b"\r\n" not in path.read_bytes()


def test_a_failed_llm_call_is_not_scored_and_the_question_is_asked_again_later(tmp_path):
    # An llm_error answer is an abstention the agent never chose; on an L6 question it would
    # score as a correct abstain. It is not written, so a later run asks again.
    path = tmp_path / "dev_A0_r1.jsonl"
    agent = Agent(reasons=["final", "llm_error", "final"])
    assert run_eval.answer_all(agent, items(1)[:3], path=path, base_line=BASE) == 2
    assert run_eval.completed_ids(path) == {"L1-0", "L3-0"}


def test_three_failed_llm_calls_in_a_row_stop_the_run(tmp_path):
    path = tmp_path / "dev_A0_r1.jsonl"
    agent = Agent(reasons=["llm_error"] * 5)
    with pytest.raises(run_eval.ProviderDown):
        run_eval.answer_all(agent, items(1), path=path, base_line=BASE)
    assert len(agent.asked) == 3
    assert run_eval.completed_ids(path) == set()


def test_answers_from_another_model_or_prompt_are_never_resumed(generated_dir, tmp_path, capsys):
    # A dry run's lines (model "fake") once made a live run skip every question. A file that
    # holds answers from another model, API or prompt version must stop the run, not count.
    path = tmp_path / "dev_A0_r1.jsonl"
    old = {"item_id": "dev-L1-01", "model": "other-model", "api_version": "fake",
           "prompt_version": run_eval.CONFIGS["A0"].prompt_version}  # fmt: skip
    path.write_text(json.dumps(old) + "\n", encoding="utf-8")
    assert dry_run(generated_dir, tmp_path) == 2
    assert "other-model" in capsys.readouterr().err
    assert path.read_text(encoding="utf-8").splitlines() == [json.dumps(old)]


def test_the_model_can_be_chosen_on_the_command_line(generated_dir, tmp_path, monkeypatch):
    # The candidates of a model comparison must not need an .env edit each time, and the
    # chosen model has to reach the provider, the run's identity and every result line.
    seen = {}

    class Stub(FakeLLM):
        def __init__(self, model):
            super().__init__([], then=run_eval.dry_run_llm().then)
            self.model = model

        def check_model(self):
            seen["checked"] = self.model

    def fake_make_llm(settings):
        seen["asked"] = settings.llm_model
        return Stub(settings.llm_model)

    monkeypatch.setattr(run_eval, "make_llm", fake_make_llm)
    code = run_eval.main(
        ["--set", "dev", "--config", "full", "--embedder", "hash", "--data", str(generated_dir),
         "--out-dir", str(tmp_path), "--limit", "1", "--env-file", str(tmp_path / "no.env"),
         "--quota-log", str(tmp_path / "quota.json"), "--model", "gemini-3.5-flash-lite"]
    )  # fmt: skip
    assert code == 0
    assert seen == {"asked": "gemini-3.5-flash-lite", "checked": "gemini-3.5-flash-lite"}
    line = json.loads((tmp_path / "dev_A0_r1.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert line["model"] == "gemini-3.5-flash-lite"


def test_each_repeat_gets_its_own_cache_so_the_spread_is_real(generated_dir, tmp_path, monkeypatch):
    # The three A0 repeats exist to measure run-to-run variance. If the cache key were the
    # same across repeats, r2 and r3 would be served from r1's answers, every std would be
    # 0.00 and the "real difference" threshold would be meaningless.
    calls = []

    class Stub(FakeLLM):
        model = "stub-model"

        def check_model(self):
            return None

        def chat(self, messages, tools, json_mode=False):
            calls.append(len(calls))
            return super().chat(messages, tools, json_mode)

    monkeypatch.setattr(run_eval, "make_llm", lambda settings: Stub([], then=run_eval.dry_run_llm().then))  # fmt: skip
    code = run_eval.main(
        ["--set", "test", "--config", "A0", "--repeat", "2", "--embedder", "hash",
         "--data", str(generated_dir), "--out-dir", str(tmp_path), "--limit", "1",
         "--env-file", str(tmp_path / "no.env"), "--quota-log", str(tmp_path / "quota.json")]
    )  # fmt: skip
    assert code == 0
    assert len(calls) == 2  # one question, two repeats, two calls: no cache hit across repeats
    assert run_eval.cache_salt("test", 1) != run_eval.cache_salt("test", 2)
    # Dev iterations deliberately share one cache: re-running a dev question is free.
    assert run_eval.cache_salt("dev", 1) == run_eval.cache_salt("dev", 2)


def test_every_line_carries_the_frozen_tree_hash(generated_dir, tmp_path):
    assert dry_run(generated_dir, tmp_path) == 0
    rows = (tmp_path / "dev_A0_r1.jsonl").read_text(encoding="utf-8").splitlines()
    assert {json.loads(row)["frozen_tree_hash"] for row in rows} == {run_eval.frozen_tree_hash()}


def test_a_file_made_under_other_frozen_code_is_refused(
    generated_dir, tmp_path, capsys, monkeypatch
):
    # V0: runs take days while other work goes on in the repository. If the measured code
    # changed in between, the new answers would measure a different system than the old ones.
    monkeypatch.setattr(run_eval, "frozen_tree_hash", lambda: "aaaaaaaaaaaaaaaa")
    assert dry_run(generated_dir, tmp_path) == 0
    before = (tmp_path / "dev_A0_r1.jsonl").read_text(encoding="utf-8")
    monkeypatch.setattr(run_eval, "frozen_tree_hash", lambda: "bbbbbbbbbbbbbbbb")
    assert dry_run(generated_dir, tmp_path) == 2
    assert "aaaaaaaaaaaaaaaa" in capsys.readouterr().err
    assert (tmp_path / "dev_A0_r1.jsonl").read_text(encoding="utf-8") == before
