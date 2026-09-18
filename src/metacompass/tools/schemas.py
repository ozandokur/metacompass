"""Inputs, outputs and errors of the six tools (spec §7.1).

Every tool takes a validated input model and returns an output model; the JSON schemas the
LLM sees are generated from the input models, never written by hand (decision D19).
Errors are ToolError(code, message) with a message fit to show a user: no stack traces.
All outputs are capped at 4,000 characters of JSON by trimming lists (fit_to_limit).
"""

from dataclasses import dataclass
from typing import Literal

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field

from metacompass.data.schema import Department
from metacompass.data.store import MetadataStore
from metacompass.retrieval.hybrid import HybridRetriever, MatchSignal

MAX_OUTPUT_CHARS = 4000
ErrorCode = Literal["NOT_FOUND", "INVALID_ARGUMENT", "INTERNAL"]


class ToolError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message

    def payload(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


@dataclass(frozen=True)
class ToolContext:
    """Everything a tool may read. Tools get it injected; there is no global state."""

    store: MetadataStore
    retrievers: dict[str, HybridRetriever]
    graph: nx.DiGraph
    retrieval_mode: Literal["hybrid", "bm25", "dense"] = "hybrid"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------------------ inputs


class SearchAssetsInput(_Model):
    query: str = Field(min_length=1, max_length=300, description="What the user is looking for.")
    asset_type: Literal["report", "table", "metric", "any"] = Field(
        "any", description="Restrict the search to one kind of asset."
    )
    department: Department | None = Field(None, description="Only assets of this department.")
    include_deprecated: bool = Field(True, description="Include deprecated reports.")
    top_k: int = Field(5, ge=1, le=10, description="Number of hits to return.")


class GetRecordInput(_Model):
    record_id: str = Field(
        description="A record ID such as RPT-0001, TBL-001, MET-001, EMP-001, REQ-0001."
    )


class ResolveOwnerInput(_Model):
    asset_id: str = Field(description="A report, table or metric ID (RPT-, TBL- or MET-).")


class TraceLineageInput(_Model):
    node_id: str = Field(description="A table, report or metric ID.")
    direction: Literal["upstream", "downstream"] = Field(
        description="upstream = where the data comes from; downstream = what uses it."
    )
    depth: int = Field(3, ge=1, le=6, description="How many steps to follow.")


class FindSimilarPastWorkInput(_Model):
    description: str = Field(min_length=1, max_length=300, description="The analysis to look for.")
    department: Department | None = Field(None, description="Only requests from this department.")
    top_k: int = Field(5, ge=1, le=10, description="Number of requests to return.")


class ImpactAnalysisInput(_Model):
    table_id: str = Field(description="The ID of the table that would change (TBL-).")


# ------------------------------------------------------------------------------ outputs


class AssetHit(_Model):
    id: str
    type: Literal["report", "table", "metric"]
    name: str
    department: str | None  # owner's department for tables and metrics
    status: str | None  # reports only
    replaced_by_report_id: str | None
    snippet: str
    rank: int


class SearchAssetsOutput(_Model):
    query: str
    hits: list[AssetHit]
    signal: MatchSignal
    truncated: bool = False


class PersonSummary(_Model):
    id: str
    name: str
    status: str


class LinkedTable(_Model):
    id: str
    name: str
    layer: str


class ReportRecord(_Model):
    record_type: Literal["report"] = "report"
    report_id: str
    name: str
    workspace: str
    department: str
    description: str
    created_date: str
    last_refresh: str
    refresh_status: str
    tags: list[str]
    usage_30d: int
    status: str
    replaced_by_report_id: str | None
    owner: PersonSummary
    tables: list[LinkedTable]
    truncated: bool = False


class TableRecord(_Model):
    record_type: Literal["table"] = "table"
    table_id: str
    name: str
    layer: str
    source_system: str
    schema_name: str
    description: str
    columns: list[dict[str, str]]
    row_count: int
    update_frequency: str
    owner: PersonSummary
    parent_table_count: int
    child_table_count: int
    downstream_report_count: int
    truncated: bool = False


class MetricRecord(_Model):
    record_type: Literal["metric"] = "metric"
    metric_id: str
    name: str
    aliases: list[str]
    business_definition: str
    formula: str | None  # null means no agreed formula was ever documented
    owner: PersonSummary
    source_tables: list[LinkedTable]
    truncated: bool = False


class EmployeeRecord(_Model):
    record_type: Literal["employee"] = "employee"
    employee_id: str
    full_name: str
    department: str
    title: str
    status: str
    manager_id: str | None
    successor_id: str | None
    is_department_head: bool
    truncated: bool = False


class RequestRecord(_Model):
    record_type: Literal["request"] = "request"
    request_id: str
    title: str
    description: str
    department: str
    created_date: str
    closed_date: str | None
    status: str
    resulting_report_id: str | None
    duplicate_of_request_id: str | None
    requester: PersonSummary
    assignee: PersonSummary
    truncated: bool = False


RecordOutput = ReportRecord | TableRecord | MetricRecord | EmployeeRecord | RequestRecord


class OwnershipHop(_Model):
    employee_id: str
    full_name: str
    status: Literal["active", "left"]
    via: Literal["owner", "successor", "manager"]


class ResolveOwnerOutput(_Model):
    asset_id: str
    original_owner_id: str
    resolved: bool
    resolved_owner_id: str | None
    hops: int
    path: list[OwnershipHop]
    fallback_contact_id: str | None  # only when resolved is False: the owner's department head
    reason: Literal["active_owner", "resolved_via_chain", "depth_limit", "cycle", "dead_end"]
    truncated: bool = False


class LineageNode(_Model):
    id: str
    type: Literal["table", "report", "metric"]
    name: str
    layer: str | None
    status: str | None
    distance: int


class TraceLineageOutput(_Model):
    root_id: str
    direction: str
    depth: int
    nodes: list[LineageNode]  # by distance, then ID; at most 100
    truncated: bool  # nodes exist beyond the depth, or the list was cut


class PastWorkHit(_Model):
    request_id: str
    title: str
    status: str
    created_date: str
    closed_date: str | None
    resulting_report_id: str | None
    duplicate_of_request_id: str | None
    rank: int


class PastWorkOutput(_Model):
    hits: list[PastWorkHit]
    signal: MatchSignal
    truncated: bool = False


class AffectedReport(_Model):
    report_id: str
    name: str
    status: str
    usage_30d: int
    # None for deprecated reports: their owners are not notified (D10).
    notify_employee_id: str | None
    owner_resolved: bool


class NotifyEntry(_Model):
    employee_id: str
    full_name: str
    report_ids: list[str]
    metric_ids: list[str]
    total_usage_30d: int
    via_fallback: bool  # True if at least one asset reached them as department-head fallback


class ImpactOutput(_Model):
    table_id: str
    affected_tables: list[str]
    affected_reports: list[AffectedReport]  # usage_30d descending, then ID
    affected_metrics: list[str]
    notify: list[NotifyEntry]  # total_usage_30d descending, then employee ID
    unresolved_asset_ids: list[str]
    truncated: bool = False


# ------------------------------------------------------------------------------ size limit


def output_size(model: BaseModel) -> int:
    return len(model.model_dump_json())


def fit_to_limit(model: BaseModel, trim_order: list[str], limit: int = MAX_OUTPUT_CHARS):
    """Drop items from the end of the listed fields, in order, until the JSON fits.

    The first field is emptied before the second is touched, so the most important lists go
    last in trim_order (impact_analysis never lists `notify`, so it is never cut).
    """
    if output_size(model) <= limit:
        return model
    data = model.model_dump()
    for field in trim_order:
        while data[field] and len(type(model)(**data).model_dump_json()) > limit:
            data[field] = data[field][:-1]
            data["truncated"] = True
        if len(type(model)(**data).model_dump_json()) <= limit:
            break
    return type(model)(**data)
