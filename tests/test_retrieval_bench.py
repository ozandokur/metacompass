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


def test_results_page_shows_the_retrieval_table():
    fake = {
        "meta": {"embedding_model": "m", "data_seed": 42, "chosen_tau": 0.5, "git_sha": "abc"},
        "chosen_tau": 0.5,
        "modes": {
            mode: {
                t: {"recall@1": 0.5, "recall@5": 1.0, "mrr": 0.75, "n": 2}
                for t in ("E", "P", "D", "all")
            }
            for mode in ("bm25", "dense", "hybrid")
        },
        "negatives_weak_rate": 0.8,
        "tau_sweep": [
            {"tau": 0.5, "macro_f1": 0.9, "strong_rate_positive": 1.0, "weak_rate_negative": 0.8}
        ],
    }
    page = report.render_results(fake)
    assert "| hybrid | 0.50 | 1.00 | 0.50 | 1.00 | 0.50 | 1.00 | 0.75 | 80% |" in page
    assert "τ" in page
