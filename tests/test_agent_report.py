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
    assert a4.split("|")[7].strip() == "0.00 ▼"  # L6: 1.00 in A0, the CIs do not overlap
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


# ---------------------------------------------------------------------- diagnostics


DIAG_ITEMS = [
    {"id": "L1-001", "category": "L1", "subtype": "exact", "question": "q",
     "gold_spec": {"type": "asset_by_description", "target_id": "RPT-0001"},
     "gold": {"answer_ids": ["RPT-0001"], "forbidden_ids": [], "should_abstain": False}},
    {"id": "L3-001", "category": "L3", "subtype": "report_upstream", "question": "q",
     "gold_spec": {"type": "upstream_tables", "node_id": "RPT-0009", "depth": 2},
     "gold": {"answer_ids": ["TBL-001", "TBL-002"], "forbidden_ids": [], "should_abstain": False}},
    {"id": "L4-001", "category": "L4", "subtype": "topic", "question": "q",
     "gold_spec": {"type": "similar_requests", "topic_key": "k"},
     "gold": {"answer_ids": ["REQ-0001", "REQ-0002"], "forbidden_ids": [], "should_abstain": False}},
    {"id": "L5-001", "category": "L5", "subtype": "individual", "question": "q",
     "gold_spec": {"type": "impact_notify", "table_id": "TBL-005"},
     "gold": {"answer_ids": ["EMP-001", "EMP-002"], "forbidden_ids": [], "should_abstain": False}},
]  # fmt: skip


def diag_line(item_id, answer_ids, correct, calls=(), repeat=1):
    base = line(item_id, correct, repeat=repeat)
    base["result"]["answer"]["answer_ids"] = list(answer_ids)
    base["result"]["steps"] = [
        {"kind": "tool", "name": name, "arguments": args, "summary": "{}"} for name, args in calls
    ]
    return base


def test_over_inclusive_answers_are_told_apart_from_wrong_ones():
    lines = [
        diag_line("L1-001", ["RPT-0001"], True),
        diag_line("L1-001", ["RPT-0001", "RPT-0002"], True, repeat=2),  # right, plus one more
        diag_line("L1-001", ["RPT-0003"], False, repeat=3),  # simply wrong
    ]
    diagnostics = agent_report.diagnostics(lines, DIAG_ITEMS)
    assert diagnostics["L1"]["over_inclusive_rate"] == pytest.approx(1 / 3)


def test_tool_arguments_separate_reasoning_from_transcription():
    right = ("trace_lineage", {"node_id": "RPT-0009", "direction": "upstream", "depth": 2})
    wrong_depth = ("trace_lineage", {"node_id": "RPT-0009", "direction": "upstream", "depth": 3})
    lines = [
        diag_line("L3-001", ["TBL-001"], False, [right]),  # right call, lost in the answer
        diag_line("L3-001", ["TBL-001", "TBL-002"], True, [right], repeat=2),
        diag_line("L3-001", ["TBL-001"], False, [wrong_depth], repeat=3),  # wrong call
        diag_line("L5-001", ["EMP-001", "EMP-002"], True, [("impact_analysis", {"table_id": "TBL-005"})]),
    ]  # fmt: skip
    d = agent_report.diagnostics(lines, DIAG_ITEMS)
    assert d["L3"]["tool_args_correct"] == pytest.approx(2 / 3)
    assert d["L3"]["accuracy_when_args_correct"] == pytest.approx(1 / 2)
    assert d["L5"]["tool_args_correct"] == 1.0


def test_in_cluster_precision_counts_the_share_of_right_requests():
    lines = [
        diag_line("L4-001", ["REQ-0001", "REQ-0009"], True),  # half right
        diag_line("L4-001", ["REQ-0001", "REQ-0002"], True, repeat=2),  # all right
    ]
    assert agent_report.diagnostics(lines, DIAG_ITEMS)["L4"][
        "in_cluster_precision"
    ] == pytest.approx(0.75)


def test_diagnostics_section_says_it_is_not_the_score():
    lines = [diag_line("L1-001", ["RPT-0001"], True)]
    text = "\n".join(agent_report.diagnostics_section(lines, DIAG_ITEMS))
    assert "do not change the scores" in text
    assert "| L1 |" in text


# ---------------------------------------------------------------------- pre-registered effects


def test_an_ablation_effect_needs_three_points_and_twice_the_noise():
    # Pre-registered: overall difference >= 0.03 AND > 2 x A0 repeat std. A0 overall here is
    # 0.89 ± 0.19, so no one-run difference short of 0.38 counts.
    runs = full_runs() + [line(i, False, config="A2") for i in ("L1-001", "L1-002", "L6-001")]
    text = "\n".join(agent_report.ablation_section(runs, ITEMS))
    a2 = next(row for row in text.splitlines() if row.startswith("| A2 bm25-only"))
    assert "-0.89 ▼" in a2  # 0.89 > 2 x 0.19 = 0.38 and >= 0.03
    assert "effect" in text  # the legend names the rule


def test_the_pre_registration_cannot_change_after_the_fact():
    text = "\n".join(report.PREREGISTERED)
    assert "A4" in text and "prompt" in text
    assert "3 points" in text and "2 times" in text
    assert report.preregistration_digest() == report.PREREGISTERED_DIGEST


def test_page_names_the_api_version_and_the_prompt_versions():
    lines = [dict(line(i["id"], True), api_version="v1beta") for i in ITEMS]
    page = report.render_results(None, runs=lines, items=ITEMS)
    assert "API `v1beta`" in page
    assert "v2 = v1 + schema/payload simplification" in page


def test_input_section_shows_real_tokens_next_to_the_character_estimate():
    composition = {
        "v2": {"mean_llm_turns": 2.6, "mean_input_chars_per_question": 21000,
               "mean_input_tokens_per_question_estimate": 5250,
               "share_by_source": {"system": 0.25, "tools": 0.58, "tool_results": 0.15, "other": 0.02}},
    }  # fmt: skip
    tokens = {"versions": {"v2": {"tokens_per_question": 5458.4,
                                  "share_by_source": {"system": 0.243, "tools": 0.571,
                                                      "tool_results": 0.163, "other": 0.024}}}}  # fmt: skip
    text = "\n".join(report.composition_section(composition, tokens))
    assert "| v2 | 2.6 | 21,000 | 5,250 | 5,458 |" in text


def test_the_pre_registration_states_how_the_model_was_chosen():
    # D25's free tier cannot carry the plan on a Flash model; the choice is measured, and the
    # rule for it belongs in the report before the candidates run.
    text = "\n".join(report.PREREGISTERED)
    assert "parse_failure" in text and "dev set" in text
    assert "15 days" in text  # a model that cannot finish the plan is not a candidate


MODEL_CHOICE = {
    "rule": "primary: answers lost to parse_failure, tool_budget or llm_error; ...",
    "chosen": "gemini-3.5-flash-lite",
    "reason": "gemini-3.5-flash-lite lost 0 answers and scored 0.70; gemini-3.8-flash was not a candidate: 20 requests a day means 120 days.",
    "candidates": [
        {"model": "gemini-3.5-flash-lite", "lite": True, "answered": 30, "planned": 30,
         "unanswered": 0, "accuracy": 0.7, "machinery_losses": 0,
         "stop_reasons": {"final": 30}, "calls_per_answer": 3.4,
         "input_tokens_per_answer": 21000.0, "rpd": 500, "observed_rpd": None,
         "plan_answers": 665, "plan_calls": 2261, "plan_days": 5, "feasible": True},
        {"model": "gemini-3.8-flash", "lite": False, "answered": 6, "planned": 30,
         "unanswered": 24, "accuracy": 0.5, "machinery_losses": 24,
         "stop_reasons": {"final": 6}, "calls_per_answer": 3.5,
         "input_tokens_per_answer": 22000.0, "rpd": 20, "observed_rpd": 20,
         "plan_answers": 665, "plan_calls": 2328, "plan_days": 117, "feasible": False},
    ],
}  # fmt: skip


def test_model_choice_section_shows_the_rule_the_candidates_and_the_decision():
    text = "\n".join(report.model_choice_section(MODEL_CHOICE))
    assert "primary" in text  # the pre-registered rule is repeated where the numbers are
    assert "| gemini-3.5-flash-lite | 30/30 | 0 | 0.70 | 3.4 | 500 | 5 | chosen |" in text
    assert "| gemini-3.8-flash | 6/30 | 24 | 0.50 | 3.5 | 20 | 117 | not a candidate |" in text
    assert "120 days" in text  # the reason, as written by model_choice.py
    # A run the quota stopped early has an accuracy over a handful of questions; say so.
    assert "gemini-3.8-flash reached 6 of 30" in text


def test_a_page_without_a_model_choice_says_not_run():
    page = report.render_results(None)
    assert "Model choice" in page


def test_diagnostics_count_wrong_answers_whose_gold_never_reached_the_model():
    # The dev pilot's remaining failures were retrieval, not reasoning: the gold IDs were in
    # no tool result, so no prompt could have fixed them. The report has to separate the two.
    seen = line("L1-001", False)
    seen["result"]["steps"] = [{"kind": "tool", "summary": '{"hits":[{"id":"RPT-0001"}]}'}]
    unseen = line("L1-002", False)
    unseen["result"]["steps"] = [{"kind": "tool", "summary": '{"hits":[{"id":"RPT-9999"}]}'}]
    rows = agent_report.diagnostics([seen, unseen], ITEMS)
    assert rows["L1"]["wrong_with_gold_unseen"] == 1
    assert rows["L1"]["wrong_answers"] == 2
    text = "\n".join(agent_report.diagnostics_section([seen, unseen], ITEMS))
    assert "Gold never retrieved" in text
    assert "| L1 |" in text and "1 of 2" in text
