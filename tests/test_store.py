"""Tests for MetadataStore: CSV loading, typed rows and lookup helpers (spec §3.3, Phase 1)."""

from datetime import date

import pytest

from metacompass.data.schema import (
    Department,
    EmployeeRow,
    MetricRow,
    ReportRow,
    RequestRow,
    TableRow,
)
from metacompass.data.store import (
    InvalidRecordTypeError,
    MetadataStore,
    RecordNotFoundError,
    record_type,
)


@pytest.fixture(scope="module")
def store(generated_dir) -> MetadataStore:
    return MetadataStore.from_dir(generated_dir)


def test_loads_every_table_with_expected_counts(store):
    assert len(store.employees) == 120
    assert len(store.reports) == 250
    assert len(store.tables) == 80
    assert len(store.metrics) == 40
    assert len(store.requests) == 300
    assert 540 <= len(store.report_table_edges) <= 660
    assert 135 <= len(store.table_table_edges) <= 165


def test_rows_are_typed(store):
    root = store.employee("EMP-001")
    assert isinstance(root, EmployeeRow)
    assert isinstance(root.start_date, date)
    assert root.is_department_head is True
    assert root.manager_id is None  # blank CSV cells become None
    report = next(iter(store.reports.values()))
    assert isinstance(report.usage_30d, int)
    assert isinstance(report.created_date, date)


def test_frames_mirror_rows(store):
    assert set(store.frames) == {
        "employees", "reports", "tables", "metrics", "requests",
        "report_table_edges", "table_table_edges",
    }  # fmt: skip
    assert len(store.frames["reports"]) == 250
    assert store.frames["employees"]["is_department_head"].dtype == bool


@pytest.mark.parametrize(
    ("record_id", "expected"),
    [
        ("EMP-001", "employee"),
        ("RPT-0001", "report"),
        ("TBL-001", "table"),
        ("MET-001", "metric"),
        ("REQ-0001", "request"),
    ],
)
def test_record_type_from_prefix(record_id, expected):
    assert record_type(record_id) == expected


@pytest.mark.parametrize("bad", ["", "XYZ-001", "rpt-0001", "RPT0001", "RPT-01", "EMP-0001"])
def test_record_type_rejects_malformed_ids(bad):
    with pytest.raises(InvalidRecordTypeError):
        record_type(bad)


def test_get_record_returns_the_right_row_type(store):
    assert isinstance(store.get_record("RPT-0001"), ReportRow)
    assert isinstance(store.get_record("TBL-001"), TableRow)
    assert isinstance(store.get_record("MET-001"), MetricRow)
    assert isinstance(store.get_record("EMP-001"), EmployeeRow)
    assert isinstance(store.get_record("REQ-0001"), RequestRow)


def test_get_asset_accepts_only_reports_tables_and_metrics(store):
    assert store.get_asset("RPT-0001").report_id == "RPT-0001"
    assert store.get_asset("TBL-080").table_id == "TBL-080"
    assert store.get_asset("MET-040").metric_id == "MET-040"
    for not_an_asset in ["EMP-001", "REQ-0001", "XYZ-001"]:
        with pytest.raises(InvalidRecordTypeError):
            store.get_asset(not_an_asset)


def test_missing_ids_raise_not_found(store):
    for missing in ["RPT-9999", "TBL-999", "MET-999", "EMP-999", "REQ-9999"]:
        with pytest.raises(RecordNotFoundError):
            store.get_record(missing)
    with pytest.raises(RecordNotFoundError):
        store.employee("EMP-999")
    # Not-found is still a KeyError, so callers can treat it like a dict miss.
    assert issubclass(RecordNotFoundError, KeyError)


@pytest.mark.parametrize("dept", list(Department))
def test_dept_head_for_every_department(store, dept):
    head = store.dept_head(dept)
    assert head.is_department_head
    assert head.department == dept.value
    assert store.dept_head(dept.value) == head  # plain strings work too


def test_list_helpers_parse_packed_fields(store):
    metric = store.metric("MET-002")  # Gross Margin %
    assert metric.name == "Gross Margin %"
    assert "GM%" in store.metric_aliases(metric)
    sources = store.metric_source_table_ids(metric)
    assert sources and all(tid in store.tables for tid in sources)
    report = store.report("RPT-0001")
    tags = store.report_tags(report)
    assert 1 <= len(tags) <= 5
    columns = store.table_columns(store.table("TBL-001"))
    assert {"name", "type"} <= set(columns[0])


def test_null_formula_is_none(store):
    assert sum(1 for m in store.metrics.values() if m.formula is None) == 3


def test_tables_of_report_uses_edges(store):
    tids = store.tables_of_report("RPT-0001")
    assert tids == sorted(tids)
    assert all(tid in store.tables for tid in tids)
    assert tids


def test_missing_data_directory_gives_actionable_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="metacompass.data.generate"):
        MetadataStore.from_dir(tmp_path / "nowhere")
