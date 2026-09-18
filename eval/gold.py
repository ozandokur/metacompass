"""Independent gold answers for evaluation questions (spec §9.1, §9.4).

Gold is computed straight from the generated CSVs with pandas, never through the
metacompass tools, graph or retrieval code, so a bug in a tool cannot make its own wrong
answers count as correct (decision D14). tests/test_architecture.py enforces the imports;
tests/test_gold_independence.py checks every type by hand on the mini fixture and against
the matching tool on all generated inputs.

Gold spec types (spec §9.4):
  asset_by_description       target_id, forbidden_ids   -> [target]
  current_contact_for_asset  asset_id or asset_ids      -> today's contacts; departed owners forbidden
  upstream_tables            node_id, depth             -> tables within depth, upstream
  downstream_reports         table_id, depth            -> reports within depth (active + deprecated)
  similar_requests           topic_key                  -> the requests of one topic cluster
  impact_notify              table_id                   -> people to notify, or their department
                                                           heads above NOTIFY_DETAIL_MAX (D24)
  abstain                    reason                     -> nothing; should_abstain
  chain                      steps, use_last            -> the last step's gold (MX)
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


# Limits restated from the spec instead of imported from the package config, so the gold
# does not share a value with the code it grades: the ownership walk (§4.4.1, D09) and the
# point where impact answers switch to department heads (§7.7, D24).
MAX_HOPS = 3
NOTIFY_DETAIL_MAX = 20


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


def _bfs(start: dict[str, int], step: dict[str, list[str]], depth: int) -> dict[str, int]:
    """Shortest distances from the start nodes (given with their distance), up to `depth`."""
    distance = dict(start)
    queue = deque(sorted(start, key=lambda n: start[n]))
    while queue:
        node = queue.popleft()
        if distance[node] >= depth:
            continue
        for nxt in step.get(node, []):
            if nxt not in distance:
                distance[nxt] = distance[node] + 1
                queue.append(nxt)
    return distance


def _table_links(raw: dict[str, pd.DataFrame]) -> tuple[dict, dict]:
    parents: dict[str, list[str]] = {}
    children: dict[str, list[str]] = {}
    edges = raw["table_table_edges"]
    for parent, child in zip(edges["parent_table_id"], edges["child_table_id"], strict=True):
        parents.setdefault(child, []).append(parent)
        children.setdefault(parent, []).append(child)
    return parents, children


def _upstream_tables(raw: dict[str, pd.DataFrame], node_id: str, depth: int) -> list[str]:
    """Tables within `depth` steps upstream of a report, metric or table."""
    parents, _ = _table_links(raw)
    if node_id in set(raw["reports"]["report_id"]):
        edges = raw["report_table_edges"]
        first = list(edges.loc[edges["report_id"] == node_id, "table_id"])
    elif node_id in set(raw["metrics"]["metric_id"]):
        metrics = raw["metrics"].set_index("metric_id")
        first = json.loads(metrics.at[node_id, "source_table_ids"])
    elif node_id in set(raw["tables"]["table_id"]):
        first = parents.get(node_id, [])
    else:
        raise ValueError(f"unknown lineage node: {node_id}")
    if depth < 1:
        return []
    return sorted(_bfs(dict.fromkeys(first, 1), parents, depth))


def _downstream_reports(raw: dict[str, pd.DataFrame], table_id: str, depth: int) -> list[str]:
    """Reports within `depth` steps downstream of a table: a report reading a table at
    distance d is at distance d + 1."""
    if table_id not in set(raw["tables"]["table_id"]):
        raise ValueError(f"unknown table: {table_id}")
    _, children = _table_links(raw)
    tables = _bfs({table_id: 0}, children, depth - 1)
    edges = raw["report_table_edges"]
    return sorted(set(edges.loc[edges["table_id"].isin(tables), "report_id"]))


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


def _answer(answer_ids, forbidden_ids=(), **extra) -> dict:
    return {
        "answer_ids": sorted(set(answer_ids)),
        "forbidden_ids": sorted(set(forbidden_ids)),
        "should_abstain": False,
        **extra,
    }


def compute_gold(gold_spec: dict, raw: dict[str, pd.DataFrame], meta: dict) -> dict:
    """Gold answer for one question: answer IDs, forbidden IDs and whether to abstain."""
    kind = gold_spec["type"]
    if kind == "asset_by_description":
        target = gold_spec["target_id"]
        forbidden = gold_spec.get("forbidden_ids", [])
        assets = _asset_ids(raw)
        missing = [i for i in [target, *forbidden] if i not in assets]
        if missing:
            raise ValueError(f"unknown asset IDs in gold spec: {missing}")
        return _answer([target], forbidden)

    if kind == "current_contact_for_asset":
        asset_ids = gold_spec.get("asset_ids") or [gold_spec["asset_id"]]
        people, owners = _people(raw), _owners(raw)
        heads = _heads(people)
        unknown = [a for a in asset_ids if a not in owners]
        if unknown:
            raise ValueError(f"unknown asset IDs in gold spec: {unknown}")
        contacts = [_walk(people, heads, owners[a])[0] for a in asset_ids]
        # Naming an owner who has left is a known wrong answer (spec §9.4).
        departed = [owners[a] for a in asset_ids if people[owners[a]]["status"] == "left"]
        return _answer(contacts, set(departed) - set(contacts))

    if kind == "upstream_tables":
        return _answer(_upstream_tables(raw, gold_spec["node_id"], gold_spec["depth"]))

    if kind == "downstream_reports":
        return _answer(_downstream_reports(raw, gold_spec["table_id"], gold_spec["depth"]))

    if kind == "similar_requests":
        keys = meta["request_topic_keys"]
        found = [rid for rid, key in keys.items() if key == gold_spec["topic_key"]]
        if not found:
            raise ValueError(f"no requests for topic {gold_spec['topic_key']!r}")
        return _answer(found)

    if kind == "impact_notify":
        notified = impact_notify(raw, gold_spec["table_id"])["people"]
        if len(notified) <= NOTIFY_DETAIL_MAX:
            return _answer(notified)
        # Broadcast (D24): the answer is who to announce to, the department heads of
        # everyone affected; the answer text is expected to say how many people that is.
        people = _people(raw)
        heads = _heads(people)
        departments = {people[p]["department"] for p in notified}
        return _answer([heads[d] for d in departments], min_mentioned_count=len(notified))

    if kind == "abstain":
        return {"answer_ids": [], "forbidden_ids": [], "should_abstain": True}

    if kind == "chain":
        if not gold_spec.get("use_last", True):
            raise ValueError("only chains scored on their last step are supported")
        golds = [compute_gold(step, raw, meta) for step in gold_spec["steps"]]
        return golds[-1]

    raise ValueError(f"unknown gold spec type {kind!r}")
