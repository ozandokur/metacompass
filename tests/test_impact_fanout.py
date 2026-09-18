"""The impact fan-out diagnostic (eval/run_impact_fanout.py) that Phase 5 uses to pick L5
targets: one row per table, and a summary that adds up."""

import run_impact_fanout as fanout_script


def test_fanout_rows_on_the_mini_fixture(mini_ctx):
    result = fanout_script.fanout(mini_ctx)
    rows = {row["table_id"]: row for row in result["tables"]}
    assert sorted(rows) == [f"TBL-00{i}" for i in range(1, 9)]
    assert rows["TBL-004"] == {
        "table_id": "TBL-004",
        "name": "int_sales_by_dealer",
        "layer": "intermediate",
        "notify_mode": "individual",
        "notify_total_count": 3,
        "affected_report_count": 6,
        "affected_metric_count": 2,
        "payload_chars": rows["TBL-004"]["payload_chars"],
        "truncated": False,
    }
    assert rows["TBL-008"]["notify_total_count"] == 0  # nothing reads stg_unused


def test_fanout_summary_adds_up(real_ctx):
    result = fanout_script.fanout(real_ctx)
    summary, rows = result["summary"], result["tables"]
    assert summary["tables"] == len(rows) == 80
    assert summary["individual"] + summary["broadcast"] == 80
    assert summary["broadcast"] == sum(r["notify_mode"] == "broadcast" for r in rows)
    by_layer = summary["by_layer"]
    assert sum(v["individual"] + v["broadcast"] for v in by_layer.values()) == 80
    assert summary["max_payload_chars"] == max(r["payload_chars"] for r in rows)
