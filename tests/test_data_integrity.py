"""Integrity invariants of the synthetic metadata (spec §4.7, I01-I16) and noise checks (§4.5).

Every check reads the generated CSVs with plain pandas and re-derives what it needs,
including an independent ownership walk, so a generator bug cannot hide behind shared code.
Test names start with the invariant code (I..) or the noise code (N..); X.. marks extra
realism checks that the spec implies but does not number.
"""

import json
import re
from datetime import date, timedelta
from pathlib import Path

import networkx as nx
import pandas as pd
import pytest

import metacompass.data
from metacompass.data.schema import (
    EMPLOYEE_ID_PATTERN,
    METRIC_ID_PATTERN,
    REPORT_ID_PATTERN,
    REQUEST_ID_PATTERN,
    TABLE_ID_PATTERN,
    Department,
)

VOCAB_DIR = Path(metacompass.data.__file__).parent / "vocab"
REFERENCE_DATE = date(2026, 9, 1)
MAX_DEPTH = 3
ABBREVIATION_TAGS = {"GM", "AOV", "NPS", "YoY", "MTD", "CSAT", "FTFR", "OTD", "DSO", "ROAS", "CPL"}
VAGUE_STOPWORDS = {"the", "a", "an", "of", "for", "to", "and", "by", "with", "in", "on", "report"}


def d(value: str) -> date:
    return date.fromisoformat(value)


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def jaccard(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / len(ta | tb)


@pytest.fixture(scope="module")
def emp(raw) -> dict[str, dict]:
    return {row["employee_id"]: row for row in raw["employees"].to_dict("records")}


@pytest.fixture(scope="module")
def reports(raw) -> dict[str, dict]:
    return {row["report_id"]: row for row in raw["reports"].to_dict("records")}


@pytest.fixture(scope="module")
def tables(raw) -> dict[str, dict]:
    return {row["table_id"]: row for row in raw["tables"].to_dict("records")}


@pytest.fixture(scope="module")
def requests_(raw) -> dict[str, dict]:
    return {row["request_id"]: row for row in raw["requests"].to_dict("records")}


def reference_walk(emp: dict[str, dict], start_id: str) -> tuple[bool, int, list[str]]:
    """Independent ownership walk (spec §4.4.1): successor first, else manager."""
    current, hops, vias = start_id, 0, []
    while emp[current]["status"] == "left":
        if hops == MAX_DEPTH:
            return False, hops, vias
        if emp[current]["successor_id"]:
            current, via = emp[current]["successor_id"], "successor"
        else:
            current, via = emp[current]["manager_id"], "manager"
        hops += 1
        vias.append(via)
    return True, hops, vias


# ------------------------------------------------------------------ I01 keys and counts


@pytest.mark.parametrize(
    ("table", "key", "pattern", "count"),
    [
        ("employees", "employee_id", EMPLOYEE_ID_PATTERN, 120),
        ("reports", "report_id", REPORT_ID_PATTERN, 250),
        ("tables", "table_id", TABLE_ID_PATTERN, 80),
        ("metrics", "metric_id", METRIC_ID_PATTERN, 40),
        ("requests", "request_id", REQUEST_ID_PATTERN, 300),
    ],
)
def test_I01_primary_keys_unique_formatted_and_counted(raw, table, key, pattern, count):
    ids = raw[table][key]
    assert len(ids) == count
    assert ids.is_unique
    assert ids.str.fullmatch(pattern).all()


def test_I01_ids_are_dense_sequences(raw):
    for table, key, width in [
        ("employees", "employee_id", 3),
        ("reports", "report_id", 4),
        ("tables", "table_id", 3),
        ("metrics", "metric_id", 3),
        ("requests", "request_id", 4),
    ]:
        numbers = sorted(int(x.split("-")[1]) for x in raw[table][key])
        assert numbers == list(range(1, len(numbers) + 1)), table
        assert all(len(x.split("-")[1]) == width for x in raw[table][key])


def test_I01_edge_tables_sized_and_without_duplicates(raw):
    rte, tte = raw["report_table_edges"], raw["table_table_edges"]
    assert 540 <= len(rte) <= 660
    assert 135 <= len(tte) <= 165
    assert not rte.duplicated(["report_id", "table_id"]).any()
    assert not tte.duplicated(["parent_table_id", "child_table_id"]).any()


# ------------------------------------------------------------------ I02 foreign keys


def test_I02_foreign_keys_resolve(raw, emp, reports, tables, requests_):
    def check(values, universe, label):
        missing = sorted({v for v in values if v and v not in universe})
        assert missing == [], label

    e, r, t, m, q = (raw[k] for k in ["employees", "reports", "tables", "metrics", "requests"])
    check(e["manager_id"], emp, "employees.manager_id")
    check(e["successor_id"], emp, "employees.successor_id")
    check(r["owner_id"], emp, "reports.owner_id")
    check(r["replaced_by_report_id"], reports, "reports.replaced_by_report_id")
    check(t["owner_id"], emp, "tables.owner_id")
    check(m["owner_id"], emp, "metrics.owner_id")
    check(q["requester_id"], emp, "requests.requester_id")
    check(q["assignee_id"], emp, "requests.assignee_id")
    check(q["resulting_report_id"], reports, "requests.resulting_report_id")
    check(q["duplicate_of_request_id"], requests_, "requests.duplicate_of_request_id")
    sources = [tid for raw_list in m["source_table_ids"] for tid in json.loads(raw_list)]
    check(sources, tables, "metrics.source_table_ids")
    check(raw["report_table_edges"]["report_id"], reports, "report_table_edges.report_id")
    check(raw["report_table_edges"]["table_id"], tables, "report_table_edges.table_id")
    check(raw["table_table_edges"]["parent_table_id"], tables, "table_table_edges.parent")
    check(raw["table_table_edges"]["child_table_id"], tables, "table_table_edges.child")


# ------------------------------------------------------------------ I03 manager tree


def test_I03_manager_tree_single_root_acyclic_and_connected(emp):
    roots = [eid for eid, row in emp.items() if not row["manager_id"]]
    assert roots == ["EMP-001"]
    for eid in emp:
        seen, current = set(), eid
        while emp[current]["manager_id"]:
            assert current not in seen, f"cycle through {current}"
            seen.add(current)
            current = emp[current]["manager_id"]
        assert current == "EMP-001"


def test_I03_managers_of_left_employees_are_active(emp):
    # A left employee's manager is the fallback contact for S2 chains, so it must be reachable.
    for row in emp.values():
        if row["status"] == "left":
            assert emp[row["manager_id"]]["status"] == "active"


# ------------------------------------------------------------------ I04 status consistency


def test_I04_status_dates_and_successor_are_consistent(emp):
    for eid, row in emp.items():
        start = d(row["start_date"])
        assert date(2016, 1, 1) <= start <= date(2026, 6, 30), eid
        if row["status"] == "left":
            assert row["left_date"], eid
            left = d(row["left_date"])
            assert start < left <= REFERENCE_DATE, eid
        else:
            assert row["status"] == "active", eid
            assert not row["left_date"], eid
            assert not row["successor_id"], eid
        assert row["successor_id"] != eid


def test_I04_successor_starts_within_60_days_of_predecessor_leaving(emp):
    for eid, row in emp.items():
        if row["successor_id"]:
            successor = emp[row["successor_id"]]
            limit = d(row["left_date"]) + timedelta(days=60)
            assert d(successor["start_date"]) <= limit, eid


# ------------------------------------------------------------------ I05 succession structures


def test_I05_simple_successor_structures(emp, meta):
    s1 = meta["chains"]["S1"]
    assert len(s1) == 12
    for eid in s1:
        assert reference_walk(emp, eid) == (True, 1, ["successor"])


def test_I05_manager_fallback_structures(emp, meta):
    s2 = meta["chains"]["S2"]
    assert len(s2) == 6
    for eid in s2:
        assert not emp[eid]["successor_id"]
        assert reference_walk(emp, eid) == (True, 1, ["manager"])


@pytest.mark.parametrize(("code", "n_chains", "length"), [("C2", 3, 2), ("C3", 2, 3), ("C4", 2, 4)])
def test_I05_chains_are_linked_by_successors(emp, meta, code, n_chains, length):
    chains = meta["chains"][code]
    assert len(chains) == n_chains
    for chain in chains:
        assert len(chain) == length
        assert all(emp[eid]["status"] == "left" for eid in chain)
        for current, nxt in zip(chain, chain[1:], strict=False):
            assert emp[current]["successor_id"] == nxt


def test_I05_chain_depths_match_spec(emp, meta):
    c2_vias = sorted(tuple(reference_walk(emp, chain[0])[2]) for chain in meta["chains"]["C2"])
    assert c2_vias == [
        ("successor", "manager"),
        ("successor", "successor"),
        ("successor", "successor"),
    ]
    for chain in meta["chains"]["C2"]:
        assert reference_walk(emp, chain[0])[:2] == (True, 2)
    for chain in meta["chains"]["C3"]:
        assert reference_walk(emp, chain[0]) == (True, 3, ["successor"] * 3)
    for chain in meta["chains"]["C4"]:
        resolved, hops, _ = reference_walk(emp, chain[0])
        assert (resolved, hops) == (False, 3)


def test_I05_exactly_38_left_and_all_belong_to_a_structure(emp, meta):
    chains = meta["chains"]
    members = list(chains["S1"]) + list(chains["S2"])
    for code in ("C2", "C3", "C4"):
        for chain in chains[code]:
            members.extend(chain)
    left = sorted(eid for eid, row in emp.items() if row["status"] == "left")
    assert len(left) == 38
    assert len(members) == len(set(members))
    assert sorted(members) == left


def test_I05_eval_split_matches_spec(emp, meta):
    assert meta["eval_split"] == {
        "C2": ["test", "test", "dev"],
        "C3": ["test", "dev"],
        "C4": ["test", "dev"],
    }
    # The test split must cover both C2 variants (successor->successor and successor->manager).
    test_vias = {
        tuple(reference_walk(emp, chain[0])[2])
        for chain, split in zip(meta["chains"]["C2"], meta["eval_split"]["C2"], strict=True)
        if split == "test"
    }
    assert test_vias == {("successor", "successor"), ("successor", "manager")}


# ------------------------------------------------------------------ I06 department heads


def test_I06_one_active_head_per_department(emp):
    for dept in Department:
        heads = [
            eid
            for eid, row in emp.items()
            if row["department"] == dept.value and row["is_department_head"] == "true"
        ]
        assert len(heads) == 1, dept
        assert emp[heads[0]]["status"] == "active"
    assert emp["EMP-001"]["department"] == "Operations"
    assert emp["EMP-001"]["is_department_head"] == "true"
    for row in emp.values():
        if row["is_department_head"] == "true" and row["employee_id"] != "EMP-001":
            assert row["manager_id"] == "EMP-001"


# ------------------------------------------------------------------ I07 chain heads own reports


def test_I07_chain_heads_own_at_least_two_active_reports(raw, meta):
    chains = meta["chains"]
    heads = list(chains["S1"]) + list(chains["S2"])
    heads += [chain[0] for code in ("C2", "C3", "C4") for chain in chains[code]]
    active = raw["reports"][raw["reports"]["status"] == "active"]
    counts = active["owner_id"].value_counts()
    for eid in heads:
        assert counts.get(eid, 0) >= 2, eid


# ------------------------------------------------------------------ I08 layers and lineage DAG


def test_I08_layer_counts_and_name_prefixes(tables):
    layers = pd.Series([row["layer"] for row in tables.values()]).value_counts().to_dict()
    assert layers == {"staging": 30, "intermediate": 25, "mart": 25}
    prefixes = {"staging": ("stg_",), "intermediate": ("int_",), "mart": ("fct_", "dim_")}
    for row in tables.values():
        assert row["name"].startswith(prefixes[row["layer"]]), row["name"]
        if row["layer"] == "staging":
            assert row["source_system"] in {"DMS", "ERP", "CRM", "WMS", "WARRANTY", "WEB"}
            assert row["schema_name"] == "staging"
        else:
            assert row["source_system"] == "warehouse"
    assert len({row["name"] for row in tables.values()}) == 80


def test_I08_table_edge_directions_follow_spec(raw, tables):
    edges = raw["table_table_edges"]
    staging_to_mart = 0
    for parent, child in zip(edges["parent_table_id"], edges["child_table_id"], strict=True):
        pair = (tables[parent]["layer"], tables[child]["layer"])
        if pair == ("intermediate", "intermediate"):
            assert parent < child, (parent, child)
        elif pair == ("staging", "mart"):
            staging_to_mart += 1
        else:
            assert pair in {("staging", "intermediate"), ("intermediate", "mart")}, pair
    assert staging_to_mart <= 0.10 * len(edges)


def test_I08_lineage_graph_is_a_dag(raw):
    g = nx.DiGraph()
    g.add_edges_from(
        zip(
            raw["table_table_edges"]["parent_table_id"],
            raw["table_table_edges"]["child_table_id"],
            strict=True,
        )
    )
    g.add_edges_from(
        zip(
            raw["report_table_edges"]["table_id"],
            raw["report_table_edges"]["report_id"],
            strict=True,
        )
    )
    for metric_id, sources in zip(
        raw["metrics"]["metric_id"], raw["metrics"]["source_table_ids"], strict=True
    ):
        g.add_edges_from((tid, metric_id) for tid in json.loads(sources))
    assert nx.is_directed_acyclic_graph(g)


def test_I08_required_mart_tables_exist(tables):
    names = {row["name"]: row["layer"] for row in tables.values()}
    required = [
        "dim_customer", "dim_vehicle", "dim_dealer", "dim_region", "dim_date",
        "fct_vehicle_sales", "fct_service_orders", "fct_parts_sales", "fct_warranty_claims",
        "fct_returns", "fct_leads", "fct_inventory_snapshot", "fct_budget_2026",
    ]  # fmt: skip
    for name in required:
        assert names.get(name) == "mart", name


# ------------------------------------------------------------------ I09 report -> table edges


def test_I09_every_report_has_one_to_five_tables(raw):
    per_report = raw["report_table_edges"].groupby("report_id").size()
    assert set(per_report.index) == set(raw["reports"]["report_id"])
    assert per_report.min() >= 1
    assert per_report.max() <= 5


def test_I09_report_edges_point_to_marts_not_staging(raw, tables):
    layers = [tables[tid]["layer"] for tid in raw["report_table_edges"]["table_id"]]
    assert layers.count("staging") == 0
    assert layers.count("mart") >= 0.90 * len(layers)


# ------------------------------------------------------------------ I10 lineage coverage


def test_I10_parents_and_children_exist(raw, tables):
    edges = raw["table_table_edges"]
    children = set(edges["child_table_id"])
    parents = set(edges["parent_table_id"])
    for tid, row in tables.items():
        if row["layer"] in {"intermediate", "mart"}:
            assert tid in children, row["name"]
    staging = [tid for tid, row in tables.items() if row["layer"] == "staging"]
    with_child = [tid for tid in staging if tid in parents]
    assert len(with_child) >= 0.90 * len(staging)


# ------------------------------------------------------------------ I11 metrics


def test_I11_metric_sources_formulas_and_aliases(raw, tables, meta):
    metrics = raw["metrics"]
    for row in metrics.to_dict("records"):
        sources = json.loads(row["source_table_ids"])
        assert 1 <= len(sources) <= 3, row["metric_id"]
        assert all(tables[tid]["layer"] == "mart" for tid in sources), row["metric_id"]
        assert [a for a in row["aliases"].split("|") if a.strip()], row["metric_id"]
    null_formula = sorted(metrics.loc[metrics["formula"] == "", "metric_id"])
    assert len(null_formula) == 3
    assert null_formula == sorted(meta["null_formula_metrics"])


# ------------------------------------------------------------------ I12 dates


def test_I12_report_dates_respect_owner_tenure(reports, emp):
    for rid, row in reports.items():
        owner = emp[row["owner_id"]]
        created = d(row["created_date"])
        assert created >= d(owner["start_date"]), rid
        if owner["status"] == "left":
            assert created < d(owner["left_date"]), rid
        assert created <= d(row["last_refresh"]) <= REFERENCE_DATE, rid


def test_I12_request_dates_are_consistent(requests_, reports):
    for qid, row in requests_.items():
        created = d(row["created_date"])
        assert date(2021, 1, 1) <= created <= REFERENCE_DATE, qid
        if row["status"] in {"open", "in_progress"}:
            assert not row["closed_date"], qid
        else:
            assert row["closed_date"], qid
            assert created <= d(row["closed_date"]) <= REFERENCE_DATE, qid
        if row["resulting_report_id"]:
            assert d(reports[row["resulting_report_id"]]["created_date"]) >= created, qid


def test_I12_request_ids_follow_creation_order(raw):
    ordered = raw["requests"].sort_values("request_id")["created_date"].tolist()
    assert ordered == sorted(ordered)


# ------------------------------------------------------------------ I13 deprecated reports


def test_I13_deprecated_reports_and_replacements(raw, reports, meta):
    deprecated = {rid: row for rid, row in reports.items() if row["status"] == "deprecated"}
    assert len(deprecated) == 15
    edges = raw["report_table_edges"].groupby("report_id")["table_id"].apply(set).to_dict()
    for rid, row in reports.items():
        assert bool(row["replaced_by_report_id"]) == (row["status"] == "deprecated"), rid
    for rid, row in deprecated.items():
        replacement = reports[row["replaced_by_report_id"]]
        assert replacement["status"] == "active", rid
        assert not replacement["replaced_by_report_id"], rid
        assert edges[rid] & edges[replacement["report_id"]], rid
        assert row["refresh_status"] == "disabled", rid
    assert meta["deprecated_map"] == {
        rid: row["replaced_by_report_id"] for rid, row in deprecated.items()
    }


# ------------------------------------------------------------------ I14 near duplicates


def test_I14_near_duplicate_pairs(reports, meta):
    pairs = meta["near_duplicate_pairs"]
    assert len(pairs) == 20
    members = [rid for pair in pairs for rid in pair]
    assert len(members) == len(set(members)) == 40
    for a, b in pairs:
        assert jaccard(reports[a]["name"], reports[b]["name"]) >= 0.5, (a, b)
        assert reports[a]["name"] != reports[b]["name"]


# ------------------------------------------------------------------ I15 requests


def test_I15_request_status_ratios(raw):
    shares = raw["requests"]["status"].value_counts(normalize=True).to_dict()
    expected = {
        "done": 0.55,
        "duplicate": 0.13,
        "open": 0.12,
        "rejected": 0.10,
        "in_progress": 0.10,
    }
    assert set(shares) == set(expected)
    for status, share in expected.items():
        assert abs(shares[status] - share) <= 0.03, status


def test_I15_duplicates_point_to_earlier_request_in_same_cluster(requests_, meta):
    topic = meta["request_topic_keys"]
    assert set(topic) == set(requests_)
    for qid, row in requests_.items():
        assert bool(row["duplicate_of_request_id"]) == (row["status"] == "duplicate"), qid
        if row["duplicate_of_request_id"]:
            original = requests_[row["duplicate_of_request_id"]]
            assert d(original["created_date"]) < d(row["created_date"]), qid
            assert topic[original["request_id"]] == topic[qid], qid


def test_I15_resulting_reports_only_on_done_requests(requests_):
    done = [row for row in requests_.values() if row["status"] == "done"]
    for row in requests_.values():
        if row["resulting_report_id"]:
            assert row["status"] == "done", row["request_id"]
    with_result = sum(1 for row in done if row["resulting_report_id"])
    assert 0.70 <= with_result / len(done) <= 0.80


# ------------------------------------------------------------------ I16 reserved near-miss pool


def test_I16_reserved_fragments_never_generated(raw):
    reserved = json.loads((VOCAB_DIR / "reserved_near_miss.json").read_text(encoding="utf-8"))
    names = (
        list(raw["reports"]["name"]) + list(raw["tables"]["name"]) + list(raw["metrics"]["name"])
    )
    for fragment in reserved["report_name_fragments"]:
        assert not [n for n in names if fragment.lower() in n.lower()], fragment
    texts = list(raw["requests"]["title"]) + list(raw["requests"]["description"])
    texts += list(raw["reports"]["name"]) + list(raw["reports"]["description"])
    for topic in reserved["unused_request_topics"]:
        for keyword in topic["keywords"]:
            assert not [t for t in texts if keyword.lower() in t.lower()], keyword


def test_I16_only_one_budget_table(tables):
    budget = sorted(row["name"] for row in tables.values() if "budget" in row["name"])
    assert budget == ["fct_budget_2026"]


# ------------------------------------------------------------------ noise checks (spec §4.5)


def test_N3_abbreviation_tags_on_at_least_40_reports(raw):
    tagged = [tags for tags in raw["reports"]["tags"] if set(tags.split("|")) & ABBREVIATION_TAGS]
    assert len(tagged) >= 40


def test_N4_ten_percent_vague_descriptions(reports, meta):
    vague = meta["vague_description_reports"]
    assert len(vague) == 25
    for rid in vague:
        shared = tokens(reports[rid]["name"]) & tokens(reports[rid]["description"])
        assert shared <= VAGUE_STOPWORDS, (rid, shared)


def test_N5_about_eight_percent_of_active_reports_failed(raw):
    active = raw["reports"][raw["reports"]["status"] == "active"]
    share = (active["refresh_status"] == "failed").mean()
    assert 0.06 <= share <= 0.10
    assert set(active["refresh_status"]) <= {"success", "failed"}


def test_N6_request_topic_clusters(meta):
    sizes = pd.Series(meta["request_topic_keys"]).value_counts()
    assert len(sizes) == 60
    assert sizes.min() >= 2
    assert sizes.max() <= 8


def test_N7_null_formula_trap_metrics_exist(raw):
    assert (raw["metrics"]["formula"] == "").sum() == 3


# ------------------------------------------------------------------ extra realism checks


def test_X_report_names_unique_and_tags_bounded(raw):
    assert raw["reports"]["name"].is_unique
    tag_counts = raw["reports"]["tags"].str.split("|").map(len)
    assert tag_counts.between(1, 5).all()


def test_X_report_department_mostly_matches_owner(raw, emp):
    same = [
        emp[owner]["department"] == dept
        for owner, dept in zip(
            raw["reports"]["owner_id"], raw["reports"]["department"], strict=True
        )
    ]
    assert 0.78 <= sum(same) / len(same) <= 0.92


def test_X_usage_long_tail(raw):
    usage = raw["reports"]["usage_30d"].astype(int)
    active = raw["reports"]["status"] == "active"
    assert 0.15 <= (usage[active] == 0).mean() <= 0.25
    assert usage[~active].max() <= 5
    assert usage.max() > 10 * max(usage.median(), 1)


def test_X_descriptions_have_one_to_three_sentences(raw):
    for text in list(raw["reports"]["description"]) + list(raw["requests"]["description"]):
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]
        assert 1 <= len(sentences) <= 3, text


def test_X_table_owners_mostly_data_and_analytics(raw, emp):
    owners = [emp[o]["department"] for o in raw["tables"]["owner_id"]]
    assert owners.count("Data & Analytics") >= 0.70 * len(owners)


def test_X_table_columns_are_valid_json(raw):
    for text in raw["tables"]["columns_json"]:
        columns = json.loads(text)
        assert 4 <= len(columns) <= 15
        assert all(set(c) == {"name", "type"} for c in columns)


def test_X_request_people_were_employed_and_assignees_mostly_data_team(requests_, emp):
    dna = 0
    for qid, row in requests_.items():
        created = d(row["created_date"])
        for key in ("requester_id", "assignee_id"):
            person = emp[row[key]]
            assert d(person["start_date"]) <= created, (qid, key)
            if person["status"] == "left":
                assert created < d(person["left_date"]), (qid, key)
        assert row["requester_id"] != row["assignee_id"], qid
        assert row["department"] == emp[row["requester_id"]]["department"], qid
        dna += emp[row["assignee_id"]]["department"] == "Data & Analytics"
    assert dna >= 0.80 * len(requests_)


def test_X_titles_vary_within_request_clusters(requests_, meta):
    by_topic: dict[str, list[str]] = {}
    for qid, key in meta["request_topic_keys"].items():
        by_topic.setdefault(key, []).append(requests_[qid]["title"])
    for key, titles in by_topic.items():
        assert len(set(titles)) >= min(len(titles), 2), key
