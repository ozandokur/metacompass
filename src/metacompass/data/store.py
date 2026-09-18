"""MetadataStore: loads the seven CSVs into typed rows and pandas frames, with lookups.

Everything downstream (retrieval, graph, tools) reads metadata through this class.
Each CSV row is validated into its schema row model on load, so a malformed file fails
here and not deep inside a tool. The store reads data/raw/*.csv only; the generator's
intent file is deliberately off limits to runtime code (spec §3.2).
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from metacompass.data.schema import (
    EMPLOYEE_ID_PATTERN,
    METRIC_ID_PATTERN,
    REPORT_ID_PATTERN,
    REQUEST_ID_PATTERN,
    TABLE_ID_PATTERN,
    TABLE_MODELS,
    Department,
    EmployeeRow,
    MetricRow,
    ReportRow,
    ReportTableEdgeRow,
    RequestRow,
    TableRow,
    TableTableEdgeRow,
)

_ID_TYPES = [
    (re.compile(rf"^{EMPLOYEE_ID_PATTERN}$"), "employee"),
    (re.compile(rf"^{REPORT_ID_PATTERN}$"), "report"),
    (re.compile(rf"^{TABLE_ID_PATTERN}$"), "table"),
    (re.compile(rf"^{METRIC_ID_PATTERN}$"), "metric"),
    (re.compile(rf"^{REQUEST_ID_PATTERN}$"), "request"),
]
ASSET_TYPES = ("report", "table", "metric")

Asset = ReportRow | TableRow | MetricRow
Record = Asset | EmployeeRow | RequestRow


class RecordNotFoundError(KeyError):
    """A well-formed ID that does not exist in the data."""


class InvalidRecordTypeError(ValueError):
    """A malformed ID, or an ID of a record type the caller does not accept."""


def record_type(record_id: str) -> str:
    """Record type from an ID's shape: employee, report, table, metric or request."""
    for pattern, kind in _ID_TYPES:
        if pattern.match(record_id):
            return kind
    raise InvalidRecordTypeError(f"'{record_id}' is not a valid record ID")


def _read_rows(path: Path, table: str) -> list:
    model = TABLE_MODELS[table]
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    # Blank cells mean "no value"; the row models decide which fields may be missing.
    return [
        model(**{k: (v if v != "" else None) for k, v in record.items()})
        for record in frame.to_dict("records")
    ]


@dataclass(frozen=True)
class MetadataStore:
    employees: dict[str, EmployeeRow]
    reports: dict[str, ReportRow]
    tables: dict[str, TableRow]
    metrics: dict[str, MetricRow]
    requests: dict[str, RequestRow]
    report_table_edges: list[ReportTableEdgeRow]
    table_table_edges: list[TableTableEdgeRow]
    frames: dict[str, pd.DataFrame]

    @classmethod
    def from_dir(cls, data_dir: Path) -> "MetadataStore":
        """Load `<data_dir>/raw/*.csv` as written by the generator."""
        raw_dir = Path(data_dir) / "raw"
        if not raw_dir.is_dir():
            raise FileNotFoundError(
                f"No metadata found at {raw_dir}. "
                "Run: python -m metacompass.data.generate --seed 42 --out data/"
            )
        rows = {table: _read_rows(raw_dir / f"{table}.csv", table) for table in TABLE_MODELS}
        frames = {
            table: pd.DataFrame([row.model_dump() for row in table_rows])
            for table, table_rows in rows.items()
        }
        return cls(
            employees={r.employee_id: r for r in rows["employees"]},
            reports={r.report_id: r for r in rows["reports"]},
            tables={r.table_id: r for r in rows["tables"]},
            metrics={r.metric_id: r for r in rows["metrics"]},
            requests={r.request_id: r for r in rows["requests"]},
            report_table_edges=rows["report_table_edges"],
            table_table_edges=rows["table_table_edges"],
            frames=frames,
        )

    # ------------------------------------------------------------------ lookups

    def _lookup(self, collection: dict, record_id: str):
        try:
            return collection[record_id]
        except KeyError:
            raise RecordNotFoundError(f"{record_id} does not exist") from None

    def employee(self, employee_id: str) -> EmployeeRow:
        return self._lookup(self.employees, employee_id)

    def report(self, report_id: str) -> ReportRow:
        return self._lookup(self.reports, report_id)

    def table(self, table_id: str) -> TableRow:
        return self._lookup(self.tables, table_id)

    def metric(self, metric_id: str) -> MetricRow:
        return self._lookup(self.metrics, metric_id)

    def request(self, request_id: str) -> RequestRow:
        return self._lookup(self.requests, request_id)

    def get_record(self, record_id: str) -> Record:
        """Any record by ID; raises InvalidRecordTypeError or RecordNotFoundError."""
        kind = record_type(record_id)
        collection = {
            "employee": self.employees,
            "report": self.reports,
            "table": self.tables,
            "metric": self.metrics,
            "request": self.requests,
        }[kind]
        return self._lookup(collection, record_id)

    def get_asset(self, asset_id: str) -> Asset:
        """A report, table or metric. Employees and requests are not assets."""
        kind = record_type(asset_id)
        if kind not in ASSET_TYPES:
            raise InvalidRecordTypeError(
                f"'{asset_id}' is a {kind}; expected a report, table or metric ID"
            )
        return self.get_record(asset_id)

    def dept_head(self, department: Department | str) -> EmployeeRow:
        dept = Department(department).value
        for row in self.employees.values():
            if row.department == dept and row.is_department_head:
                return row
        raise RecordNotFoundError(f"no head found for {dept}")

    # ------------------------------------------------------------------ packed fields

    @staticmethod
    def report_tags(report: ReportRow) -> list[str]:
        return report.tags.split("|")

    @staticmethod
    def metric_aliases(metric: MetricRow) -> list[str]:
        return metric.aliases.split("|")

    @staticmethod
    def metric_source_table_ids(metric: MetricRow) -> list[str]:
        return json.loads(metric.source_table_ids)

    @staticmethod
    def table_columns(table: TableRow) -> list[dict[str, str]]:
        return json.loads(table.columns_json)

    def tables_of_report(self, report_id: str) -> list[str]:
        """IDs of the tables a report reads, sorted."""
        return sorted(e.table_id for e in self.report_table_edges if e.report_id == report_id)
