"""Impact fan-out: how far a change to each table reaches (diagnostic for D24 and Phase 5).

For every table it runs impact_analysis and records how many people would be told, how
many reports and metrics are affected, which notify mode the tool picks and how long the
JSON the LLM receives is. Phase 5 picks L5 targets from it: individual-mode tables for
the set_f1 questions and MX chains, broadcast-mode hub tables for the department-head
questions (spec §9.2).

Usage: python eval/run_impact_fanout.py [--data data/] [--out eval/results/impact_fanout.json]
"""

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from metacompass.config import NOTIFY_BROADCAST_TOP, NOTIFY_DETAIL_MAX, output_char_cap
from metacompass.data.store import MetadataStore
from metacompass.graph import build_lineage_graph
from metacompass.tools.impact import impact_analysis
from metacompass.tools.schemas import ToolContext
from runinfo import ROOT, git_sha


def fanout(ctx: ToolContext) -> dict:
    rows = []
    for table_id in sorted(ctx.store.tables):
        table, out = ctx.store.table(table_id), impact_analysis(ctx, table_id)
        rows.append(
            {
                "table_id": table_id,
                "name": table.name,
                "layer": table.layer,
                "notify_mode": out.notify_mode,
                "notify_total_count": out.notify_total_count,
                "affected_report_count": out.affected_report_count,
                "affected_metric_count": out.affected_metric_count,
                "payload_chars": len(out.model_dump_json()),
                "truncated": out.truncated,
            }
        )
    by_layer: dict[str, Counter] = {}
    for row in rows:
        by_layer.setdefault(row["layer"], Counter())[row["notify_mode"]] += 1
    modes = Counter(row["notify_mode"] for row in rows)
    summary = {
        "tables": len(rows),
        "individual": modes["individual"],
        "broadcast": modes["broadcast"],
        "by_layer": {
            layer: {"individual": c["individual"], "broadcast": c["broadcast"]}
            for layer, c in sorted(by_layer.items())
        },
        "max_payload_chars": max((row["payload_chars"] for row in rows), default=0),
        "truncated": sum(row["truncated"] for row in rows),
    }
    return {"summary": summary, "tables": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure impact fan-out for every table.")
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--out", type=Path, default=ROOT / "eval" / "results" / "impact_fanout.json"
    )
    args = parser.parse_args(argv)

    store = MetadataStore.from_dir(args.data)
    ctx = ToolContext(store=store, retrievers={}, graph=build_lineage_graph(store))
    meta = json.loads((args.data / "_meta.json").read_text(encoding="utf-8"))
    result = {
        "metadata": {
            "date": date.today().isoformat(),
            "git_sha": git_sha(),
            "data_seed": meta["seed"],
            "notify_detail_max": NOTIFY_DETAIL_MAX,
            "notify_broadcast_top": NOTIFY_BROADCAST_TOP,
            "output_char_cap": output_char_cap("impact_analysis"),
        },
        **fanout(ctx),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes((json.dumps(result, indent=2) + "\n").encode("utf-8"))
    s = result["summary"]
    print(
        f"{s['tables']} tables: {s['individual']} individual, {s['broadcast']} broadcast; "
        f"by layer {s['by_layer']}; max payload {s['max_payload_chars']} chars, "
        f"{s['truncated']} truncated"
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
