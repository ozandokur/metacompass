"""The independent gold (eval/gold.py, spec §9.4, D14).

Two kinds of checks. On the mini fixture every gold_spec type is compared with answers
worked out by hand (tests/fixtures/mini/README.md). On the generated data every gold type
that has a tool counterpart is compared with that tool on all of its inputs: a mismatch
means a bug in the gold or in the tool, to be found, not papered over (Phase 5 task 3).
The import rule that keeps the gold independent is in test_architecture.py.
"""

import pytest

import gold
from metacompass.graph import neighbors_bfs
from metacompass.tools.impact import impact_analysis
from metacompass.tools.ownership import resolve_owner


@pytest.fixture(scope="module")
def mini_raw(mini_dir):
    return gold.load_raw(mini_dir)


def g(spec: dict, raw, meta=None) -> dict:
    return gold.compute_gold(spec, raw, meta or {})


# ---------------------------------------------------------------------- by hand, mini fixture


def test_current_contact(mini_raw):
    def contact(**spec):
        return g({"type": "current_contact_for_asset", **spec}, mini_raw)

    assert contact(asset_id="RPT-0001") == {
        "answer_ids": ["EMP-004"], "forbidden_ids": [], "should_abstain": False,
    }  # fmt: skip
    # S1: the owner left, so naming them is wrong.
    assert contact(asset_id="RPT-0002")["forbidden_ids"] == ["EMP-008"]
    # C4: four leavers, the Sales head is the contact.
    assert contact(asset_id="RPT-0007") == {
        "answer_ids": ["EMP-002"], "forbidden_ids": ["EMP-005"], "should_abstain": False,
    }  # fmt: skip
    # Several assets at once (MX: the owners of a metric's source tables).
    both = contact(asset_ids=["RPT-0002", "RPT-0006"])
    assert both["answer_ids"] == ["EMP-004"]
    assert both["forbidden_ids"] == ["EMP-006", "EMP-008"]


def test_upstream_tables(mini_raw):
    def up(node, depth):
        return g({"type": "upstream_tables", "node_id": node, "depth": depth}, mini_raw)[
            "answer_ids"
        ]

    assert up("MET-002", 1) == ["TBL-005", "TBL-006"]
    assert up("MET-002", 2) == ["TBL-003", "TBL-004", "TBL-005", "TBL-006"]
    assert up("RPT-0001", 6) == [f"TBL-00{i}" for i in range(1, 7)]
    assert up("RPT-0007", 2) == ["TBL-002", "TBL-003", "TBL-004"]
    assert up("TBL-004", 1) == ["TBL-002", "TBL-003"]


def test_downstream_reports(mini_raw):
    def down(table, depth):
        spec = {"type": "downstream_reports", "table_id": table, "depth": depth}
        return g(spec, mini_raw)["answer_ids"]

    assert down("TBL-001", 1) == []
    assert down("TBL-001", 2) == ["RPT-0003", "RPT-0008"]  # through fct_returns
    assert down("TBL-001", 3) == [
        "RPT-0001", "RPT-0002", "RPT-0003", "RPT-0006", "RPT-0007", "RPT-0008",
    ]  # fmt: skip
    # Deprecated RPT-0004 counts: it still breaks (only notifying its owner is skipped).
    assert down("TBL-001", 4)[-5:] == ["RPT-0004", "RPT-0005", "RPT-0006", "RPT-0007", "RPT-0008"]


def test_similar_requests(mini_raw):
    meta = {"request_topic_keys": {"REQ-0002": "returns", "REQ-0003": "returns", "REQ-0001": "x"}}
    spec = {"type": "similar_requests", "topic_key": "returns"}
    assert g(spec, mini_raw, meta)["answer_ids"] == ["REQ-0002", "REQ-0003"]


def test_impact_notify_individual_and_broadcast(mini_raw, monkeypatch):
    spec = {"type": "impact_notify", "table_id": "TBL-004"}
    assert g(spec, mini_raw) == {
        "answer_ids": ["EMP-002", "EMP-003", "EMP-004"], "forbidden_ids": [],
        "should_abstain": False,
    }  # fmt: skip
    # With a lower threshold the same three people become a broadcast to their department
    # heads: EMP-002 and EMP-004 are in Sales (head EMP-002), EMP-003 heads Data & Analytics.
    monkeypatch.setattr(gold, "NOTIFY_DETAIL_MAX", 2)
    assert g(spec, mini_raw) == {
        "answer_ids": ["EMP-002", "EMP-003"], "forbidden_ids": [], "should_abstain": False,
        "min_mentioned_count": 3,
    }  # fmt: skip


def test_chain_takes_the_last_step(mini_raw):
    spec = {
        "type": "chain",
        "use_last": True,
        "steps": [
            {
                "type": "asset_by_description",
                "target_id": "RPT-0005",
                "forbidden_ids": ["RPT-0004"],
            },
            {"type": "current_contact_for_asset", "asset_id": "RPT-0005"},
        ],
    }
    assert g(spec, mini_raw) == g(
        {"type": "current_contact_for_asset", "asset_id": "RPT-0005"}, mini_raw
    )
    broken = {**spec, "steps": [{"type": "upstream_tables", "node_id": "TBL-999", "depth": 1}]}
    with pytest.raises(ValueError):
        g(broken, mini_raw)


def test_abstain_and_unknown_types(mini_raw):
    assert g({"type": "abstain", "reason": "salary"}, mini_raw)["should_abstain"] is True
    with pytest.raises(ValueError):
        g({"type": "guess"}, mini_raw)


# ---------------------------------------------------------------------- cross-checks, real data


@pytest.fixture(scope="module")
def real_raw(generated_dir):
    return gold.load_raw(generated_dir)


def test_contacts_match_resolve_owner_on_every_asset(real_ctx, real_raw):
    store = real_ctx.store
    for asset_id in [*store.reports, *store.tables, *store.metrics]:
        tool = resolve_owner(real_ctx, asset_id)
        expected = gold.compute_gold(
            {"type": "current_contact_for_asset", "asset_id": asset_id}, real_raw, {}
        )
        assert expected["answer_ids"] == [tool.resolved_owner_id or tool.fallback_contact_id], (
            asset_id
        )


def test_upstream_tables_match_the_lineage_graph(real_ctx, real_raw):
    g_ = real_ctx.graph
    for node in [*real_ctx.store.reports, *real_ctx.store.metrics, *real_ctx.store.tables]:
        for depth in (1, 2, 3, 6):
            tool = sorted(
                n
                for n, _ in neighbors_bfs(g_, node, "upstream", depth)
                if g_.nodes[n]["type"] == "table"
            )
            spec = {"type": "upstream_tables", "node_id": node, "depth": depth}
            assert gold.compute_gold(spec, real_raw, {})["answer_ids"] == tool, (node, depth)


def test_downstream_reports_match_the_lineage_graph(real_ctx, real_raw):
    g_ = real_ctx.graph
    for table in real_ctx.store.tables:
        for depth in (1, 2, 3, 6):
            tool = sorted(
                n for n, _ in neighbors_bfs(g_, table, "downstream", depth)
                if g_.nodes[n]["type"] == "report"
            )  # fmt: skip
            spec = {"type": "downstream_reports", "table_id": table, "depth": depth}
            assert gold.compute_gold(spec, real_raw, {})["answer_ids"] == tool, (table, depth)


def test_impact_gold_matches_impact_analysis(real_ctx, real_raw):
    for table in real_ctx.store.tables:
        out = impact_analysis(real_ctx, table)
        expected = gold.compute_gold({"type": "impact_notify", "table_id": table}, real_raw, {})
        if out.notify_mode == "individual":
            assert expected["answer_ids"] == sorted(n.employee_id for n in out.notify), table
            assert "min_mentioned_count" not in expected
        else:
            heads = sorted(r.head_employee_id for r in out.notify_rollup)
            assert expected["answer_ids"] == heads, table
            assert expected["min_mentioned_count"] == out.notify_total_count, table


def test_request_clusters_cover_every_request_once(real_raw, meta):
    keys = set(meta["request_topic_keys"].values())
    seen = []
    for key in keys:
        seen += gold.compute_gold({"type": "similar_requests", "topic_key": key}, real_raw, meta)[
            "answer_ids"
        ]
    assert sorted(seen) == sorted(real_raw["requests"]["request_id"])
