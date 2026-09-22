"""Proving by a cache replay that lines written under changed infrastructure code are what the
frozen code gives (Q-V0-1)."""

import json

import verify_replay

OLD, FROZEN = "5f0ee29ab437ea65", "b4025ab1103ea7c9"


def line(item_id="L1-001", *, frozen=OLD, answer="RPT-0001 is it.", ids=("RPT-0001",),
         tools=(("search_assets", {"query": "x"}),), tokens=(100, 20), latency=900):  # fmt: skip
    steps = [{"kind": "llm", "summary": "tool calls", "duration_ms": 5}]
    steps += [{"kind": "tool", "name": n, "arguments": a, "summary": "{}", "duration_ms": 3}
              for n, a in tools]  # fmt: skip
    return {
        "item_id": item_id, "repeat": 1, "frozen_tree_hash": frozen, "date": "2026-09-21",
        "git_sha": "b1eed88",
        "result": {"answer": {"answer": answer, "answer_ids": list(ids), "evidence_ids": [],
                              "abstained": False},
                   "stopped_reason": "final", "steps": steps, "tool_calls": len(tools),
                   "input_tokens": tokens[0], "output_tokens": tokens[1], "latency_ms": latency},
    }  # fmt: skip


def test_timings_and_dates_do_not_count_as_differences():
    replay = {**line(latency=40), "date": "2026-09-22", "git_sha": "128acfb"}
    assert verify_replay.differences(line(), replay) == []


def test_every_compared_field_is_caught():
    original = line()
    assert verify_replay.differences(original, line(answer="Another text.")) == ["answer"]
    assert verify_replay.differences(original, line(ids=("RPT-0002",))) == ["answer_ids"]
    assert "tool calls" in verify_replay.differences(
        original, line(tools=(("search_assets", {"query": "y"}),))
    )
    assert verify_replay.differences(original, line(tokens=(101, 20))) == ["input_tokens"]


def test_identical_lines_are_kept_with_the_frozen_hash_and_the_rest_are_dropped():
    originals = [line("L1-001"), line("L1-002"), line("L1-003"), line("L1-004", frozen=FROZEN)]
    replays = {"L1-001": line("L1-001"), "L1-002": line("L1-002", answer="changed")}
    kept, report = verify_replay.apply(originals, replays, old=OLD, frozen=FROZEN)
    by_id = {row["item_id"]: row for row in kept}
    assert set(by_id) == {"L1-001", "L1-004"}  # L1-002 differs, L1-003 missed: both go
    assert by_id["L1-001"]["frozen_tree_hash"] == FROZEN
    assert by_id["L1-001"]["equivalence"] == "cache_replay_verified"
    assert by_id["L1-001"]["frozen_tree_hash_produced"] == OLD  # the provenance stays
    assert by_id["L1-001"]["result"]["latency_ms"] == 900  # the original line, not the replay
    assert by_id["L1-004"] == line("L1-004", frozen=FROZEN)  # lines under the freeze untouched
    assert report == {"checked": 3, "identical": 1, "differs": {"L1-002": ["answer"]},
                      "missed": ["L1-003"]}  # fmt: skip


def test_the_files_are_rewritten_and_the_counts_saved(tmp_path):
    results, replay = tmp_path / "results", tmp_path / "replay"
    results.mkdir()
    replay.mkdir()
    rows = [line("L1-001"), line("L1-002")]
    (results / "test_A0_r1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (replay / "test_A0_r1.jsonl").write_text(json.dumps(line("L1-001")) + "\n")
    summary = verify_replay.main_for(results, replay, old=OLD, frozen=FROZEN)
    kept = (results / "test_A0_r1.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(r)["item_id"] for r in kept] == ["L1-001"]
    assert summary["files"]["test_A0_r1.jsonl"]["identical"] == 1
    assert summary["files"]["test_A0_r1.jsonl"]["missed"] == ["L1-002"]
    saved = json.loads((results / "replay_verification.json").read_text(encoding="utf-8"))
    assert saved["totals"] == {"checked": 2, "identical": 1, "differs": 0, "missed": 1}
