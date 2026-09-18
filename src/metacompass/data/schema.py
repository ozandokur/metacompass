"""Row models, enums and ID formats for the seven synthetic metadata tables (spec §4.3).

These models describe one CSV row each, in the exact column order written to disk.
They check types, enum values and ID shapes only; cross-row rules (foreign keys, dates,
succession chains) are invariants tested in tests/test_data_integrity.py.
This module is also the only metacompass module eval/gold.py may import.
"""

import re
from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class Department(StrEnum):
    OPERATIONS = "Operations"
    SALES = "Sales"
    AFTERSALES = "Aftersales"
    FINANCE = "Finance"
    MARKETING = "Marketing"
    SUPPLY_CHAIN = "Supply Chain"
    DATA_ANALYTICS = "Data & Analytics"


DEPARTMENT_CODES: dict[Department, str] = {
    Department.OPERATIONS: "OPS",
    Department.SALES: "SAL",
    Department.AFTERSALES: "AFT",
    Department.FINANCE: "FIN",
    Department.MARKETING: "MKT",
    Department.SUPPLY_CHAIN: "SCM",
    Department.DATA_ANALYTICS: "DNA",
}


class EmployeeStatus(StrEnum):
    ACTIVE = "active"
    LEFT = "left"


class ReportStatus(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class RefreshStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    DISABLED = "disabled"


class Layer(StrEnum):
    STAGING = "staging"
    INTERMEDIATE = "intermediate"
    MART = "mart"


class UpdateFrequency(StrEnum):
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class TransformType(StrEnum):
    CLEAN = "clean"
    JOIN = "join"
    AGGREGATE = "aggregate"
    SNAPSHOT = "snapshot"


class RequestStatus(StrEnum):
    DONE = "done"
    DUPLICATE = "duplicate"
    OPEN = "open"
    REJECTED = "rejected"
    IN_PROGRESS = "in_progress"


SOURCE_SYSTEMS = ("DMS", "ERP", "CRM", "WMS", "WARRANTY", "WEB")
WAREHOUSE_SOURCE = "warehouse"

# ID formats. Prefixes never collide, so an ID alone tells the record type.
EMPLOYEE_ID_PATTERN = r"EMP-\d{3}"
REPORT_ID_PATTERN = r"RPT-\d{4}"
TABLE_ID_PATTERN = r"TBL-\d{3}"
METRIC_ID_PATTERN = r"MET-\d{3}"
REQUEST_ID_PATTERN = r"REQ-\d{4}"

# Any record ID inside free text (spec §7.8); used for grounding checks.
RECORD_ID_REGEX = re.compile(
    rf"\b({REPORT_ID_PATTERN}|{TABLE_ID_PATTERN}|{METRIC_ID_PATTERN}"
    rf"|{EMPLOYEE_ID_PATTERN}|{REQUEST_ID_PATTERN})\b"
)

RECORD_PREFIXES = {
    "EMP": "employee",
    "RPT": "report",
    "TBL": "table",
    "MET": "metric",
    "REQ": "request",
}


def employee_id(n: int) -> str:
    return f"EMP-{n:03d}"


def report_id(n: int) -> str:
    return f"RPT-{n:04d}"


def table_id(n: int) -> str:
    return f"TBL-{n:03d}"


def metric_id(n: int) -> str:
    return f"MET-{n:03d}"


def request_id(n: int) -> str:
    return f"REQ-{n:04d}"


EmployeeId = Annotated[str, Field(pattern=rf"^{EMPLOYEE_ID_PATTERN}$")]
ReportId = Annotated[str, Field(pattern=rf"^{REPORT_ID_PATTERN}$")]
TableId = Annotated[str, Field(pattern=rf"^{TABLE_ID_PATTERN}$")]
MetricId = Annotated[str, Field(pattern=rf"^{METRIC_ID_PATTERN}$")]
RequestId = Annotated[str, Field(pattern=rf"^{REQUEST_ID_PATTERN}$")]
NonEmpty = Annotated[str, Field(min_length=1)]


class _Row(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=True)


class EmployeeRow(_Row):
    employee_id: EmployeeId
    full_name: NonEmpty
    department: Department
    title: NonEmpty
    is_department_head: bool
    status: EmployeeStatus
    manager_id: EmployeeId | None
    successor_id: EmployeeId | None
    start_date: date
    left_date: date | None


class ReportRow(_Row):
    report_id: ReportId
    name: NonEmpty
    workspace: NonEmpty
    owner_id: EmployeeId
    department: Department
    description: NonEmpty
    created_date: date
    last_refresh: date
    refresh_status: RefreshStatus
    tags: NonEmpty  # "|"-separated, 1-5 tags
    usage_30d: Annotated[int, Field(ge=0)]
    status: ReportStatus
    replaced_by_report_id: ReportId | None


class TableRow(_Row):
    table_id: TableId
    name: Annotated[str, Field(pattern=r"^(stg|int|fct|dim)_[a-z0-9_]+$")]
    layer: Layer
    source_system: NonEmpty
    schema_name: NonEmpty
    owner_id: EmployeeId
    description: NonEmpty
    columns_json: NonEmpty  # JSON list of {"name", "type"}
    row_count: Annotated[int, Field(ge=0)]
    update_frequency: UpdateFrequency


class ReportTableEdgeRow(_Row):
    report_id: ReportId
    table_id: TableId


class TableTableEdgeRow(_Row):
    parent_table_id: TableId
    child_table_id: TableId
    transform_type: TransformType


class MetricRow(_Row):
    metric_id: MetricId
    name: NonEmpty
    aliases: NonEmpty  # "|"-separated, at least one
    business_definition: NonEmpty
    formula: str | None
    source_table_ids: NonEmpty  # JSON list of mart table IDs
    owner_id: EmployeeId


class RequestRow(_Row):
    request_id: RequestId
    title: NonEmpty
    description: NonEmpty
    requester_id: EmployeeId
    assignee_id: EmployeeId
    department: Department
    created_date: date
    closed_date: date | None
    status: RequestStatus
    resulting_report_id: ReportId | None
    duplicate_of_request_id: RequestId | None


# Table name -> row model. Dict order is the order files are generated and documented.
TABLE_MODELS: dict[str, type[_Row]] = {
    "employees": EmployeeRow,
    "tables": TableRow,
    "table_table_edges": TableTableEdgeRow,
    "metrics": MetricRow,
    "reports": ReportRow,
    "report_table_edges": ReportTableEdgeRow,
    "requests": RequestRow,
}


def columns_of(table: str) -> list[str]:
    """CSV column order for a table: the row model's field order."""
    return list(TABLE_MODELS[table].model_fields)
