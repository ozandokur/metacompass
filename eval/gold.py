"""Independent gold answers for evaluation questions (spec §9.1, §9.4).

Gold is computed straight from the generated CSVs with pandas, never through the
metacompass tools, graph or retrieval code, so a bug in a tool cannot make its own wrong
answers count as correct (decision D14). tests/test_architecture.py enforces the imports.
Phase 2 implements the lookup and abstain specs used by the retrieval benchmark; the
ownership, lineage, past-work and impact specs arrive in Phase 5.
"""

import json
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
