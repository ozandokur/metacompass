"""One-command smoke check of a built app (V5): run inside the container or a fresh clone.

    python scripts/smoke_check.py            # exit 0 when every check passes

Checks that the image carries what the demo needs before any visitor arrives: the seven
generated tables, the precomputed document embeddings, the eight prepared answers, and a
working record lookup (the record viewer behind every ID chip). No model call, no network.
"""

import json
import sys
import time
from pathlib import Path

from metacompass.config import PROJECT_ROOT, load_settings
from metacompass.retrieval.embedders import HashEmbedder, SentenceTransformerEmbedder
from metacompass.service import build_components

TABLES = (
    "employees", "reports", "tables", "report_table_edges", "table_table_edges", "metrics",
    "requests",
)  # fmt: skip
PREPARED = 8


def checks(root: Path, embedder_name: str = "model") -> list[tuple[str, bool, str]]:
    data = root / "data"
    out = []
    missing = [t for t in TABLES if not (data / "raw" / f"{t}.csv").is_file()]
    out.append(("seven generated tables", not missing, f"missing {missing}" if missing else ""))
    cached = [p for p in (data / "cache").rglob("*") if p.is_file()] if (data / "cache").is_dir() else []  # fmt: skip
    out.append(("precomputed embeddings", bool(cached), f"{len(cached)} cache files"))
    answers = json.loads((root / "app" / "cached_answers.json").read_text(encoding="utf-8"))
    questions = answers["questions"]
    out.append(("prepared answers", len(questions) == PREPARED, f"{len(questions)} questions"))
    started = time.perf_counter()
    embedder = (
        HashEmbedder(dim=64)
        if embedder_name == "hash"
        else SentenceTransformerEmbedder(load_settings().embedding_model)
    )
    components = build_components(data, embedder)
    record_id = questions[0]["result"]["answer"]["evidence_ids"][0]
    payload, _ = components.registry.call("get_record", {"record_id": record_id})
    ok = "error" not in payload
    took = time.perf_counter() - started
    out.append(("record lookup", ok, f"{record_id} in {took:.1f} s (indices from the cache)"))
    return out


def main(argv: list[str] | None = None) -> int:
    embedder = (argv or sys.argv[1:] or ["model"])[0]
    results = checks(PROJECT_ROOT, embedder)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
    passed = all(ok for _, ok, _ in results)
    print("smoke: " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
