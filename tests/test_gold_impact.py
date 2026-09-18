"""The independent impact gold (eval/gold.py) against values worked out by hand on the
mini fixture. The tool tests compare impact_analysis with this gold on every generated
table, so the gold itself must be right first.
"""

from gold import current_contact, impact_notify, load_raw


def test_current_contact_walks_the_chain_like_the_spec_says(mini_dir):
    raw = load_raw(mini_dir)
    assert current_contact(raw, "RPT-0001") == ("EMP-004", True)  # active owner
    assert current_contact(raw, "RPT-0002") == ("EMP-004", True)  # S1: 008 -> 004
    assert current_contact(raw, "RPT-0006") == ("EMP-004", True)  # C3: 006 -> 007 -> 008 -> 004
    assert current_contact(raw, "RPT-0007") == ("EMP-002", False)  # C4: Sales head fallback


def test_impact_notify_on_the_mini_fixture(mini_dir):
    gold = impact_notify(load_raw(mini_dir), "TBL-004")
    assert gold["tables"] == ["TBL-005", "TBL-006"]
    # RPT-0004 is deprecated: it is affected but nobody is told about it (D10).
    assert gold["reports"] == [
        "RPT-0001",
        "RPT-0002",
        "RPT-0004",
        "RPT-0005",
        "RPT-0006",
        "RPT-0007",
    ]
    assert gold["metrics"] == ["MET-001", "MET-002"]
    assert gold["people"] == {
        "EMP-004": {"usage": 190, "reports": ["RPT-0001", "RPT-0002", "RPT-0006"], "metrics": ["MET-001"]},
        "EMP-003": {"usage": 60, "reports": ["RPT-0005"], "metrics": []},
        "EMP-002": {"usage": 5, "reports": ["RPT-0007"], "metrics": ["MET-002"]},
    }  # fmt: skip


def test_impact_notify_of_a_table_nothing_reads(mini_dir):
    gold = impact_notify(load_raw(mini_dir), "TBL-008")
    assert (gold["tables"], gold["reports"], gold["metrics"], gold["people"]) == ([], [], [], {})
