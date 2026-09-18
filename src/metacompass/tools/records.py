"""get_record: the full card of any record by ID (spec §7.3).

Accepts every record type (report, table, metric, employee, request) and adds the context
the agent usually needs next: a report's tables and owner, a table's neighbour counts, a
metric's source tables. Employees are included so that, with resolve_owner switched off
(ablation A3), the model can still walk a succession chain itself.
"""

from metacompass.config import output_char_cap
from metacompass.data.store import InvalidRecordTypeError, RecordNotFoundError, record_type
from metacompass.graph import all_descendants
from metacompass.tools.schemas import (
    EmployeeRecord,
    GetRecordInput,
    LinkedTable,
    MetricRecord,
    PersonSummary,
    RecordOutput,
    ReportRecord,
    RequestRecord,
    TableRecord,
    ToolContext,
    ToolError,
    fit_to_limit,
    parse_args,
)


def _person(ctx: ToolContext, employee_id: str) -> PersonSummary:
    e = ctx.store.employee(employee_id)
    return PersonSummary(id=e.employee_id, name=e.full_name, status=e.status)


def _linked(ctx: ToolContext, table_ids: list[str]) -> list[LinkedTable]:
    tables = [ctx.store.table(tid) for tid in sorted(table_ids)]
    return [LinkedTable(id=t.table_id, name=t.name, layer=t.layer) for t in tables]


def _iso(day) -> str | None:
    return day.isoformat() if day is not None else None


def _report(ctx: ToolContext, rid: str) -> ReportRecord:
    r = ctx.store.report(rid)
    return ReportRecord(
        report_id=r.report_id, name=r.name, workspace=r.workspace, department=r.department,
        description=r.description, created_date=_iso(r.created_date),
        last_refresh=_iso(r.last_refresh), refresh_status=r.refresh_status,
        tags=ctx.store.report_tags(r), usage_30d=r.usage_30d, status=r.status,
        replaced_by_report_id=r.replaced_by_report_id, owner=_person(ctx, r.owner_id),
        tables=_linked(ctx, ctx.store.tables_of_report(rid)),
    )  # fmt: skip


def _table(ctx: ToolContext, tid: str) -> TableRecord:
    t, g = ctx.store.table(tid), ctx.graph
    downstream = all_descendants(g, tid)
    return TableRecord(
        table_id=t.table_id, name=t.name, layer=t.layer, source_system=t.source_system,
        schema_name=t.schema_name, description=t.description,
        columns=ctx.store.table_columns(t), row_count=t.row_count,
        update_frequency=t.update_frequency, owner=_person(ctx, t.owner_id),
        parent_table_count=sum(1 for n in g.predecessors(tid) if g.nodes[n]["type"] == "table"),
        child_table_count=sum(1 for n in g.successors(tid) if g.nodes[n]["type"] == "table"),
        downstream_report_count=sum(1 for n in downstream if g.nodes[n]["type"] == "report"),
    )  # fmt: skip


def _metric(ctx: ToolContext, mid: str) -> MetricRecord:
    m = ctx.store.metric(mid)
    return MetricRecord(
        metric_id=m.metric_id, name=m.name, aliases=ctx.store.metric_aliases(m),
        business_definition=m.business_definition, formula=m.formula,
        owner=_person(ctx, m.owner_id),
        source_tables=_linked(ctx, ctx.store.metric_source_table_ids(m)),
    )  # fmt: skip


def _employee(ctx: ToolContext, eid: str) -> EmployeeRecord:
    e = ctx.store.employee(eid)
    return EmployeeRecord(
        employee_id=e.employee_id, full_name=e.full_name, department=e.department,
        title=e.title, status=e.status, manager_id=e.manager_id,
        successor_id=e.successor_id, is_department_head=e.is_department_head,
    )  # fmt: skip


def _request(ctx: ToolContext, qid: str) -> RequestRecord:
    q = ctx.store.request(qid)
    return RequestRecord(
        request_id=q.request_id, title=q.title, description=q.description,
        department=q.department, created_date=_iso(q.created_date),
        closed_date=_iso(q.closed_date), status=q.status,
        resulting_report_id=q.resulting_report_id,
        duplicate_of_request_id=q.duplicate_of_request_id,
        requester=_person(ctx, q.requester_id), assignee=_person(ctx, q.assignee_id),
    )  # fmt: skip


_BUILDERS = {
    "report": (_report, ["tables"]),
    "table": (_table, ["columns"]),
    "metric": (_metric, ["source_tables"]),
    "employee": (_employee, []),
    "request": (_request, []),
}


def get_record(ctx: ToolContext, record_id: str) -> RecordOutput:
    args = parse_args(GetRecordInput, record_id=record_id)
    try:
        kind = record_type(args.record_id)
        ctx.store.get_record(args.record_id)
    except InvalidRecordTypeError:
        raise ToolError(
            "INVALID_ARGUMENT", f"'{args.record_id}' is not a valid record ID"
        ) from None
    except RecordNotFoundError:
        raise ToolError("NOT_FOUND", f"{args.record_id} does not exist") from None
    build, trim_order = _BUILDERS[kind]
    return fit_to_limit(build(ctx, args.record_id), trim_order, output_char_cap("get_record"))
