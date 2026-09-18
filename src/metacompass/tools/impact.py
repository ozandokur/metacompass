"""impact_analysis: what breaks if a table changes, and who needs to know (spec §7.7).

A composite tool: it walks everything downstream of the table in the lineage graph, runs
resolve_owner on every affected active report and metric, and merges the contacts into
one row per person. Deprecated reports are listed but their owners are not notified
(decision D10). Doing this in code instead of letting the LLM chain the tools is what
ablation A5 measures.

The answer changes form with scale (D24). Up to NOTIFY_DETAIL_MAX people, every person is
listed ("individual"). Above that, a list of everyone is correct but useless, so the tool
"broadcasts": the NOTIFY_BROADCAST_TOP people with the most affected usage, plus a
department rollup that counts every person. Nobody is dropped silently: each person is a
row in `notify` or a count in their department's rollup, and all counts are exact.
"""

from dataclasses import dataclass, field

from metacompass.config import NOTIFY_BROADCAST_TOP, NOTIFY_DETAIL_MAX, output_char_cap
from metacompass.data.store import InvalidRecordTypeError, MetadataStore, record_type
from metacompass.graph import all_descendants
from metacompass.tools.ownership import resolve_owner
from metacompass.tools.schemas import (
    AffectedReport,
    ImpactAnalysisInput,
    ImpactOutput,
    NotifyEntry,
    NotifyRollup,
    ToolContext,
    ToolError,
    fit_to_limit,
    parse_args,
)

# Cut order when the output is over its cap. `notify` and `notify_rollup` are not listed,
# so they are never cut.
TRIM_ORDER = ["affected_reports", "affected_tables", "affected_metrics", "unresolved_asset_ids"]


@dataclass
class _Contact:
    report_ids: list[str] = field(default_factory=list)
    metric_ids: list[str] = field(default_factory=list)
    usage: int = 0
    via_fallback: bool = False


def _rollup(store: MetadataStore, people: list[NotifyEntry]) -> list[NotifyRollup]:
    """One row per department of the people to notify, counting all of them."""
    by_department: dict[str, list[NotifyEntry]] = {}
    for person in people:
        department = store.employee(person.employee_id).department
        by_department.setdefault(department, []).append(person)
    rows = [
        NotifyRollup(
            department=department,
            head_employee_id=store.dept_head(department).employee_id,
            people_count=len(members),
            report_count=sum(len(m.report_ids) for m in members),
        )
        for department, members in by_department.items()
    ]
    return sorted(rows, key=lambda r: (-r.people_count, r.department))


def build_impact(ctx: ToolContext, table_id: str) -> ImpactOutput:
    """The full answer, before the output cap is applied."""
    args = parse_args(ImpactAnalysisInput, table_id=table_id)
    try:
        kind = record_type(args.table_id)
    except InvalidRecordTypeError:
        kind = None
    if kind != "table":
        raise ToolError("INVALID_ARGUMENT", f"{args.table_id} is not a table ID")
    if args.table_id not in ctx.store.tables:
        raise ToolError("NOT_FOUND", f"{args.table_id} does not exist")

    g, store = ctx.graph, ctx.store
    downstream = sorted(all_descendants(g, args.table_id))

    def of_type(node_type: str) -> list[str]:
        return [n for n in downstream if g.nodes[n]["type"] == node_type]

    contacts: dict[str, _Contact] = {}
    unresolved: list[str] = []

    def route(asset_id: str) -> tuple[str, bool]:
        """Who is told about this asset, and whether their ownership chain resolved."""
        result = resolve_owner(ctx, asset_id)
        person = result.resolved_owner_id or result.fallback_contact_id
        if not result.resolved:
            unresolved.append(asset_id)
        contact = contacts.setdefault(person, _Contact())
        contact.via_fallback = contact.via_fallback or not result.resolved
        return person, result.resolved

    affected_reports = []
    for report_id in of_type("report"):
        report = store.report(report_id)
        if report.status == "active":
            person, resolved = route(report_id)
            contacts[person].report_ids.append(report_id)
            contacts[person].usage += report.usage_30d
        else:
            person, resolved = None, resolve_owner(ctx, report_id).resolved
        affected_reports.append(
            AffectedReport(
                report_id=report_id,
                name=report.name,
                status=report.status,
                usage_30d=report.usage_30d,
                notify_employee_id=person,
                owner_resolved=resolved,
            )  # fmt: skip
        )
    affected_metrics = of_type("metric")
    for metric_id in affected_metrics:
        person, _ = route(metric_id)
        contacts[person].metric_ids.append(metric_id)

    everyone = sorted(
        (
            NotifyEntry(
                employee_id=eid,
                full_name=store.employee(eid).full_name,
                report_ids=c.report_ids,
                metric_ids=c.metric_ids,
                total_usage_30d=c.usage,
                via_fallback=c.via_fallback,
            )  # fmt: skip
            for eid, c in contacts.items()
        ),
        key=lambda n: (-n.total_usage_30d, n.employee_id),
    )
    if len(everyone) <= NOTIFY_DETAIL_MAX:
        mode, notify, rollup = "individual", everyone, []
    else:
        mode, notify = "broadcast", everyone[:NOTIFY_BROADCAST_TOP]
        rollup = _rollup(store, everyone)
    return ImpactOutput(
        table_id=args.table_id,
        notify_mode=mode,
        notify_total_count=len(everyone),
        notify_omitted_count=len(everyone) - len(notify),
        affected_report_count=len(affected_reports),
        affected_metric_count=len(affected_metrics),
        affected_tables=of_type("table"),
        affected_reports=sorted(affected_reports, key=lambda r: (-r.usage_30d, r.report_id)),
        affected_metrics=affected_metrics,
        notify=notify,
        notify_rollup=rollup,
        unresolved_asset_ids=sorted(unresolved),
    )


def impact_analysis(ctx: ToolContext, table_id: str) -> ImpactOutput:
    """build_impact cut to the tool's output cap; only the affected-asset lists are cut."""
    return fit_to_limit(build_impact(ctx, table_id), TRIM_ORDER, output_char_cap("impact_analysis"))
