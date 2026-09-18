"""Tool tests (spec §7.9): happy path, an edge case, an error code, the size limit and
deterministic output for every tool, plus the impact_analysis cases.

Expected values are worked out by hand from tests/fixtures/mini (see its README).
"""

from collections import Counter

import pytest

from gold import impact_notify
from metacompass.config import NOTIFY_BROADCAST_TOP, NOTIFY_DETAIL_MAX, output_char_cap
from metacompass.tools.impact import build_impact, impact_analysis
from metacompass.tools.lineage import trace_lineage
from metacompass.tools.past_work import find_similar_past_work
from metacompass.tools.records import get_record
from metacompass.tools.schemas import ToolError
from metacompass.tools.search import search_assets


def error_code(call) -> str:
    with pytest.raises(ToolError) as error:
        call()
    assert "Traceback" not in error.value.message
    return error.value.code


def same_twice(call) -> bool:
    return call().model_dump_json() == call().model_dump_json()


# ---------------------------------------------------------------------- search_assets


def test_search_finds_and_describes_assets(mini_ctx):
    out = search_assets(mini_ctx, query="parts returns and reasons")
    ids = [h.id for h in out.hits]
    assert "RPT-0003" in ids
    assert [h.rank for h in out.hits] == list(range(1, len(out.hits) + 1))
    hit = next(h for h in out.hits if h.id == "RPT-0003")
    assert (hit.type, hit.name, hit.status, hit.department) == (
        "report", "Parts Returns Tracker", "active", "Supply Chain",
    )  # fmt: skip
    assert len(hit.snippet) <= 160
    assert out.signal.match_quality in {"strong", "weak"}


def test_search_filters(mini_ctx):
    tables = search_assets(mini_ctx, query="sales", asset_type="table", top_k=10)
    assert tables.hits and all(h.type == "table" for h in tables.hits)
    active = search_assets(
        mini_ctx, query="regional sales legacy", include_deprecated=False, top_k=10
    )
    assert "RPT-0004" not in [h.id for h in active.hits]
    deprecated = search_assets(mini_ctx, query="Regional Sales Legacy", top_k=10)
    hit = next(h for h in deprecated.hits if h.id == "RPT-0004")
    assert hit.replaced_by_report_id == "RPT-0005"


def test_search_on_an_empty_filtered_corpus_is_weak(mini_ctx):
    # Every mini metric is owned by someone from Sales, so there is no Finance metric.
    out = search_assets(mini_ctx, query="margin", asset_type="metric", department="Finance")
    assert out.hits == []
    assert out.signal.match_quality == "weak"


def test_search_errors(mini_ctx):
    assert error_code(lambda: search_assets(mini_ctx, query="")) == "INVALID_ARGUMENT"
    assert error_code(lambda: search_assets(mini_ctx, query="   ")) == "INVALID_ARGUMENT"
    assert error_code(lambda: search_assets(mini_ctx, query="x", top_k=11)) == "INVALID_ARGUMENT"
    assert (
        error_code(lambda: search_assets(mini_ctx, query="x", department="Legal"))
        == "INVALID_ARGUMENT"
    )


def test_search_size_and_determinism(real_ctx):
    def call():
        return search_assets(real_ctx, query="dealer sales performance by region", top_k=10)

    assert len(call().model_dump_json()) <= output_char_cap("search_assets")
    assert same_twice(call)


# ---------------------------------------------------------------------- get_record


def test_get_record_report(mini_ctx):
    out = get_record(mini_ctx, "RPT-0001")
    assert out.record_type == "report"
    assert [(t.id, t.name, t.layer) for t in out.tables] == [
        ("TBL-005", "fct_sales", "mart"),
        ("TBL-006", "dim_region", "mart"),
    ]
    assert (out.owner.id, out.owner.status) == ("EMP-004", "active")
    assert out.tags == ["sales", "dealers"]


def test_get_record_table_counts(mini_ctx):
    out = get_record(mini_ctx, "TBL-004")
    assert (out.parent_table_count, out.child_table_count) == (2, 2)
    # RPT-0001, 0002, 0004, 0005, 0006 and 0007 read TBL-004 directly or through its children.
    assert out.downstream_report_count == 6
    assert out.columns[0] == {"name": "sale_id", "type": "string"}


def test_get_record_metric_with_null_formula(mini_ctx):
    out = get_record(mini_ctx, "MET-003")
    assert out.formula is None
    assert "formula" in out.model_dump()  # explicitly null, not missing
    assert [t.id for t in out.source_tables] == ["TBL-007"]
    assert out.aliases == ["returns %", "RMA rate"]


def test_get_record_employee_and_request(mini_ctx):
    emp = get_record(mini_ctx, "EMP-010")
    assert (emp.status, emp.successor_id, emp.manager_id) == ("left", None, "EMP-003")
    req = get_record(mini_ctx, "REQ-0003")
    assert req.duplicate_of_request_id == "REQ-0002"
    assert (req.requester.id, req.assignee.id) == ("EMP-014", "EMP-003")


def test_get_record_errors(mini_ctx):
    assert error_code(lambda: get_record(mini_ctx, "XYZ-001")) == "INVALID_ARGUMENT"
    assert error_code(lambda: get_record(mini_ctx, "RPT-0999")) == "NOT_FOUND"
    assert error_code(lambda: get_record(mini_ctx, "EMP-999")) == "NOT_FOUND"


def test_get_record_size_and_determinism(real_ctx):
    for record_id in ("RPT-0001", "TBL-065", "MET-002", "EMP-001", "REQ-0001"):
        out = get_record(real_ctx, record_id)
        assert len(out.model_dump_json()) <= output_char_cap("get_record")
        assert same_twice(lambda rid=record_id: get_record(real_ctx, rid))


# ---------------------------------------------------------------------- trace_lineage


def test_lineage_upstream_of_a_report(mini_ctx):
    out = trace_lineage(mini_ctx, "RPT-0001", "upstream", depth=6)
    assert [(n.id, n.distance) for n in out.nodes] == [
        ("TBL-005", 1), ("TBL-006", 1), ("TBL-003", 2), ("TBL-004", 2), ("TBL-001", 3), ("TBL-002", 3),
    ]  # fmt: skip
    assert out.nodes[0].type == "table" and out.nodes[0].layer == "mart"
    assert out.truncated is False


def test_lineage_marks_nodes_beyond_the_depth(mini_ctx):
    shallow = trace_lineage(mini_ctx, "RPT-0001", "upstream", depth=1)
    assert [n.id for n in shallow.nodes] == ["TBL-005", "TBL-006"]
    assert shallow.truncated is True


def test_lineage_of_a_report_downstream_is_empty(mini_ctx):
    out = trace_lineage(mini_ctx, "RPT-0001", "downstream", depth=3)
    assert (out.nodes, out.truncated) == ([], False)


def test_lineage_errors(mini_ctx):
    assert error_code(lambda: trace_lineage(mini_ctx, "XYZ-001", "upstream")) == "INVALID_ARGUMENT"
    assert error_code(lambda: trace_lineage(mini_ctx, "EMP-001", "upstream")) == "INVALID_ARGUMENT"
    assert error_code(lambda: trace_lineage(mini_ctx, "REQ-0001", "upstream")) == "INVALID_ARGUMENT"
    assert error_code(lambda: trace_lineage(mini_ctx, "TBL-999", "upstream")) == "NOT_FOUND"
    assert (
        error_code(lambda: trace_lineage(mini_ctx, "TBL-001", "upstream", depth=7))
        == "INVALID_ARGUMENT"
    )
    assert error_code(lambda: trace_lineage(mini_ctx, "TBL-001", "sideways")) == "INVALID_ARGUMENT"


def test_lineage_size_and_determinism(real_ctx):
    def call():
        return trace_lineage(real_ctx, "TBL-003", "downstream", depth=6)  # a busy staging table

    out = call()
    assert len(out.model_dump_json()) <= output_char_cap("trace_lineage")
    assert out.truncated is True
    assert same_twice(call)


# ---------------------------------------------------------------------- find_similar_past_work


def test_past_work_finds_related_requests(mini_ctx):
    out = find_similar_past_work(mini_ctx, description="returned parts per region")
    ids = [h.request_id for h in out.hits]
    assert {"REQ-0002", "REQ-0003"} <= set(ids[:3])
    duplicate = next(h for h in out.hits if h.request_id == "REQ-0003")
    assert duplicate.duplicate_of_request_id == "REQ-0002"


def test_past_work_department_filter(mini_ctx):
    out = find_similar_past_work(mini_ctx, description="returned parts", department="Operations")
    assert out.hits and {h.request_id for h in out.hits} <= {"REQ-0003", "REQ-0006"}


def test_past_work_errors(mini_ctx):
    assert (
        error_code(lambda: find_similar_past_work(mini_ctx, description="")) == "INVALID_ARGUMENT"
    )
    assert (
        error_code(lambda: find_similar_past_work(mini_ctx, description="x", top_k=0))
        == "INVALID_ARGUMENT"
    )


def test_past_work_size_and_determinism(real_ctx):
    def call():
        return find_similar_past_work(real_ctx, description="parts returns by region", top_k=10)

    assert len(call().model_dump_json()) <= output_char_cap("find_similar_past_work")
    assert same_twice(call)


# ---------------------------------------------------------------------- impact_analysis


def test_impact_lists_everything_downstream(mini_ctx):
    out = impact_analysis(mini_ctx, "TBL-004")
    assert out.affected_tables == ["TBL-005", "TBL-006"]
    assert out.affected_metrics == ["MET-001", "MET-002"]
    assert [(r.report_id, r.usage_30d) for r in out.affected_reports] == [
        ("RPT-0001", 120), ("RPT-0005", 60), ("RPT-0002", 40),
        ("RPT-0006", 30), ("RPT-0007", 5), ("RPT-0004", 1),
    ]  # fmt: skip


def test_impact_merges_one_person_into_one_row(mini_ctx):
    notify = {n.employee_id: n for n in impact_analysis(mini_ctx, "TBL-004").notify}
    # RPT-0001 (owner), RPT-0002 (via S1) and RPT-0006 (via C3) all end at EMP-004.
    assert notify["EMP-004"].report_ids == ["RPT-0001", "RPT-0002", "RPT-0006"]
    assert notify["EMP-004"].metric_ids == ["MET-001"]
    assert notify["EMP-004"].total_usage_30d == 190
    assert notify["EMP-004"].via_fallback is False


def test_impact_does_not_notify_owners_of_deprecated_reports(mini_ctx):
    out = impact_analysis(mini_ctx, "TBL-004")
    assert "EMP-014" not in [n.employee_id for n in out.notify]  # owns only the deprecated RPT-0004
    deprecated = next(r for r in out.affected_reports if r.report_id == "RPT-0004")
    assert deprecated.notify_employee_id is None


def test_impact_uses_the_fallback_for_unresolved_owners(mini_ctx):
    out = impact_analysis(mini_ctx, "TBL-004")
    notify = {n.employee_id: n for n in out.notify}
    # EMP-005 heads a four-leaver chain: RPT-0007 and MET-002 go to the Sales head.
    assert notify["EMP-002"].report_ids == ["RPT-0007"]
    assert notify["EMP-002"].metric_ids == ["MET-002"]
    assert notify["EMP-002"].via_fallback is True
    assert out.unresolved_asset_ids == ["MET-002", "RPT-0007"]
    assert [n.employee_id for n in out.notify] == ["EMP-004", "EMP-003", "EMP-002"]  # by usage


def test_impact_errors(mini_ctx):
    assert error_code(lambda: impact_analysis(mini_ctx, "XYZ-001")) == "INVALID_ARGUMENT"
    assert error_code(lambda: impact_analysis(mini_ctx, "RPT-0001")) == "INVALID_ARGUMENT"
    assert error_code(lambda: impact_analysis(mini_ctx, "TBL-999")) == "NOT_FOUND"


def test_impact_counts_and_mode_on_the_mini_fixture(mini_ctx):
    out = impact_analysis(mini_ctx, "TBL-004")
    assert (out.affected_report_count, out.affected_metric_count) == (6, 2)
    assert (out.notify_mode, out.notify_total_count, out.notify_omitted_count) == (
        "individual", 3, 0,
    )  # fmt: skip
    assert out.notify_rollup == []


@pytest.fixture(scope="module")
def impacts(real_ctx, raw):
    """(table ID, full answer, capped answer, independent gold) for every generated table."""
    return [
        (tid, build_impact(real_ctx, tid), impact_analysis(real_ctx, tid), impact_notify(raw, tid))
        for tid in sorted(real_ctx.store.tables)
    ]


def _ranking(gold) -> list[str]:
    """Gold people in notify order: most affected usage first, then ID."""
    return sorted(gold["people"], key=lambda p: (-gold["people"][p]["usage"], p))


def test_impact_counts_match_an_independent_computation(impacts):
    cap = output_char_cap("impact_analysis")
    for tid, _, out, gold in impacts:
        assert len(out.model_dump_json()) <= cap, tid
        assert out.notify_total_count == len(gold["people"]), tid
        assert out.affected_report_count == len(gold["reports"]), tid
        assert out.affected_metric_count == len(gold["metrics"]), tid
    assert any(out.truncated for _, _, out, _ in impacts)  # the cap is really used


def test_impact_notify_mode_follows_the_number_of_people(impacts):
    modes = set()
    for tid, _, out, gold in impacts:
        ranking, total = _ranking(gold), len(gold["people"])
        modes.add(out.notify_mode)
        if total <= NOTIFY_DETAIL_MAX:
            assert out.notify_mode == "individual", tid
            assert [n.employee_id for n in out.notify] == ranking, tid  # everyone, in order
            assert (out.notify_rollup, out.notify_omitted_count) == ([], 0), tid
        else:
            assert out.notify_mode == "broadcast", tid
            top = ranking[:NOTIFY_BROADCAST_TOP]
            assert [n.employee_id for n in out.notify] == top, tid
            assert out.notify_omitted_count == total - NOTIFY_BROADCAST_TOP, tid
    assert modes == {"individual", "broadcast"}  # both modes occur in the generated data


def test_impact_rollup_accounts_for_every_person(impacts, raw):
    employees = raw["employees"].set_index("employee_id")
    head_rows = employees[employees["is_department_head"] == "true"]
    heads = dict(zip(head_rows["department"], head_rows.index, strict=True))
    for tid, _, out, gold in impacts:
        if out.notify_mode == "individual":
            continue
        people = gold["people"]
        dept_of = {p: employees.loc[p, "department"] for p in people}
        expected_people = Counter(dept_of.values())
        expected_reports = Counter()
        for person, info in people.items():
            expected_reports[dept_of[person]] += len(info["reports"])
        rollup = {r.department: r for r in out.notify_rollup}
        assert sum(r.people_count for r in out.notify_rollup) == out.notify_total_count, tid
        assert {d: r.people_count for d, r in rollup.items()} == dict(expected_people), tid
        assert {d: r.report_count for d, r in rollup.items()} == {
            d: expected_reports[d] for d in expected_people
        }, tid
        assert {d: r.head_employee_id for d, r in rollup.items()} == {
            d: heads[d] for d in expected_people
        }, tid
        order = [(-r.people_count, r.department) for r in out.notify_rollup]
        assert order == sorted(order), tid


def test_impact_cap_only_trims_the_affected_lists(impacts):
    counts = ("affected_report_count", "affected_metric_count", "notify_total_count")
    for tid, full, out, _ in impacts:
        assert out.notify == full.notify, tid
        assert out.notify_rollup == full.notify_rollup, tid
        assert [getattr(out, c) for c in counts] == [getattr(full, c) for c in counts], tid
        for field in ("affected_reports", "affected_tables", "affected_metrics"):
            kept = getattr(out, field)
            assert kept == getattr(full, field)[: len(kept)], (tid, field)  # cut from the end
        assert out.truncated is (out != full), tid


def test_impact_of_a_table_without_dependants(mini_ctx):
    out = impact_analysis(mini_ctx, "TBL-008")
    assert (out.affected_reports, out.notify, out.truncated) == ([], [], False)
    assert (out.notify_total_count, out.notify_mode) == (0, "individual")
    assert same_twice(lambda: impact_analysis(mini_ctx, "TBL-004"))
