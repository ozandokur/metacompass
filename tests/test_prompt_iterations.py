"""The dev prompt iterations, summarised from their runs so results.md can show them."""

import json

import pytest

import prompt_iterations


def dev_line(item_id, correct, *, abstained=False, stopped="final", calls=3, version="v3"):
    return {
        "set": "dev", "config": "A0", "repeat": 1, "item_id": item_id, "prompt_version": version,
        "category": item_id.split("-")[1], "subtype": "x", "model": "m",
        "score": {"correct": correct},
        "result": {"stopped_reason": stopped, "input_tokens": 6000, "output_tokens": 300,
                   "steps": [{"kind": "llm", "summary": "x"}] * calls,
                   "answer": {"answer": "", "answer_ids": [], "evidence_ids": [],
                              "abstained": abstained}},
    }  # fmt: skip


ITEMS = [
    {"id": "dev-L1-01", "category": "L1", "gold": {"should_abstain": False}},
    {"id": "dev-L6-01", "category": "L6", "gold": {"should_abstain": True}},
]


def test_a_version_is_summarised_with_accuracy_and_abstention():
    lines = [dev_line("dev-L1-01", True), dev_line("dev-L6-01", False)]  # answered an L6
    summary = prompt_iterations.summarize("v3", lines, ITEMS)
    assert summary["answers"] == 2
    assert summary["accuracy"] == pytest.approx(0.5)
    assert summary["by_category"] == {"L1": {"correct": 1, "n": 1}, "L6": {"correct": 0, "n": 1}}
    assert summary["abstain_recall"] == 0.0  # the one question that should abstain did not
    assert summary["calls_per_answer"] == pytest.approx(3.0)


def test_versions_are_read_from_their_run_folders(tmp_path):
    (tmp_path / "prompt_v3").mkdir()
    (tmp_path / "prompt_v3" / "dev_A0_r1.jsonl").write_text(
        json.dumps(dev_line("dev-L1-01", False, version="v3")) + "\n", encoding="utf-8"
    )
    (tmp_path / "dev_A0_r1.jsonl").write_text(
        json.dumps(dev_line("dev-L1-01", True, version="v5")) + "\n", encoding="utf-8"
    )
    out = tmp_path / "prompt_iterations.json"
    items = tmp_path / "dev_set.json"
    items.write_text(json.dumps({"items": ITEMS}), encoding="utf-8")
    code = prompt_iterations.main(
        ["--dir", str(tmp_path), "--out", str(out), "--set-file", str(items), "--frozen", "v5"]
    )
    assert code == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert [v["version"] for v in written["versions"]] == ["v3", "v5"]
    assert written["frozen"] == "v5"


def test_a_run_whose_lines_disagree_with_the_folder_is_refused(tmp_path):
    (tmp_path / "prompt_v3").mkdir()
    (tmp_path / "prompt_v3" / "dev_A0_r1.jsonl").write_text(
        json.dumps(dev_line("dev-L1-01", True, version="v4")) + "\n", encoding="utf-8"
    )
    items = tmp_path / "dev_set.json"
    items.write_text(json.dumps({"items": ITEMS}), encoding="utf-8")
    with pytest.raises(ValueError, match="v4"):
        prompt_iterations.main(
            ["--dir", str(tmp_path), "--out", str(tmp_path / "x.json"), "--set-file", str(items),
             "--frozen", "v4"]
        )  # fmt: skip
