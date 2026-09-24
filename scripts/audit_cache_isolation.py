"""V12: checks that each configuration got its own answers from the model (phase 8).

    python scripts/audit_cache_isolation.py     # exit 0 when every configuration is isolated

The LLM cache is keyed by the whole request plus a salt. While the salt carried only the
repeat number, two configurations that send the same first request shared the same cached
conversation, so an ablation could be scored on the full system's answers without ever
calling the model. The salt now carries the configuration too; this audit is what would have
caught that, and what keeps catching it.

**What a spent request looks like.** A cached model call returns without a network round
trip, so it is orders of magnitude faster. When this was written the model steps fell into
two groups with nothing in between: one step at 1 ms, then 98 between 200 and 999 ms and 1169
above a second. A step under 50 ms therefore came from the cache and spent nothing. The two
sides of that line are measured on every run and reported, so the claim that the gap is wide
stays checkable instead of becoming folklore.

**What is and is not evidence.** Two configurations answering the same question with the same
answer is ordinary. Even the same tool trace is ordinary: A1 only swaps the retrieval mode, so
the model's first request is byte for byte the full system's, and an easy lookup can lead to
the same call with the same argument. What cannot be explained away is a configuration that
produced answers without spending requests. The identical-trace share is therefore reported
as a number to read, and the failure is on the requests a configuration actually spent: below
half of A0's rate per answer it is not measuring itself.
"""

import json
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

# The Windows console is not UTF-8 here; the summary holds · and ≥.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
FILE_NAME = re.compile(r"test_(A\d)_r(\d+)\.jsonl")
CACHE_MS = 50  # a model step faster than this was served from the cache, not the provider
FAST_ANSWER_MS = 500  # a whole answer this quick cannot have made a real call
BASELINE = "A0"  # the full system: every other configuration is compared with its rate
RATE_FLOOR = 0.5  # of the baseline's requests per answer


@dataclass
class ConfigStats:
    """What one configuration spent to get its answers."""

    config: str
    answers: int = 0
    requests: int = 0
    free_answers: int = 0  # answers that spent no request at all
    fast_answers: int = 0  # answers that came back under FAST_ANSWER_MS
    latencies: list[int] = field(default_factory=list)

    @property
    def per_answer(self) -> float:
        return self.requests / self.answers if self.answers else 0.0

    @property
    def median_latency_ms(self) -> int:
        return round(statistics.median(self.latencies)) if self.latencies else 0


@dataclass
class Isolation:
    stats: dict[str, ConfigStats] = field(default_factory=dict)
    comparable: int = 0  # questions answered by more than one configuration
    shared_traces: int = 0  # of those, how many have two configurations with the same trace
    failures: list[str] = field(default_factory=list)
    # The two sides of the threshold as the data actually shows them, so the page states a
    # measured gap instead of repeating a claim that a later run could quietly falsify.
    slowest_cached_ms: int | None = None
    fastest_live_ms: int | None = None


def requests_spent(line: dict) -> int:
    """Model calls that went to the provider; a cached one returns too fast to have."""
    return sum(
        step["kind"] == "llm" and step["duration_ms"] >= CACHE_MS
        for step in line["result"]["steps"]
    )


def trace(line: dict) -> tuple[tuple[str, str], ...]:
    """The tools called, with their arguments, in order. Durations and outputs are left out."""
    return tuple(
        (step["name"], json.dumps(step["arguments"], sort_keys=True))
        for step in line["result"]["steps"]
        if step["kind"] == "tool"
    )


def _read(results: Path) -> list[dict]:
    lines = []
    for path in sorted(results.glob("test_A*_r*.jsonl")):
        if not FILE_NAME.fullmatch(path.name):
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                lines.append(json.loads(raw))
    return lines


def isolation(results: Path) -> Isolation:
    report = Isolation()
    lines = _read(results)
    traces: dict[str, dict[str, set[tuple]]] = {}
    for line in lines:
        stats = report.stats.setdefault(line["config"], ConfigStats(line["config"]))
        stats.answers += 1
        spent = requests_spent(line)
        stats.requests += spent
        stats.free_answers += spent == 0
        latency = line["result"]["latency_ms"]
        stats.latencies.append(latency)
        stats.fast_answers += latency < FAST_ANSWER_MS
        traces.setdefault(line["item_id"], {}).setdefault(line["config"], set()).add(trace(line))
        for step in line["result"]["steps"]:
            if step["kind"] != "llm":
                continue
            if step["duration_ms"] < CACHE_MS:
                report.slowest_cached_ms = max(report.slowest_cached_ms or 0, step["duration_ms"])
            else:
                report.fastest_live_ms = min(
                    report.fastest_live_ms if report.fastest_live_ms is not None else 10**9,
                    step["duration_ms"],
                )

    for by_config in traces.values():
        if len(by_config) < 2:
            continue  # only one configuration answered it; nothing to compare
        report.comparable += 1
        seen: list[set[tuple]] = list(by_config.values())
        if any(a & b for i, a in enumerate(seen) for b in seen[i + 1 :]):
            report.shared_traces += 1

    baseline = report.stats.get(BASELINE)
    if baseline is None or not baseline.answers:
        report.failures.append(f"no {BASELINE} answers to compare the other rates with")
        return report
    floor = baseline.per_answer * RATE_FLOOR
    for config, stats in sorted(report.stats.items()):
        if config == BASELINE:
            continue
        if stats.per_answer < floor:
            report.failures.append(
                f"{config} spent {stats.per_answer:.2f} requests per answer, under half of "
                f"{BASELINE}'s {baseline.per_answer:.2f}; its answers may come from a shared cache"
            )
    return report


def markdown(report: Isolation) -> list[str]:
    """The per-configuration evidence, for the results page: what each one spent to answer."""
    rows = [
        "| Config | Answers | Requests | Per answer | Median latency | Free | Under 500 ms |",
        "|---|---|---|---|---|---|---|",
    ]
    for config, stats in sorted(report.stats.items()):
        rows.append(
            f"| {config} | {stats.answers} | {stats.requests} | {stats.per_answer:.2f} | "
            f"{stats.median_latency_ms / 1000:.1f} s | {stats.free_answers} | "
            f"{stats.fast_answers} |"
        )
    share = f"{report.shared_traces} of {report.comparable}" if report.comparable else "none"
    cached = report.slowest_cached_ms
    live = report.fastest_live_ms
    gap = (
        f"the slowest cache-served call took {cached} ms and the fastest call that reached the "
        f"provider {live} ms"
        if cached is not None and live is not None
        else f"no call has yet landed on both sides of the {CACHE_MS} ms line"
    )
    rows += [
        "",
        f"A request is a model call that reached the provider: a cached one returns without a "
        f"network round trip, so the line is drawn at {CACHE_MS} ms. In these runs {gap}, which "
        f"is the gap the threshold sits in. *Free* counts answers that spent no request at all, "
        f"which is what a configuration scored on another's cached answers would look like. "
        f"A configuration under half of {BASELINE}'s rate per answer is refused.",
        "",
        f"Questions answered by more than one configuration where two produced the same tool "
        f"trace: **{share}**. This is deliberately not a failure condition. A1 only swaps the "
        f"retrieval mode, so the model's first request is the full system's byte for byte and "
        f"the same call often follows; the share above was measured on runs that each spent "
        f"their own requests. What cannot be explained is a configuration that answered without "
        f"spending any.",
    ]
    return rows


def table(report: Isolation) -> list[str]:
    """The same numbers on the console, one line per configuration."""
    rows = ["config · answers · requests · per answer · median latency · free · under 500 ms"]
    for config, stats in sorted(report.stats.items()):
        rows.append(
            f"{config} · {stats.answers} · {stats.requests} · {stats.per_answer:.2f} · "
            f"{stats.median_latency_ms / 1000:.1f} s · {stats.free_answers} · {stats.fast_answers}"
        )
    return rows


def main() -> int:
    report = isolation(ROOT / "eval" / "results")
    print("\n".join(table(report)))
    share = (
        f"{report.shared_traces}/{report.comparable}" if report.comparable else "none to compare"
    )
    print(f"same trace in more than one configuration: {share} (a number to read, not a verdict)")
    for failure in report.failures:
        print(f"FAIL {failure}")
    print("cache isolation: " + ("PASSED" if not report.failures else "FAILED"))
    return 0 if not report.failures else 1


if __name__ == "__main__":
    sys.exit(main())
