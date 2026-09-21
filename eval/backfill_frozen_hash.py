"""Adds frozen_tree_hash to result lines written before the runner recorded it (V0).

    python eval/backfill_frozen_hash.py

Every line carries the git SHA it was written under, so its frozen tree hash can be
recomputed from that commit (runinfo.frozen_tree_hash). A "-dirty" suffix is dropped: it
marks uncommitted changes, and in this run those were result files and notes, never the
frozen code (PROGRESS records it). Each line gets the hash of its own commit, not today's,
and is marked frozen_tree_hash_backfilled so the report can say the value was added later.
Lines that already have a hash are left alone.
"""

import json
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from runinfo import ROOT, frozen_tree_hash


def backfill(lines: list[dict], hash_at: Callable[[str], str]) -> list[dict]:
    out = []
    for line in lines:
        if "frozen_tree_hash" not in line:
            commit = line["git_sha"].removesuffix("-dirty")
            line = {
                **line,
                "frozen_tree_hash": hash_at(commit),
                "frozen_tree_hash_backfilled": True,
            }
        out.append(line)
    return out


def backfill_file(path: Path, hash_at: Callable[[str], str]) -> dict[str, int]:
    rows = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines() if row]
    rows = backfill(rows, hash_at)
    text = "".join(json.dumps(row) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8", newline="\n")
    return dict(Counter(row["frozen_tree_hash"] for row in rows))


def main() -> int:
    cache: dict[str, str] = {}

    def hash_at(commit: str) -> str:
        if commit not in cache:
            cache[commit] = frozen_tree_hash(ROOT, commit=commit)
        return cache[commit]

    for path in sorted((ROOT / "eval" / "results").glob("test_*.jsonl")):
        print(f"{path.name}: {backfill_file(path, hash_at)}")
    print("hash per commit:", cache)
    return 0


if __name__ == "__main__":
    sys.exit(main())
