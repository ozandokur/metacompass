"""Audits the raw test-set result files before any report is written (V6).

    python scripts/audit_eval.py            # exit 0 when every hard check holds

Hard checks, each a failure when broken:
  - one identity per file: (model, API version, prompt version, frozen tree hash)
  - every line sits in the file its config and repeat name, and answers a test question
  - no question answered twice in one file
  - every stored score is what scoring.py gives the stored answer today
  - quota log: no day above the daily limit the provider enforced, and no day whose result
    lines hold clearly more model calls than the provider received that day; that would mean
    answers came from a cache shared across repeats instead of the model
Counted, not failed: answers the plan still waits for, and answers that ended in llm_error.
A run in progress is expected to have missing answers; a report is only final with none.
"""

import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
from configs import CATEGORIES, REPEATS  # noqa: E402
from runinfo import RUN_IDENTITY  # noqa: E402
from scoring import score  # noqa: E402

FILE_NAME = re.compile(r"test_(A\d)_r(\d+)\.jsonl")
# A question the quota stopped halfway is finished the next day and replays its first turns
# from the cache, so a day may hold a few more model calls than requests; a shared cache
# across repeats would hold many more.
REPLAY_ALLOWANCE = 1.10
REPLAY_SLACK = 10


@dataclass
class Audit:
    failures: list[str] = field(default_factory=list)
    missing: dict[tuple[str, int], int] = field(default_factory=dict)
    llm_errors: int = 0
    answers: int = 0


def _llm_calls(line: dict) -> int:
    return sum(step["kind"] == "llm" for step in line["result"]["steps"])


def audit(
    results: Path,
    items: list[dict],
    repeats: dict[str, int] = REPEATS,
    categories: dict[str, tuple[str, ...]] = CATEGORIES,
) -> Audit:
    report = Audit()
    by_id = {item["id"]: item for item in items}
    answered: dict[tuple[str, int], set[str]] = defaultdict(set)
    calls_per_day: Counter = Counter()
    for path in sorted(results.glob("test_*.jsonl")):
        match = FILE_NAME.fullmatch(path.name)
        if not match:
            report.failures.append(f"{path.name}: not a <set>_<config>_r<repeat> file name")
            continue
        config, repeat = match[1], int(match[2])
        lines = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines() if row]
        identities = {tuple(line.get(key) for key in RUN_IDENTITY) for line in lines}
        if len(identities) > 1:
            report.failures.append(
                f"{path.name}: {len(identities)} identities {sorted(identities)}"
            )
        seen = Counter(line["item_id"] for line in lines)
        twice = sorted(item_id for item_id, n in seen.items() if n > 1)
        if twice:
            report.failures.append(f"{path.name}: answered twice: {twice}")
        for line in lines:
            where = f"{path.name} {line['item_id']}"
            if (line["config"], line["repeat"]) != (config, repeat):
                report.failures.append(f"{where}: config/repeat differ from the file name")
            item = by_id.get(line["item_id"])
            if item is None:
                report.failures.append(f"{where}: not a test question")
                continue
            if score(item, line["result"]["answer"]) != line["score"]:
                report.failures.append(f"{where}: stored score differs from a fresh scoring")
            report.llm_errors += line["result"]["stopped_reason"] == "llm_error"
            calls_per_day[line["date"]] += _llm_calls(line)
            answered[(config, repeat)].add(line["item_id"])
            report.answers += 1
    for config, n_repeats in repeats.items():
        wanted = {item["id"] for item in items if item["category"] in categories[config]}
        for repeat in range(1, n_repeats + 1):
            report.missing[(config, repeat)] = len(wanted - answered[(config, repeat)])
    report.failures += _quota_failures(results / "quota_log.json", calls_per_day)
    return report


def _quota_failures(path: Path, calls_per_day: Counter) -> list[str]:
    if not path.is_file():
        return ["quota_log.json is missing"]
    log = json.loads(path.read_text(encoding="utf-8"))
    days, limit = log.get("days", {}), log.get("observed_rpd")
    failures = []
    for day, used in sorted(days.items()):
        if limit is not None and used["requests"] > limit:
            failures.append(f"quota {day}: {used['requests']} requests, over the limit {limit}")
    for day, calls in sorted(calls_per_day.items()):
        requests = days.get(day, {}).get("requests", 0)
        if calls > requests * REPLAY_ALLOWANCE + REPLAY_SLACK:
            failures.append(
                f"quota {day}: result lines hold {calls} model calls but the provider received "
                f"{requests} requests; answers may come from a cache shared across repeats"
            )
    return failures


def main() -> int:
    items = json.loads((ROOT / "eval" / "test_set.json").read_text(encoding="utf-8"))["items"]
    report = audit(ROOT / "eval" / "results", items)
    missing = {f"{c} r{r}": n for (c, r), n in sorted(report.missing.items()) if n}
    print(
        f"{report.answers} answers · llm_error {report.llm_errors} · missing by plan {missing or 'none'}"
    )
    for failure in report.failures:
        print(f"FAIL {failure}")
    print("audit: " + ("PASSED" if not report.failures else "FAILED"))
    return 0 if not report.failures else 1


if __name__ == "__main__":
    sys.exit(main())
