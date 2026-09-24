"""V12: configurations must answer from the model, not from each other's cached answers."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import audit_cache_isolation as isolation  # noqa: E402


def line(config: str, item_id: str, calls: list[int], tools: list[tuple[str, dict]]) -> dict:
    """One result line: `calls` are the model steps' durations, `tools` what it called."""
    steps = [{"kind": "llm", "name": None, "arguments": None, "duration_ms": ms} for ms in calls]
    steps += [
        {"kind": "tool", "name": name, "arguments": args, "duration_ms": 12} for name, args in tools
    ]
    return {
        "set": "test",
        "config": config,
        "repeat": 1,
        "item_id": item_id,
        "result": {"steps": steps, "latency_ms": sum(calls) + 12 * len(tools)},
    }


def write(folder: Path, config: str, lines: list[dict]) -> None:
    path = folder / f"test_{config}_r1.jsonl"
    path.write_text("".join(json.dumps(one) + "\n" for one in lines), encoding="utf-8")


def real_run(config: str, count: int) -> list[dict]:
    return [
        line(config, f"L1-{n:03d}", [1800, 2400], [("search_assets", {"query": f"q{n}"})])
        for n in range(count)
    ]


def test_a_cached_model_step_did_not_spend_a_request():
    replayed = line("A1", "L1-001", [1, 1], [("search_assets", {"query": "q"})])
    live = line("A1", "L1-002", [1800, 2400], [("search_assets", {"query": "q"})])
    assert isolation.requests_spent(replayed) == 0
    assert isolation.requests_spent(live) == 2


def test_the_trace_is_tool_names_and_arguments_in_order():
    one = line("A0", "L1-001", [900], [("search_assets", {"query": "a"}), ("get_record", {"i": 1})])
    other = line("A1", "L1-001", [3], [("get_record", {"i": 1}), ("search_assets", {"query": "a"})])
    assert isolation.trace(one) != isolation.trace(other)  # order counts
    assert isolation.trace(one)[0][0] == "search_assets"


def test_a_configuration_replaying_another_is_failed(tmp_path):
    write(tmp_path, "A0", real_run("A0", 20))
    replayed = [
        line("A1", f"L1-{n:03d}", [1, 1], [("search_assets", {"query": f"q{n}"})])
        for n in range(20)
    ]
    write(tmp_path, "A1", replayed)
    report = isolation.isolation(tmp_path)
    assert any("A1" in failure for failure in report.failures)
    assert report.stats["A1"].requests == 0


def test_the_same_trace_alone_is_not_a_failure(tmp_path):
    """Two configurations may well call the same tool with the same argument; that is not
    evidence of a shared cache. Spending no requests is."""
    write(tmp_path, "A0", real_run("A0", 20))
    write(tmp_path, "A1", real_run("A1", 20))
    report = isolation.isolation(tmp_path)
    assert report.failures == []
    assert report.shared_traces == 20  # every question, and still fine
    assert report.comparable == 20


def test_a_configuration_under_half_of_the_baselines_rate_is_failed(tmp_path):
    four_calls = [
        line("A0", f"L1-{n:03d}", [1800, 2400, 2000, 1900], [("search_assets", {"query": f"q{n}"})])
        for n in range(20)
    ]
    write(tmp_path, "A0", four_calls)  # four model calls per answer, so the floor is two
    thin = [
        line("A2", f"L1-{n:03d}", [1, 1, 1, 2500], [("search_assets", {"query": f"q{n}"})])
        for n in range(20)
    ]
    write(tmp_path, "A2", thin)  # one real call per answer, under the floor
    report = isolation.isolation(tmp_path)
    assert any("A2" in failure and "per answer" in failure for failure in report.failures)


def test_a_configuration_exactly_at_the_floor_is_not_failed(tmp_path):
    """The rule is *under* half; a configuration that legitimately makes fewer calls than the
    full system, such as one without a tool, must not be failed for being efficient."""
    write(tmp_path, "A0", real_run("A0", 20))  # two model calls per answer, floor one
    lean = [
        line("A4", f"L1-{n:03d}", [2500], [("search_assets", {"query": f"q{n}"})])
        for n in range(20)
    ]
    write(tmp_path, "A4", lean)
    assert isolation.isolation(tmp_path).failures == []


def test_answers_that_came_back_impossibly_fast_are_counted(tmp_path):
    write(tmp_path, "A0", real_run("A0", 20))
    quick = real_run("A1", 19) + [line("A1", "L1-099", [1, 1], [("search_assets", {"query": "q"})])]
    write(tmp_path, "A1", quick)
    report = isolation.isolation(tmp_path)
    assert report.stats["A1"].fast_answers == 1
    assert report.stats["A1"].free_answers == 1


def test_the_projects_own_results_are_isolated():
    report = isolation.isolation(ROOT / "eval" / "results")
    assert report.failures == []


# ------------------------------------------------- the results page carries the evidence

sys.path.insert(0, str(ROOT / "eval"))
import report  # noqa: E402


def built(configs: dict[str, int]) -> isolation.Isolation:
    folder = Path(__import__("tempfile").mkdtemp())
    for config, count in configs.items():
        write(folder, config, real_run(config, count))
    return isolation.isolation(folder)


def test_the_page_shows_what_each_configuration_spent_to_answer():
    page = report.render_results(None, isolated=built({"A0": 20, "A1": 20}))
    assert "| A1 | 20 | 40 | 2.00 |" in page
    assert "Median latency" in page
    # The share is shown, but the reader is told it is not the test.
    assert "not a failure condition" in page


def test_the_page_says_the_cache_sharing_was_found_and_what_was_done():
    page = report.render_results(None, items=[], set_name="test")
    threats = page.split("## Threats to validity")[1]
    assert "67" in threats and "salt" in threats


def test_the_page_is_refused_when_a_configuration_is_not_isolated(tmp_path, capsys):
    """End to end: real lines, with A1's model calls made to look cache-served."""
    results = ROOT / "eval" / "results"
    for path in [*sorted(results.glob("test_A0_r*.jsonl")), results / "quota_log.json"]:
        (tmp_path / path.name).write_bytes(path.read_bytes())
    replayed = []
    for raw in (results / "test_A1_r1.jsonl").read_text(encoding="utf-8").splitlines():
        one = json.loads(raw)
        for step in one["result"]["steps"]:
            if step["kind"] == "llm":
                step["duration_ms"] = 1
        replayed.append(json.dumps(one))
    (tmp_path / "test_A1_r1.jsonl").write_text("\n".join(replayed) + "\n", encoding="utf-8")
    out = tmp_path / "results.md"
    assert report.main(["--results-dir", str(tmp_path), "--out", str(out)]) == 1
    assert not out.exists()
    # Named, so this cannot pass because some other audit happened to refuse first.
    refusal = capsys.readouterr().err
    assert "audit_cache_isolation.py" in refusal
    assert "A1 spent 0.00 requests per answer" in refusal


def test_the_page_states_the_measured_gap_around_the_threshold(tmp_path):
    """The sentence about the threshold must come from the data, not from a memory of it."""
    write(tmp_path, "A0", real_run("A0", 4))
    write(tmp_path, "A1", [line("A1", "L1-000", [1, 1800], [("get_record", {"i": 1})])])
    report = isolation.isolation(tmp_path)
    assert (report.slowest_cached_ms, report.fastest_live_ms) == (1, 1800)
    assert "slowest cache-served call took 1 ms" in "\n".join(isolation.markdown(report))
