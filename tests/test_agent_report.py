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
            "input_tokens": 100, "output_tokens": 20,
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


def test_answers_the_run_has_not_reached_yet_are_counted_from_the_plan():
    # D25: a run that the daily quota stopped is resumed later; until then the page says so.
    lines = full_runs()[:-1]  # repeat 3 of L6-001 not answered yet
    text = "\n".join(agent_report.full_system_section(lines, ITEMS))
    l6 = next(row for row in text.splitlines() if row.startswith("| L6 |"))
    overall = next(row for row in text.splitlines() if row.startswith("| Overall |"))
    assert l6.endswith("| 1 not answered yet |")
    assert overall.endswith("| 1 not answered yet |")


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
    assert ops["tokens_per_q"] == pytest.approx(120)
    assert ops["stop_reasons"] == {"final": 9}
    assert ops["fabricated_rate"] == pytest.approx(1 / 9)


def test_ablation_table_marks_what_did_not_run():
    runs = full_runs() + [line("L6-001", False, config="A4", repeat=1)]
    text = "\n".join(agent_report.ablation_section(runs, ITEMS))
    header, separator = text.splitlines()[:2]
    assert header.count("|") == separator.count("|")  # a valid markdown table
    a0 = next(row for row in text.splitlines() if row.startswith("| A0 full"))
    a1 = next(row for row in text.splitlines() if row.startswith("| A1 dense-only"))
    a4 = next(row for row in text.splitlines() if row.startswith("| A4 no-abstain"))
    assert "0.83" in a0
    assert set(a1.strip("|").split("|")[1:]) == {" — "}  # never ran
    assert a4.split("|")[2].strip() == "—"  # A4 ran, but not on L1
    assert a4.split("|")[7].strip() == "0.00"  # L6 column: 1.00 in A0, a real drop
    assert "Tokens/q" in header and "$/q" not in header


def test_ablation_differences_inside_the_full_systems_noise_are_marked():
    # D25: ablations run once, so the A0 repeat-to-repeat std is the yardstick. A0 on L1 is
    # 0.83 ± 0.29; an ablation at 1.00 differs by 0.17, inside that spread.
    runs = full_runs() + [line("L1-001", True, config="A1"), line("L1-002", True, config="A1")]
    text = "\n".join(agent_report.ablation_section(runs, ITEMS))
    a1 = next(row for row in text.splitlines() if row.startswith("| A1 dense-only"))
    cells = [c.strip() for c in a1.split("|")]
    assert cells[2] == "1.00 ≈"  # L1
    assert "+0.11 ≈" in cells  # overall 1.00 against A0's 0.89 ± 0.19
    assert "≈" in text.split("\n\n")[-1]  # the legend explains the mark


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


QUOTA = {
    "limits": {"rpm": 10, "rpd": 250, "tpm": 250000},
    "days": {"2026-09-18": {"requests": 240, "tokens": 900000},
             "2026-09-19": {"requests": 40, "tokens": 150000}},
}  # fmt: skip


def test_run_plan_shows_the_free_tier_and_how_far_the_run_got():
    text = "\n".join(agent_report.run_plan_section(full_runs(), ITEMS, QUOTA))
    assert "| A0 full | 3 | all | 9 | 9 |" in text
    assert "| A3 llm-walks-chain | 1 | L2, L5, MX | 0 | 0 |" in text
    assert "test-model" in text and "free tier" in text
    assert "10 requests/min" in text and "250 requests/day" in text
    assert "280 requests over 2 days" in text


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
    assert "## Run plan and free-tier limits" in page
