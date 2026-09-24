"""The IDs the model was actually shown, recovered by replaying the stored tool calls."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "eval"))
import agent_report  # noqa: E402
import replay_tool_outputs as replay  # noqa: E402

RESULTS = ROOT / "eval" / "results"


class FakeRegistry:
    """Stands in for the real one: the point under test is the replay, not the tools."""

    def __init__(self, answers: dict[tuple[str, str], list[str]]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, dict]] = []

    def call(self, name: str, args: dict) -> tuple[dict, list[str]]:
        self.calls.append((name, args))
        return {}, self.answers.get((name, json.dumps(args, sort_keys=True)), [])


def line(item_id: str, calls: list[tuple[str, dict]], config: str = "A0") -> dict:
    steps = [{"kind": "llm", "name": None, "arguments": None, "summary": "x"}]
    steps += [
        {"kind": "tool", "name": name, "arguments": args, "summary": "{}"} for name, args in calls
    ]
    return {
        "set": "test",
        "config": config,
        "repeat": 1,
        "item_id": item_id,
        "incomplete": False,
        "result": {"steps": steps},
    }


def test_the_ids_shown_are_the_union_over_the_calls_in_order():
    one = line("L5-001", [("search_assets", {"query": "a"}), ("impact_analysis", {"t": "TBL-1"})])
    registry = FakeRegistry(
        {
            ("search_assets", '{"query": "a"}'): ["TBL-1", "RPT-9"],
            ("impact_analysis", '{"t": "TBL-1"}'): ["EMP-3", "RPT-9"],
        }
    )
    assert replay.ids_shown(one, registry) == ["TBL-1", "RPT-9", "EMP-3"]
    assert len(registry.calls) == 2


def test_an_answer_that_called_nothing_was_shown_nothing():
    assert replay.ids_shown(line("L6-001", []), FakeRegistry({})) == []


def test_the_key_names_the_configuration_the_repeat_and_the_question():
    assert replay.key(line("L1-001", [], config="A2")) == "A2/1/L1-001"


def recorded() -> dict[str, list[str]]:
    path = RESULTS / replay.OUTPUT_NAME
    if not path.exists():
        pytest.skip(f"{replay.OUTPUT_NAME} not written yet")
    return json.loads(path.read_text(encoding="utf-8"))["shown"]


def answered() -> set[str]:
    keys = set()
    for result_file in sorted(RESULTS.glob("test_A*_r*.jsonl")):
        for raw in result_file.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                one = json.loads(raw)
                if not one.get("incomplete"):
                    keys.add(replay.key(one))
    return keys


def test_the_recorded_file_holds_no_answer_the_results_do_not():
    """A run in progress leaves the file behind, which the page says out loud; an entry with
    no line behind it is different — it means the file was written from results since gone."""
    orphans = sorted(set(recorded()) - answered())
    assert orphans == [], f"{len(orphans)} replayed answers have no result line, e.g. {orphans[:3]}"


def test_a_partly_replayed_run_is_said_out_loud_instead_of_quietly_guessed():
    lines = [line("L1-001", []), line("L1-002", [])]
    for one in lines:
        one.update(category="L1", score={"correct": False})
        one["result"]["answer"] = {"answer_ids": [], "abstained": False}
    basis = "\n".join(
        agent_report.error_kinds_section(
            lines,
            [
                {"id": item, "category": "L1", "question": "q",
                 "gold": {"answer_ids": ["RPT-0001"], "forbidden_ids": [], "should_abstain": False}}
                for item in ("L1-001", "L1-002")
            ],
            {"A0/1/L1-001": []},
        )
    )  # fmt: skip
    assert "1 of 2 answers are not in the replay file yet" in basis
