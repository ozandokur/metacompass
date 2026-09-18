"""Tokenizer rules from spec §5.3, as an input -> expected tokens table."""

import pytest

from metacompass.retrieval.tokenize import STOPWORDS, tokenize

CASES = [
    # rule 1: lower-case
    ("Service Retention", ["service", "retention"]),
    # rule 2 + 3: "_" and "-" stay inside a token, and the parts are added after it
    ("dim_customer", ["dim_customer", "dim", "customer"]),
    ("RPT-0142", ["rpt-0142", "rpt", "0142"]),
    (
        "Which tables feed fct_vehicle_sales?",
        ["tables", "feed", "fct_vehicle_sales", "fct", "vehicle", "sales"],
    ),
    ("port-to-dealer transit", ["port-to-dealer", "port", "dealer", "transit"]),
    # rule 4: "%" is kept, attached or on its own
    ("GM%", ["gm%", "gm"]),
    ("Gross Margin %", ["gross", "margin", "%"]),
    # rule 5: stop words are removed, including from compound parts
    ("the owner of the report", ["owner", "report"]),
    ("Who owns RPT-0001 and what is it for?", ["owns", "rpt-0001", "rpt", "0001", "it"]),
    # rule 6: no stemming
    ("returns returned returning", ["returns", "returned", "returning"]),
    # punctuation splits tokens; stray separators are not tokens
    ("P&L - Monthly (Extended)", ["p", "l", "monthly", "extended"]),
    ("Dealer Sales Performance – Regional", ["dealer", "sales", "performance", "regional"]),
    ("", []),
    ("   ...   ", []),
]


@pytest.mark.parametrize(("text", "expected"), CASES, ids=[c[0] or "<empty>" for c in CASES])
def test_tokenize(text, expected):
    assert tokenize(text) == expected


def test_stopword_list_is_the_spec_list():
    spec_list = "the a an of for to in on and or is are which what who by with"
    assert frozenset(spec_list.split(" ")) == STOPWORDS


def test_tokenize_is_deterministic_and_keeps_duplicates():
    # Term frequency matters to BM25, so repeated words stay repeated.
    assert tokenize("parts parts dim_part") == ["parts", "parts", "dim_part", "dim", "part"]
