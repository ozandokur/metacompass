"""Summarise the dev prompt iterations so results.md can show them (spec §9.1 rule 4).

Every prompt version answered the same 30 dev questions once. The runs live in
eval/results/scratch/ (dev runs are not committed): prompt_v<N>/dev_A0_r1.jsonl for the
versions that were replaced, dev_A0_r1.jsonl for the one in use. This script reads them and
writes eval/results/prompt_iterations.json, so the numbers in the report come from the runs
and not from a note somebody typed. The test set is never touched here.

Usage: python eval/prompt_iterations.py [--frozen v5]
  writes eval/results/prompt_iterations.json
"""

import argparse
import json
import sys
from pathlib import Path

from runinfo import ROOT, git_sha

SCRATCH = ROOT / "eval" / "results" / "scratch"


def summarize(version: str, lines: list[dict], items: list[dict]) -> dict:
    """One version's dev run: accuracy overall and per category, abstention, cost in calls."""
    by_id = {item["id"]: item for item in items}
    by_category: dict[str, dict] = {}
    for line in lines:
        cell = by_category.setdefault(line["category"], {"correct": 0, "n": 0})
        cell["correct"] += bool(line["score"]["correct"])
        cell["n"] += 1
    should = [line for line in lines if by_id[line["item_id"]]["gold"]["should_abstain"]]
    did = [line for line in lines if line["result"]["answer"]["abstained"]]
    right_abstentions = [line for line in did if by_id[line["item_id"]]["gold"]["should_abstain"]]
    calls = sum(sum(s["kind"] == "llm" for s in line["result"]["steps"]) for line in lines)
    return {
        "version": version,
        "answers": len(lines),
        "accuracy": sum(bool(line["score"]["correct"]) for line in lines) / len(lines),
        "by_category": dict(sorted(by_category.items())),
        "abstain_precision": len(right_abstentions) / len(did) if did else None,
        "abstain_recall": len(right_abstentions) / len(should) if should else None,
        "calls_per_answer": calls / len(lines),
        "input_tokens_per_answer": sum(line["result"]["input_tokens"] for line in lines)
        / len(lines),
    }


def _read(path: Path, expected: str) -> list[dict]:
    lines = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines() if row]
    found = {line.get("prompt_version") for line in lines}
    if found != {expected}:
        raise ValueError(f"{path} holds prompt versions {sorted(found)}, expected {expected}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarise the dev prompt iterations.")
    parser.add_argument("--dir", type=Path, default=SCRATCH)
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "results" / "prompt_iterations.json")  # fmt: skip
    parser.add_argument("--set-file", type=Path, default=ROOT / "eval" / "dev_set.json")
    parser.add_argument("--frozen", required=True, help="the version kept for the test run")
    args = parser.parse_args(argv)
    items = json.loads(args.set_file.read_text(encoding="utf-8"))["items"]
    versions = []
    for folder in sorted(p for p in args.dir.iterdir() if p.is_dir() and p.name.startswith("prompt_v")):  # fmt: skip
        path = folder / "dev_A0_r1.jsonl"
        if path.is_file():
            version = folder.name.removeprefix("prompt_")
            versions.append(summarize(version, _read(path, version), items))
    current = args.dir / "dev_A0_r1.jsonl"
    if current.is_file():
        versions.append(summarize(args.frozen, _read(current, args.frozen), items))
    if not versions:
        print(f"no dev runs under {args.dir}", file=sys.stderr)
        return 2
    result = {
        "metadata": {"git_sha": git_sha(), "set": "dev", "questions": len(items)},
        "frozen": args.frozen,
        "versions": versions,
    }
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")

    def num(value: float | None) -> str:
        return "—" if value is None else f"{value:.2f}"

    for v in versions:
        cells = " ".join(f"{c} {x['correct']}/{x['n']}" for c, x in v["by_category"].items())
        print(
            f"{v['version']}: {v['accuracy']:.2f} overall · {cells} · abstain P "
            f"{num(v['abstain_precision'])} R {num(v['abstain_recall'])} · "
            f"{v['calls_per_answer']:.2f} calls/answer"
        )
    print(f"frozen: {args.frozen}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
