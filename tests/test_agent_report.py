"""The agent sections of results.md (spec §9.7, §9.11), rendered from made-up raw lines."""

import pytest

import agent_report
import report

ITEMS = [
    {"id": "L1-001", "category": "L1", "subtype": "exact", "question": "What is RPT-0001?",
     "gold": {"answer_ids": ["RPT-0001"], "forbidden_ids": [], "should_abstain": False}},
    {"id": "L1-002", "category": "L1", "subtype": "paraphrase", "question": "Dealer sales?",
     "gold": {"answer_ids": ["RPT-0002"], "forbidden_ids": [], "should_abstain": False}},
    {"id": "L6-001", "category": "L6", "subtype": "salary", "question": "Salary of X?",
     "gold": {"answer_ids": [], "forbidden_ids": [], "should_abstain": True}},
]  # fmt: skip


def line(item_id, correct, *, config="A0", repeat=1, abstained=False, stripped=(), tools=1,
         tool_errors=0, cost=0.01, latency=100, stopped="final", set_name="test"):  # fmt: skip
    category = item_id.split("-")[0]
    steps = [{"kind": "llm", "summary": "answer"}]
    steps += [{"kind": "tool", "summary": "error: NOT_FOUND"}] * tool_errors
    steps += [{"kind": "tool", "summary": '{"hits":[]}'}] * (tools - tool_errors)
    return {
        "set": set_name, "config": config, "repeat": repeat, "item_id": item_id,
        "category": category, "subtype": "x", "incomplete": False,
        "model": "test-model", "prompt_version": "v1", "git_sha": "abc1234", "date": "2026-09-19",
        "score": {"correct": correct},
        "result": {
            "answer": {"answer": "...", "answer_ids": [], "evidence_ids": [], "abstained": abstained},
            "stripped_ids": list(stripped), "tool_calls": tools, "steps": steps,
            "cost_usd": cost, "latency_ms": latency, "stopped_reason": stopped,
        },
    }  # fmt: skip


def full_runs():
    # L1-001 right in all three repeats, L1-002 wrong in repeat 2; L6 abstains correctly.
    return [
        line("L1-001", True, repeat=1), line("L1-002", True, repeat=1),
        line("L6-001", True, repeat=1, abstained=True),
        line("L1-001", True, repeat=2), line("L1-002", False, repeat=2, stripped=["EMP-999"]),
        line("L6-001", True, repeat=2, abstained=True),
        line("L1-001", True, repeat=3), line("L1-002", True, repeat=3, latency=900),
        line("L6-001", True, repeat=3, abstained=True, tool_errors=1),
    ]  # fmt: skip


def test_full_system_accuracy_is_mean_and_std_over_repeats():
    text = "\n".join(agent_report.full_system_section(full_runs(), ITEMS))
    # L1 per repeat: 1.0, 0.5, 1.0 -> mean 0.83, sample std 0.29
    assert "| L1 | 2 | 0.83 ± 0.29 |" in text
    assert "| L6 | 1 | 1.00 ± 0.00 |" in text
    assert "| Overall | 3 | 0.89 ± 0.19 |" in text


def test_bootstrap_interval_is_seeded_and_brackets_the_mean():
    per_question = [1.0, 1.0, 0.0, 1.0, 0.5]
    low, high = agent_report.bootstrap_ci(per_question)
    assert (low, high) == agent_report.bootstrap_ci(per_question)
    assert 0.0 <= low <= sum(per_question) / 5 <= high <= 1.0


def test_abstention_precision_recall_and_false_rate():
    lines = [
        line("L6-001", True, abstained=True),
        line("L1-001", False, abstained=True),  # abstained on an answerable question
        line("L1-002", True),
    ]
    precision, recall, false_rate = agent_report.abstention(lines, {i["id"]: i for i in ITEMS})
    assert (precision, recall, false_rate) == (0.5, 1.0, 0.5)


def test_operational_numbers():
    ops = agent_report.operational(full_runs())
    assert ops["tools_per_q"] == pytest.approx(1.0)
    assert ops["tool_error_rate"] == pytest.approx(1 / 9)
    assert ops["p95_ms"] == 900
    assert ops["cost_per_q"] == pytest.approx(0.01)
    assert ops["stop_reasons"] == {"final": 9}
    assert ops["fabricated_rate"] == pytest.approx(1 / 9)


def test_ablation_table_marks_what_did_not_run():
    runs = full_runs() + [line("L6-001", False, config="A4", repeat=r) for r in (1, 2)]
    text = "\n".join(agent_report.ablation_section(runs, ITEMS))
    header, separator = text.splitlines()[:2]
    assert header.count("|") == separator.count("|")  # a valid markdown table
    a0 = next(row for row in text.splitlines() if row.startswith("| A0 full"))
    a1 = next(row for row in text.splitlines() if row.startswith("| A1 dense-only"))
    a4 = next(row for row in text.splitlines() if row.startswith("| A4 no-abstain"))
    assert "0.83" in a0
    assert set(a1.strip("|").split("|")[1:]) == {" — "}  # never ran
    assert a4.split("|")[2].strip() == "—"  # A4 ran, but not on L1
    assert a4.split("|")[7].strip() == "0.00"  # L6 column


def test_a5_note_explains_the_tool_budget(capsys):
    runs = full_runs() + [
        line("L1-001", False, config="A5", repeat=1, stopped="tool_budget"),
        line("L1-002", False, config="A5", repeat=1, stopped="final"),
    ]
    text = "\n".join(agent_report.ablation_section(runs, ITEMS))
    assert "A5" in text and "tool budget" in text and "50%" in text


def test_error_analysis_picks_failures_from_the_raw_lines():
    text = "\n".join(agent_report.error_analysis(full_runs(), ITEMS))
    assert "L1-002" in text  # the one wrong answer, with its repeat and what went wrong
    assert "invented IDs removed" in text
    assert "L1-001" not in text


def test_page_without_agent_runs_says_not_run():
    page = report.render_results(None)
    assert page.count(report.NOT_RUN) >= 5


def test_page_with_a_single_dry_run_has_every_section_filled():
    # Phase 5 task 11: a one-repeat dev run must fill every agent section; std needs two.
    lines = [line(i["id"], i["category"] == "L6", abstained=i["category"] == "L6", set_name="dev")
             for i in ITEMS]  # fmt: skip
    page = report.render_results(None, runs=lines, items=ITEMS, set_name="dev")
    agent_part = page.split("## Agent")[1]
    assert report.NOT_RUN not in agent_part.split("## Ablation")[0]
    assert "| L1 | 2 | 0.00 (1 repeat) |" in agent_part
    assert "`test-model`" in page and "`v1`" in page
