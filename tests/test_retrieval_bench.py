"""Metric helpers of the retrieval benchmark (spec §5.8) and the results page (spec §9.11)."""

import pytest

import report
import run_retrieval_bench as bench


def test_rank_of():
    assert bench.rank_of("B", ["A", "B", "C"]) == 2
    assert bench.rank_of("Z", ["A", "B"]) is None


def test_recall_and_mrr():
    ranks = [1, 3, None, 6]
    assert bench.recall_at(ranks, 1) == pytest.approx(1 / 4)
    assert bench.recall_at(ranks, 5) == pytest.approx(2 / 4)
    assert bench.mean_reciprocal_rank(ranks) == pytest.approx((1 + 1 / 3 + 0 + 1 / 6) / 4)
    assert bench.recall_at([], 1) == 0.0


def test_macro_f1_by_hand():
    # strong class: tp=2, fp=1, fn=1 -> F1 = 2/3; weak class: tp=1, fp=1, fn=1 -> F1 = 1/2
    truth = ["strong", "strong", "strong", "weak", "weak"]
    pred = ["strong", "strong", "weak", "strong", "weak"]
    assert bench.macro_f1(truth, pred) == pytest.approx((2 / 3 + 1 / 2) / 2)


def test_macro_f1_handles_an_empty_class():
    assert bench.macro_f1(["strong", "strong"], ["strong", "strong"]) == pytest.approx(0.5)


def _record(kind, cosine, exact=False):
    return {"type": kind, "top_dense_cosine": cosine, "exact_match": exact}


def test_tau_sweep_uses_exact_match_or_cosine():
    records = [_record("P", 0.60), _record("E", 0.10, exact=True), _record("N", 0.40)]
    sweep = {row["tau"]: row for row in bench.tau_sweep(records, [0.35, 0.50, 0.65])}
    assert sweep[0.35]["weak_rate_negative"] == 0.0  # the negative looks strong at 0.35
    assert sweep[0.50]["weak_rate_negative"] == 1.0
    assert sweep[0.50]["strong_rate_positive"] == 1.0
    assert sweep[0.65]["strong_rate_positive"] == pytest.approx(0.5)  # only the exact match
    assert sweep[0.50]["macro_f1"] == pytest.approx(1.0)


def test_choose_tau_takes_the_middle_of_the_best_plateau():
    sweep = [
        {"tau": 0.30, "macro_f1": 0.5},
        {"tau": 0.35, "macro_f1": 0.8},
        {"tau": 0.40, "macro_f1": 0.8},
        {"tau": 0.45, "macro_f1": 0.8},
        {"tau": 0.50, "macro_f1": 0.7},
    ]
    assert bench.choose_tau(sweep) == 0.40
    assert bench.choose_tau(sweep[:3]) == 0.35  # even plateau: lower middle


def test_tau_grid_is_the_spec_grid():
    assert bench.TAU_GRID == [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]


def test_results_page_marks_unrun_sections():
    page = report.render_results(None)
    assert "# Evaluation Results" in page
    assert "⏳ not run" in page
    assert "All data is synthetic" in page


def _fake_run(name, mrr, kind="cosine", equals_exact=True, topic=(0.2, 0.5, 0.4), overlap=0.0):
    modes = {}
    for i, mode in enumerate(("bm25", "dense", "hybrid")):
        modes[mode] = {
            "E": {"recall@1": 1.0, "recall@5": 1.0, "mrr": 1.0, "n": 15},
            "P": {"recall@1": 0.1, "recall@5": 0.2, "mrr": 0.2, "n": 15, "topic_hit@5": topic[i]},
            "D": {"recall@1": 0.7, "recall@5": 1.0, "mrr": 0.8, "n": 15, "pair_coverage@5": 1.0,
                  "forbidden_above_target": 0.3},
            "all": {"recall@1": 0.6, "recall@5": 0.7, "mrr": mrr if mode == "hybrid" else 0.5, "n": 45},
            "E_recall@1_by_subtype": {"table name": 1.0, "metric acronym": 1.0,
                                      "report ID": 1.0 if mode == "bm25" else 0.0},
        }  # fmt: skip
    per_query = [
        {"type": "P", "exact_match": False, "top_dense_cosine": 0.5, "dense_z": 5.0, "description_overlap": overlap},
        {"type": "N", "exact_match": False, "top_dense_cosine": 0.5, "dense_z": 1.0},
    ]  # fmt: skip
    return {
        "meta": {"embedding_model": name, "data_seed": 42, "git_sha": "abc", "run_date": "2026-09-18",
                 "n_queries": {"E": 15, "P": 15, "D": 15, "N": 15}, "top_k": 10, "label": ""},
        "modes": modes,
        "sweeps": {"cosine": [{"tau": 0.65, "macro_f1": 0.7, "strong_rate_positive": 0.6, "weak_rate_negative": 1.0}],
                   "z": [{"tau": 4.25, "macro_f1": 0.75, "strong_rate_positive": 0.7, "weak_rate_negative": 1.0}]},
        "signal": {"kind": kind, "threshold": 4.25 if kind == "z" else 0.65, "macro_f1": 0.75 if kind == "z" else 0.7,
                   "positives_strong_rate": 0.7, "negatives_weak_rate": 1.0, "equals_exact_match": equals_exact,
                   "best": {"cosine": {"threshold": 0.65, "macro_f1": 0.7}, "z": {"threshold": 4.25, "macro_f1": 0.75}}},
        "leakage": {"p_description_overlap_mean": overlap, "p_queries_over_limit": 9 if overlap else 0, "limit": 0.2},
        "per_query": per_query,
    }  # fmt: skip


def _fake_retrieval():
    v1_original = {
        "chosen_tau": 0.65,
        "negatives_weak_rate": 1.0,
        "meta": {"git_sha": "1d37885", "run_date": "2026-09-18"},
        "modes": {
            mode: {
                t: {"recall@1": 0.5, "recall@5": 1.0, "mrr": 0.75} for t in ("E", "P", "D", "all")
            }
            for mode in ("bm25", "dense", "hybrid")
        },
    }
    return {
        "models": {
            "all-MiniLM-L6-v2": _fake_run("all-MiniLM-L6-v2", 0.54),
            "bge-small-en-v1.5": _fake_run("bge-small-en-v1.5", 0.58, kind="z", equals_exact=False),
        },
        "v1": v1_original,
        "v1_rescored": _fake_run("all-MiniLM-L6-v2", 0.61, topic=(0.73, 0.53, 0.73), overlap=0.35),
    }


def test_results_page_headline_uses_the_ab_winner():
    page = report.render_results(_fake_retrieval())
    assert "bge-small-en-v1.5" in page.split("### Headline")[1].splitlines()[0]
    assert "| hybrid | 1.00 | 1.00 | 0.20 | 0.40 | 1.00 | 0.58 |" in page


def test_results_page_shows_both_models_and_the_rule():
    page = report.render_results(_fake_retrieval())
    assert "| all-MiniLM-L6-v2 | 0.54 |" in page
    assert "| bge-small-en-v1.5 | 0.58 |" in page
    assert "pre-registered" in page


def test_results_page_keeps_the_original_v1_table_and_explains_the_change():
    page = report.render_results(_fake_retrieval())
    assert (
        "| hybrid | 0.50 | 1.00 | 0.50 | 1.00 | 0.50 | 1.00 | 0.75 | 100% |" in page
    )  # verbatim v1
    assert "35%" in page  # mean description overlap of the leaky set, computed not typed


def test_results_page_flags_a_signal_that_is_only_exact_match():
    retrieval = _fake_retrieval()
    retrieval["models"]["bge-small-en-v1.5"]["signal"]["equals_exact_match"] = True
    page = report.render_results(retrieval)
    assert "A4 ablation therefore measures only the prompt" in page


def test_results_page_names_the_rrf_id_property():
    page = report.render_results(_fake_retrieval())
    assert "Known property" in page and "report ID" in page


# ---------------------------------------------------------------- spec update 2026-09-18


def test_topic_hit_counts_any_report_of_the_right_subject():
    subjects = {"R1": "retention", "R2": "retention", "R3": "margin"}
    assert bench.topic_hit("R1", ["R3", "R2"], subjects, k=5) is True  # a sibling counts
    assert bench.topic_hit("R1", ["R3"], subjects, k=5) is False
    assert bench.topic_hit("R1", ["R3", "R3", "R3", "R3", "R3", "R2"], subjects, k=5) is False


def test_pair_coverage_needs_both_members_in_the_top_k():
    assert bench.pair_covered("A", "B", ["X", "B", "A"], k=5) is True
    assert bench.pair_covered("A", "B", ["A", "X"], k=5) is False
    assert bench.pair_covered("A", "B", ["X", "X", "X", "X", "X", "A", "B"], k=5) is False


def test_z_grid_is_fixed_before_looking_at_data():
    assert bench.TAU_Z_GRID[0] == 0.5 and bench.TAU_Z_GRID[-1] == 6.0
    assert len(bench.TAU_Z_GRID) == 23


def test_sweep_works_on_either_signal_field():
    records = [
        {"type": "P", "top_dense_cosine": 0.4, "dense_z": 4.0, "exact_match": False},
        {"type": "N", "top_dense_cosine": 0.5, "dense_z": 2.0, "exact_match": False},
    ]
    cosine = bench.tau_sweep(records, [0.45], field="top_dense_cosine")[0]
    z = bench.tau_sweep(records, [3.0], field="dense_z")[0]
    assert cosine["macro_f1"] == 0.0  # cosine gets both wrong
    assert z["macro_f1"] == 1.0  # z separates them


def test_choose_signal_prefers_the_better_variant_and_keeps_cosine_on_a_tie():
    cosine = [{"tau": 0.6, "macro_f1": 0.70}]
    z_better = [{"tau": 3.0, "macro_f1": 0.80}]
    z_equal = [{"tau": 3.0, "macro_f1": 0.70}]
    assert bench.choose_signal(cosine, z_better) == ("z", 3.0, 0.80)
    assert bench.choose_signal(cosine, z_equal) == ("cosine", 0.6, 0.70)


def test_signal_equals_exact_match_detection():
    records = [
        {"type": "E", "top_dense_cosine": 0.2, "dense_z": 1.0, "exact_match": True},
        {"type": "P", "top_dense_cosine": 0.4, "dense_z": 2.0, "exact_match": False},
    ]
    assert bench.signal_equals_exact_match(records, "cosine", 0.5) is True
    assert bench.signal_equals_exact_match(records, "cosine", 0.3) is False
    assert bench.signal_equals_exact_match(records, "z", 1.5) is False


def _model_result(mrr, f1):
    return {"modes": {"hybrid": {"all": {"mrr": mrr}}}, "signal": {"macro_f1": f1}}


def test_choose_model_follows_the_preregistered_rule():
    incumbent = "all-MiniLM-L6-v2"
    runs = {incumbent: _model_result(0.60, 0.70), "bge-small-en-v1.5": _model_result(0.65, 0.60)}
    assert bench.choose_model(runs) == "bge-small-en-v1.5"  # MRR gap >= 0.02 decides
    runs = {incumbent: _model_result(0.60, 0.70), "bge-small-en-v1.5": _model_result(0.61, 0.80)}
    assert bench.choose_model(runs) == "bge-small-en-v1.5"  # close MRR: signal F1 decides
    runs = {incumbent: _model_result(0.60, 0.70), "bge-small-en-v1.5": _model_result(0.61, 0.702)}
    assert bench.choose_model(runs) == incumbent  # still a tie: keep the incumbent
