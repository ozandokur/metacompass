"""Deep links into the demo: a URL can name a prepared question, open its trace and a record.

They make a state shareable ("look at this answer") and let a screenshot of the demo be taken
without clicking through it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import streamlit_app as app

LABELS = ["Lookup", "Impact", "Unanswerable", "Mixed: data behind a metric"]


def test_a_label_becomes_a_slug():
    assert app.slug("Mixed: data behind a metric") == "mixed-data-behind-a-metric"
    assert app.slug("Past work") == "past-work"


def test_a_question_slug_selects_that_prepared_answer():
    state = app.deep_link_state({"q": "impact"}, LABELS)
    assert state["shown"] == {"kind": "prepared", "number": 1}


def test_an_unknown_question_changes_nothing():
    assert app.deep_link_state({"q": "nope"}, LABELS) == {}


def test_a_record_and_an_open_trace_come_from_the_url():
    state = app.deep_link_state({"q": "impact", "record": "EMP-031", "trace": "open"}, LABELS)
    assert state["record"] == "EMP-031"
    assert state["trace_open"] is True
    assert app.deep_link_state({"q": "impact"}, LABELS).get("trace_open") is None
