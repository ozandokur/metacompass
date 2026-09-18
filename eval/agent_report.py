"""The agent sections of results.md, computed from the runner's raw JSON lines (spec §9.7,
§9.8, §9.11).

Every number here comes from eval/results/*.jsonl (one scored AgentResult per line) joined
with the question set for the gold; nothing is typed in. Incomplete lines (the budget ran
out) are left out of every rate and counted in the notes. Cells of configurations or
categories that never ran are "—".
"""

import random
import statistics
from collections import Counter

from configs import CATEGORIES, CONFIGS

CATEGORY_ORDER = ("L1", "L2", "L3", "L4", "L5", "L6", "MX")
DASH = "—"
BOOTSTRAP_SAMPLES = 1000
BOOTSTRAP_SEED = 0


def complete(lines: list[dict]) -> list[dict]:
    return [line for line in lines if not line["incomplete"]]


def fmt(value: float | None) -> str:
    return DASH if value is None else f"{value:.2f}"


def _share(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _by_repeat(lines: list[dict]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for line in lines:
        out.setdefault(line["repeat"], []).append(line)
    return dict(sorted(out.items()))


def _accuracy(lines: list[dict]) -> float | None:
    done = complete(lines)
    return _share(sum(line["score"]["correct"] for line in done), len(done))


def bootstrap_ci(per_question: list[float]) -> tuple[float, float]:
    """95% percentile interval of the mean, resampling questions (fixed seed, spec §9.7)."""
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(per_question)
    means = sorted(sum(rng.choices(per_question, k=n)) / n for _ in range(BOOTSTRAP_SAMPLES))
    return means[int(0.025 * BOOTSTRAP_SAMPLES)], means[int(0.975 * BOOTSTRAP_SAMPLES) - 1]


def _row(label: str, lines: list[dict]) -> str:
    repeats = _by_repeat(complete(lines))
    per_repeat = [_accuracy(group) for group in repeats.values()]
    questions = sorted({line["item_id"] for line in complete(lines)})
    if len(per_repeat) > 1:
        accuracy = f"{statistics.mean(per_repeat):.2f} ± {statistics.stdev(per_repeat):.2f}"
    else:
        accuracy = f"{per_repeat[0]:.2f} (1 repeat)"
    per_question = [
        statistics.mean(
            line["score"]["correct"] for line in complete(lines) if line["item_id"] == q
        )
        for q in questions
    ]
    low, high = bootstrap_ci(per_question)
    missing = sum(line["incomplete"] for line in lines)
    notes = f"{missing} incomplete" if missing else ""
    return f"| {label} | {len(questions)} | {accuracy} | [{low:.2f}, {high:.2f}] | {notes} |"


def full_system_section(lines: list[dict], items: list[dict]) -> list[str]:
    out = ["| Category | n | Accuracy | 95% CI | Notes |", "|---|---|---|---|---|"]
    for category in CATEGORY_ORDER:
        subset = [line for line in lines if line["category"] == category]
        if complete(subset):
            out.append(_row(category, subset))
    out.append(_row("Overall", lines))
    return out


def abstention(lines: list[dict], items_by_id: dict[str, dict]) -> tuple:
    """(precision, recall, false abstain rate) over all complete answers (spec §9.7)."""
    done = complete(lines)
    should = [items_by_id[line["item_id"]]["gold"]["should_abstain"] for line in done]
    did = [line["result"]["answer"]["abstained"] for line in done]
    both = sum(s and d for s, d in zip(should, did, strict=True))
    wrong = sum(d and not s for s, d in zip(should, did, strict=True))
    return (
        _share(both, sum(did)),
        _share(both, sum(should)),
        _share(wrong, sum(not s for s in should)),
    )


def _percentile(values: list[int], q: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def operational(lines: list[dict]) -> dict:
    done = complete(lines)
    results = [line["result"] for line in done]
    tool_steps = [s for r in results for s in r["steps"] if s["kind"] == "tool"]
    # BUDGET is the loop refusing a call, not a tool failing; it shows in the stop reasons.
    errors = [
        s for s in tool_steps
        if s["summary"].startswith("error:") and s["summary"] != "error: BUDGET"
    ]  # fmt: skip
    latencies = [r["latency_ms"] for r in results]
    return {
        "tools_per_q": statistics.mean(r["tool_calls"] for r in results),
        "tool_error_rate": _share(len(errors), len(tool_steps)),
        "p50_ms": _percentile(latencies, 0.50),
        "p95_ms": _percentile(latencies, 0.95),
        "cost_per_q": statistics.mean(r["cost_usd"] for r in results),
        "total_cost": sum(r["cost_usd"] for r in results),
        "fabricated_rate": _share(sum(bool(r["stripped_ids"]) for r in results), len(results)),
        "stop_reasons": dict(Counter(r["stopped_reason"] for r in results)),
    }


def operational_section(lines: list[dict], spend: dict | None) -> list[str]:
    ops = operational(lines)
    reasons = ", ".join(f"{k} {v}" for k, v in sorted(ops["stop_reasons"].items()))
    total = f"{spend['total_usd']:.2f} USD (all runs)" if spend else f"{ops['total_cost']:.4f} USD"
    return [
        "| Tools/q | Tool error rate | p50 ms | p95 ms | $/q | Total spend | Stop reasons |",
        "|---|---|---|---|---|---|---|",
        f"| {ops['tools_per_q']:.2f} | {fmt(ops['tool_error_rate'])} | {ops['p50_ms']} | "
        f"{ops['p95_ms']} | {ops['cost_per_q']:.4f} | {total} | {reasons} |",
    ]


def ablation_section(lines: list[dict], items: list[dict]) -> list[str]:
    items_by_id = {i["id"]: i for i in items}
    header = (
        "| Config | " + " | ".join(CATEGORY_ORDER) + " | Overall | Abstain P/R | False abstain |"
        " Fabricated IDs | Tools/q | p95 ms | $/q |"
    )
    out = [header, "|" + "---|" * (len(CATEGORY_ORDER) + 8)]
    for code, config in CONFIGS.items():
        mine = [line for line in lines if line["config"] == code]
        cells = []
        for category in CATEGORY_ORDER:
            subset = [line for line in mine if line["category"] == category]
            ran = category in CATEGORIES[code] and complete(subset)
            cells.append(fmt(_accuracy(subset)) if ran else DASH)
        if complete(mine):
            precision, recall, false_rate = abstention(mine, items_by_id)
            ops = operational(mine)
            cells += [
                fmt(_accuracy(mine)), f"{fmt(precision)}/{fmt(recall)}", fmt(false_rate),
                fmt(ops["fabricated_rate"]), f"{ops['tools_per_q']:.2f}", str(ops["p95_ms"]),
                f"{ops['cost_per_q']:.4f}",
            ]  # fmt: skip
        else:
            cells += [DASH] * 7
        out.append(f"| {code} {config.name} | " + " | ".join(cells) + " |")
    a5 = complete([line for line in lines if line["config"] == "A5"])
    if a5:
        stopped = sum(line["result"]["stopped_reason"] == "tool_budget" for line in a5)
        out += [
            "",
            f"A5 (no composite impact tool): {stopped / len(a5):.0%} of its answers stopped on the "
            "tool budget. Without impact_analysis the model has to chain lineage and ownership "
            "calls itself, and broadcast questions (tens of reports and people) run out of calls. "
            "That cost is what this ablation measures, not a fault of the run (D24).",
        ]
    return out


def _what_went_wrong(line: dict, item: dict) -> str:
    result, gold = line["result"], item["gold"]
    given = set(result["answer"]["answer_ids"])
    parts = []
    if gold["should_abstain"]:
        parts.append(
            "answered instead of abstaining"
            if not result["answer"]["abstained"]
            else "named a person while abstaining"
        )
    elif result["answer"]["abstained"]:
        parts.append("abstained on an answerable question")
    else:
        missing = sorted(set(gold["answer_ids"]) - given)
        forbidden = sorted(set(gold["forbidden_ids"]) & given)
        if missing:
            parts.append("missing " + ", ".join(missing[:5]) + (" …" if len(missing) > 5 else ""))
        if forbidden:
            parts.append("gave forbidden " + ", ".join(forbidden))
    if result["stripped_ids"]:
        parts.append("invented IDs removed: " + ", ".join(result["stripped_ids"]))
    parts.append(f"stopped: {result['stopped_reason']}, {result['tool_calls']} tool calls")
    return "; ".join(parts)


def error_analysis(lines: list[dict], items: list[dict], per_category: int = 3) -> list[str]:
    """Up to three failures per category, picked from the raw lines in ID order."""
    items_by_id = {i["id"]: i for i in items}
    out = ["| Question | Repeat | Question text | What went wrong |", "|---|---|---|---|"]
    for category in CATEGORY_ORDER:
        failures = sorted(
            (
                line
                for line in complete(lines)
                if line["category"] == category and not line["score"]["correct"]
            ),
            key=lambda line: (line["item_id"], line["repeat"]),
        )
        seen: set[str] = set()
        for line in failures:
            if line["item_id"] in seen or len(seen) == per_category:
                continue
            seen.add(line["item_id"])
            item = items_by_id[line["item_id"]]
            question = item["question"].replace("|", "/")
            out.append(
                f"| {line['item_id']} | {line['repeat']} | {question} | {_what_went_wrong(line, item)} |"
            )
    return out


THREATS = [
    "- **Synthetic, template-built data.** One fictional company, generated by code; real "
    "catalogues are messier, and the questions come from templates, not from users.",
    "- **Gold and data share an author.** The gold is computed by independent code (D14) and "
    "cross-checked against the tools, but it encodes the same reading of the spec.",
    "- **One model, one data seed.** Results may not carry over to another model or dataset; "
    "three repeats measure sampling noise, not model choice.",
    "- **Small categories.** 10–15 questions per category give wide confidence intervals.",
    "- **Broadcast impact questions are graded on department heads (D24),** not on every "
    "person to notify; the stated count is not scored yet.",
    "- **The match signal mostly rests on exact names** (retrieval benchmark), so the "
    "abstain ablation largely measures the prompt.",
]
