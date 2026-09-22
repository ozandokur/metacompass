"""Proves by a cache replay that result lines written under changed code are what the frozen
code gives (Q-V0-1).

    python eval/run_eval.py --set test --config A0 --repeat 2 --cache-only \
        --out-dir eval/results/scratch/replay_v0
    python eval/verify_replay.py

During the test run, agent/quota.py briefly held a demo reserve (b1eed88), so 158 lines of A0
carry another frozen tree hash than the freeze. The replay ran the frozen code over the same
questions with the same cache salts, answering only from the LLM cache: if that code sends
exactly the requests the original run sent, every turn comes from the cache and the answer
is the same; the smallest difference in a request is a cache miss. Each changed-code line is
compared with its replay on everything that describes the answer and how it was reached
(answer text and IDs, abstention, stop reason, every tool call with its arguments, token
counts), never on timings. An identical line is kept as it was, timings included, with the
frozen hash, an "equivalence" marker and the hash it was produced under; a line that differs
or missed the cache is removed, and the normal run answers it again. The counts go to
eval/results/replay_verification.json, from which the report states them.
"""

import json
import sys
from pathlib import Path

from runinfo import ROOT, frozen_tree_hash

OLD_HASH = "5f0ee29ab437ea65"  # b1eed88: the demo reserve in agent/quota.py
RESULTS = ROOT / "eval" / "results"
REPLAY = RESULTS / "scratch" / "replay_v0"


def _tool_calls(result: dict) -> list[tuple[str, str]]:
    return [
        (step["name"], json.dumps(step["arguments"], sort_keys=True))
        for step in result["steps"]
        if step["kind"] == "tool"
    ]


def differences(original: dict, replay: dict) -> list[str]:
    """Names of the compared fields in which a replay differs from the original line."""
    a, b = original["result"], replay["result"]
    compared = {
        "answer": (a["answer"]["answer"], b["answer"]["answer"]),
        "answer_ids": (a["answer"]["answer_ids"], b["answer"]["answer_ids"]),
        "evidence_ids": (a["answer"]["evidence_ids"], b["answer"]["evidence_ids"]),
        "abstained": (a["answer"]["abstained"], b["answer"]["abstained"]),
        "stopped_reason": (a["stopped_reason"], b["stopped_reason"]),
        "tool calls": (_tool_calls(a), _tool_calls(b)),
        "tool call count": (a["tool_calls"], b["tool_calls"]),
        "input_tokens": (a["input_tokens"], b["input_tokens"]),
        "output_tokens": (a["output_tokens"], b["output_tokens"]),
    }
    return [name for name, (x, y) in compared.items() if x != y]


def apply(originals: list[dict], replays: dict[str, dict], *, old: str, frozen: str):
    """(lines to keep, report) for one result file."""
    kept, differs, missed, identical = [], {}, [], 0
    for line in originals:
        if line["frozen_tree_hash"] != old:
            kept.append(line)  # written under the frozen code: nothing to prove
            continue
        replay = replays.get(line["item_id"])
        if replay is None:
            missed.append(line["item_id"])
            continue
        changed = differences(line, replay)
        if changed:
            differs[line["item_id"]] = changed
            continue
        identical += 1
        kept.append(
            {
                **line,
                "frozen_tree_hash": frozen,
                "frozen_tree_hash_produced": old,
                "equivalence": "cache_replay_verified",
            }
        )
    checked = identical + len(differs) + len(missed)
    report = {"checked": checked, "identical": identical, "differs": differs, "missed": missed}
    return kept, report


def _read(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines() if row]


def main_for(results: Path, replay: Path, *, old: str, frozen: str) -> dict:
    summary: dict = {"old_hash": old, "frozen_hash": frozen, "files": {}}
    for path in sorted(results.glob("test_*.jsonl")):
        originals = _read(path)
        if not any(line["frozen_tree_hash"] == old for line in originals):
            continue
        replays = {line["item_id"]: line for line in _read(replay / path.name)}
        kept, report = apply(originals, replays, old=old, frozen=frozen)
        path.write_text("".join(json.dumps(row) + "\n" for row in kept), encoding="utf-8", newline="\n")  # fmt: skip
        summary["files"][path.name] = report
    reports = summary["files"].values()
    summary["totals"] = {
        "checked": sum(r["checked"] for r in reports),
        "identical": sum(r["identical"] for r in reports),
        "differs": sum(len(r["differs"]) for r in reports),
        "missed": sum(len(r["missed"]) for r in reports),
    }
    out = results / "replay_verification.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    return summary


def main() -> int:
    frozen = frozen_tree_hash()
    summary = main_for(RESULTS, REPLAY, old=OLD_HASH, frozen=frozen)
    for name, report in summary["files"].items():
        print(f"{name}: {report['checked']} checked, {report['identical']} identical, "
              f"{len(report['differs'])} differ {report['differs'] or ''}, "
              f"{len(report['missed'])} missed {report['missed'] or ''}")  # fmt: skip
    print("totals:", summary["totals"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
