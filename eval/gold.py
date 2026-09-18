"""Independent gold answers for evaluation questions (spec §9.1, §9.4).

Gold is computed straight from the generated CSVs with pandas, never through the
metacompass tools, graph or retrieval code, so a bug in a tool cannot make its own wrong
answers count as correct (decision D14). tests/test_architecture.py enforces the imports.
Phase 2 implements the lookup and abstain specs used by the retrieval benchmark. Phase 3
adds the ownership walk and the impact computation, which the tool tests check
impact_analysis against on every generated table. The gold-spec wiring for them, and the
lineage and past-work specs, arrive in Phase 5.
"""

import json
from collections import deque
from pathlib import Path

import pandas as pd

TABLE_FILES = (
    "employees",
    "reports",
    "tables",
    "report_table_edges",
    "table_table_edges",
    "metrics",
    "requests",
)


def load_raw(data_dir: Path) -> dict[str, pd.DataFrame]:
    """All CSVs as string frames; blank cells stay empty strings."""
    raw_dir = Path(data_dir) / "raw"
    return {
        name: pd.read_csv(raw_dir / f"{name}.csv", dtype=str, keep_default_na=False)
        for name in TABLE_FILES
    }


def load_meta(data_dir: Path) -> dict:
    """The generator's intent file (evaluation code may read it; runtime code may not)."""
    return json.loads((Path(data_dir) / "_meta.json").read_text(encoding="utf-8"))


def _asset_ids(raw: dict[str, pd.DataFrame]) -> set[str]:
    return (
        set(raw["reports"]["report_id"])
        | set(raw["tables"]["table_id"])
        | set(raw["metrics"]["metric_id"])
    )


# The ownership walk limit, restated from spec §4.4.1 (D09) instead of imported from the
# package config, so the gold does not share a value with the code it grades.
MAX_HOPS = 3


def _people(raw: dict[str, pd.DataFrame]) -> dict[str, dict]:
    return raw["employees"].set_index("employee_id").to_dict("index")


def _heads(people: dict[str, dict]) -> dict[str, str]:
    return {
        row["department"]: eid for eid, row in people.items() if row["is_department_head"] == "true"
    }


def _owners(raw: dict[str, pd.DataFrame]) -> dict[str, str]:
    owners: dict[str, str] = {}
    for name, id_column in (
        ("reports", "report_id"),
        ("tables", "table_id"),
        ("metrics", "metric_id"),
    ):
        frame = raw[name]
        owners.update(zip(frame[id_column], frame["owner_id"], strict=True))
    return owners


def _walk(people: dict[str, dict], heads: dict[str, str], owner: str) -> tuple[str, bool]:
    """From an asset's owner to the person to contact today; False if the chain failed.

    While the person has left, step to their successor (else their manager). Needing more
    than MAX_HOPS steps, meeting someone twice or running out of links ends the walk at
    the head of the owner's department.
    """
    person, hops, seen = owner, 0, {owner}
    while people[person]["status"] == "left":
        step = people[person]["successor_id"] or people[person]["manager_id"]
        if hops == MAX_HOPS or not step or step in seen:
            return heads[people[owner]["department"]], False
        seen.add(step)
        person, hops = step, hops + 1
    return person, True


def current_contact(raw: dict[str, pd.DataFrame], asset_id: str) -> tuple[str, bool]:
    """Who to contact about a report, table or metric today, and whether the chain resolved."""
    people = _people(raw)
    return _walk(people, _heads(people), _owners(raw)[asset_id])


def _downstream(raw: dict[str, pd.DataFrame], table_id: str) -> tuple[list, list, list]:
    """Tables, reports and metrics that read the table directly or through other tables."""
    edges = raw["table_table_edges"]
    children: dict[str, list[str]] = {}
    for parent, child in zip(edges["parent_table_id"], edges["child_table_id"], strict=True):
        children.setdefault(parent, []).append(child)
    reached, queue = {table_id}, deque([table_id])
    while queue:
        for child in children.get(queue.popleft(), []):
            if child not in reached:
                reached.add(child)
                queue.append(child)
    report_edges = raw["report_table_edges"]
    reports = set(report_edges.loc[report_edges["table_id"].isin(reached), "report_id"])
    metric_frame = raw["metrics"]
    metrics = {
        metric_id
        for metric_id, sources in zip(
            metric_frame["metric_id"], metric_frame["source_table_ids"], strict=True
        )
        if reached & set(json.loads(sources))
    }
    return sorted(reached - {table_id}), sorted(reports), sorted(metrics)


def impact_notify(raw: dict[str, pd.DataFrame], table_id: str) -> dict:
    """Everything downstream of a table, and who is told about it (gold type impact_notify).

    Active reports and all metrics go to the person their ownership walk ends at;
    deprecated reports are affected but nobody is told (D10). `people` maps each person to
    the affected usage and the report and metric IDs that reach them.
    """
    tables, reports, metrics = _downstream(raw, table_id)
    people, owners = _people(raw), _owners(raw)
    heads = _heads(people)
    report_rows = raw["reports"].set_index("report_id")
    notified: dict[str, dict] = {}

    def entry(asset_id: str) -> dict:
        person, _ = _walk(people, heads, owners[asset_id])
        return notified.setdefault(person, {"usage": 0, "reports": [], "metrics": []})

    for report_id in reports:
        if report_rows.loc[report_id, "status"] == "active":
            target = entry(report_id)
            target["reports"].append(report_id)
            target["usage"] += int(report_rows.loc[report_id, "usage_30d"])
    for metric_id in metrics:
        entry(metric_id)["metrics"].append(metric_id)
    return {"tables": tables, "reports": reports, "metrics": metrics, "people": notified}


def compute_gold(gold_spec: dict, raw: dict[str, pd.DataFrame], meta: dict) -> dict:
    """Gold answer for one question: answer IDs, forbidden IDs and whether to abstain."""
    kind = gold_spec["type"]
    if kind == "asset_by_description":
        target = gold_spec["target_id"]
        forbidden = sorted(gold_spec.get("forbidden_ids", []))
        assets = _asset_ids(raw)
        missing = [i for i in [target, *forbidden] if i not in assets]
        if missing:
            raise ValueError(f"unknown asset IDs in gold spec: {missing}")
        return {"answer_ids": [target], "forbidden_ids": forbidden, "should_abstain": False}
    if kind == "abstain":
        return {"answer_ids": [], "forbidden_ids": [], "should_abstain": True}
    raise NotImplementedError(f"gold spec type {kind!r} is implemented in Phase 5")
