"""BM25 index tests (spec §5.4) on a tiny hand-written corpus."""

import math

import numpy as np
import pytest

from metacompass.retrieval.bm25 import BM25Index

IDS = ["D1", "D2", "D3", "D4"]
TEXTS = [
    "Service retention by dealer. Share of owners who come back for maintenance.",
    "Parts fill rate by warehouse. Order lines shipped complete from stock.",
    "fct_returns: parts returns with reason code and credit amount.",
    "Gross margin % (GM%) across vehicles, parts and service.",
]


@pytest.fixture(scope="module")
def index() -> BM25Index:
    return BM25Index(IDS, TEXTS)


@pytest.mark.parametrize(
    ("query", "expected_first"),
    [
        ("service retention", "D1"),
        ("fill rate", "D2"),
        ("fct_returns", "D3"),
        ("returns", "D3"),
        ("GM%", "D4"),
        ("gm", "D4"),
    ],
)
def test_expected_first_result(index, query, expected_first):
    assert index.top(query, n=4)[0][0] == expected_first


def test_scores_are_aligned_with_document_ids(index):
    scores = index.scores("warehouse stock")
    assert scores.shape == (4,)
    assert int(np.argmax(scores)) == IDS.index("D2")


def test_only_matching_documents_are_candidates(index):
    hits = index.top("warehouse", n=10)
    assert [doc_id for doc_id, _ in hits] == ["D2"]
    assert index.top("nothing here matches", n=10) == []
    assert index.top("the of and", n=10) == []  # stop words only


def test_ties_break_by_document_id():
    tied = BM25Index(["B", "A", "C"], ["apple pie", "apple pie", "banana"])
    assert [doc_id for doc_id, _ in tied.top("apple", n=3)] == ["A", "B"]


def test_mask_removes_documents_before_ranking(index):
    mask = np.array([True, False, True, True])
    hits = index.top("parts", n=10, mask=mask)
    assert "D2" not in [doc_id for doc_id, _ in hits]
    assert {doc_id for doc_id, _ in hits} == {"D3", "D4"}


def test_score_matches_okapi_formula():
    # Three one-word documents, so idf is positive and the formula is easy to redo by hand.
    k1, b = 1.5, 0.75
    small = BM25Index(["X", "Y", "Z"], ["alpha", "beta", "gamma"], k1=k1, b=b)
    idf = math.log((3 - 1 + 0.5) / (1 + 0.5))
    expected = idf * (1 * (k1 + 1)) / (1 + k1 * (1 - b + b * 1 / 1))
    assert small.scores("alpha")[0] == pytest.approx(expected)


def test_rejects_mismatched_inputs():
    with pytest.raises(ValueError):
        BM25Index(["A", "B"], ["only one text"])
