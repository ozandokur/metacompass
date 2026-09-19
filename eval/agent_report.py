"""The agent sections of results.md, computed from the runner's raw JSON lines (spec §9.7,
§9.8, §9.11).

Every number here comes from eval/results/*.jsonl (one scored AgentResult per line) joined
with the question set for the gold; nothing is typed in. Cells of configurations or
categories that never ran are "—".

The run happens on a free tier (D25): a day's quota can stop it and a later run resumes
it, so answers the plan asks for but the run has not reached yet are counted from the plan
and shown as "not answered yet". Only the full system is repeated; its repeat-to-repeat
standard deviation is the yardstick for reading one-run ablation differences ("≈").
"""

import random
import statistics
from collections import Counter

from configs import ALL_CATEGORIES, CATEGORIES, CONFIGS, REPEATS

CATEGORY_ORDER = ("L1", "L2", "L3", "L4", "L5", "L6", "MX")
DASH = "—"
BOOTSTRAP_SAMPLES = 1000
BOOTSTRAP_SEED = 0


def complete(lines: list[dict]) -> list[dict]:
    # Lines written before D25 could be placeholders for questions the budget cut off.
    return [line for line in lines if not line.get("incomplete", False)]


def planned(items: list[dict], code: str, category: str | None = None, repeats=None) -> int:
    """Answers the plan asks of one configuration (optionally for one category)."""
    wanted = [category] if category else CATEGORIES[code]
    n_items = sum(
        1 for item in items if item["category"] in wanted and item["category"] in CATEGORIES[code]
    )
    return n_items * (REPEATS[code] if repeats is None else repeats)


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


def _row(label: str, lines: list[dict], expected: int) -> str:
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
    missing = expected - len(complete(lines))
    notes = f"{missing} not answered yet" if missing > 0 else ""
    return f"| {label} | {len(questions)} | {accuracy} | [{low:.2f}, {high:.2f}] | {notes} |"


def full_system_section(lines: list[dict], items: list[dict], repeats=None) -> list[str]:
    """Accuracy per category of the full system; `repeats` defaults to the test-set plan."""
    out = ["| Category | n | Accuracy | 95% CI | Notes |", "|---|---|---|---|---|"]
    for category in CATEGORY_ORDER:
        subset = [line for line in lines if line["category"] == category]
        if complete(subset):
            out.append(_row(category, subset, planned(items, "A0", category, repeats)))
    out.append(_row("Overall", lines, planned(items, "A0", repeats=repeats)))
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
        # The free tier costs nothing (D25); tokens are what the quota counts.
        "tokens_per_q": statistics.mean(r["input_tokens"] + r["output_tokens"] for r in results),
        "fabricated_rate": _share(sum(bool(r["stripped_ids"]) for r in results), len(results)),
        "stop_reasons": dict(Counter(r["stopped_reason"] for r in results)),
    }


def _quota_used(quota: dict | None) -> str:
    if not quota or not quota.get("days"):
        return DASH
    days = quota["days"].values()
    requests, tokens = sum(d["requests"] for d in days), sum(d["tokens"] for d in days)
    return f"{requests} requests over {len(quota['days'])} days ({tokens:,} tokens)"


def operational_section(lines: list[dict], quota: dict | None) -> list[str]:
    ops = operational(lines)
    reasons = ", ".join(f"{k} {v}" for k, v in sorted(ops["stop_reasons"].items()))
    return [
        "| Tools/q | Tool error rate | p50 ms | p95 ms | Tokens/q | Quota used (all runs) | Stop reasons |",
        "|---|---|---|---|---|---|---|",
        f"| {ops['tools_per_q']:.2f} | {fmt(ops['tool_error_rate'])} | {ops['p50_ms']} | "
        f"{ops['p95_ms']} | {ops['tokens_per_q']:.0f} | {_quota_used(quota)} | {reasons} |",
    ]


def run_plan_section(lines: list[dict], items: list[dict], quota: dict | None) -> list[str]:
    """What the plan asks, how far the run got, and the free-tier limits that shaped it."""
    out = [
        "| Config | Repeats | Categories | Planned answers | Answered |",
        "|---|---|---|---|---|",
    ]
    for code, config in CONFIGS.items():
        cats = "all" if CATEGORIES[code] == ALL_CATEGORIES else ", ".join(CATEGORIES[code])
        answered = len(complete([line for line in lines if line["config"] == code]))
        out.append(
            f"| {code} {config.name} | {REPEATS[code]} | {cats} | {planned(items, code)} | {answered} |"
        )
    models = ", ".join(sorted({str(line.get("model")) for line in lines})) or DASH
    limits = (quota or {}).get("limits") or {}

    def limit(key: str, unit: str) -> str:
        return f"{limits[key]:,} {unit}" if limits.get(key) is not None else f"{DASH} {unit}"

    out += [
        "",
        f"Model: `{models}`, on the Google AI Studio free tier: the runs cost nothing, and the "
        f"limits are {limit('rpm', 'requests/min')}, {limit('rpd', 'requests/day')} and "
        f"{limit('tpm', 'input tokens/min')}. Quota used: {_quota_used(quota)}.",
        "",
        "The limits shaped the plan (D25): the full system runs three times, every ablation "
        "once, and a run the daily quota stops resumes the next day where it left off. "
        "Ablation differences are therefore read against the full system's repeat-to-repeat "
        "spread (the ≈ mark below). This records measuring under a constraint; it is not a "
        "gap in the method.",
    ]
    return out


def _spread(lines: list[dict]) -> tuple[float, float] | None:
    """(mean, std) of accuracy over repeats, or None with fewer than two repeats."""
    per_repeat = [_accuracy(group) for group in _by_repeat(complete(lines)).values()]
    if len(per_repeat) < 2:
        return None
    return statistics.mean(per_repeat), statistics.stdev(per_repeat)


def _against_full(value: float, full: tuple[float, float] | None) -> str:
    """A one-run value, marked ≈ when it is within the full system's repeat spread."""
    if full is not None and abs(value - full[0]) <= full[1]:
        return f"{value:.2f} ≈"
    return f"{value:.2f}"


def _question_ci(lines: list[dict]) -> tuple[float, float] | None:
    """Bootstrap CI of accuracy over questions (each question's mean over its repeats)."""
    done = complete(lines)
    questions = sorted({line["item_id"] for line in done})
    if not questions:
        return None
    means = [
        statistics.mean(line["score"]["correct"] for line in done if line["item_id"] == q)
        for q in questions
    ]
    return bootstrap_ci(means)


EFFECT_POINTS = 0.03  # pre-registered: an overall effect needs 3 points...
EFFECT_NOISE_FACTOR = 2  # ...and more than twice the full system's repeat std


def _category_cell(value: float, lines: list[dict], full_lines: list[dict]) -> str:
    """Pre-registered category rule: an effect when the two CIs do not overlap (▲/▼);
    otherwise ≈ when within one std of the full system's repeats."""
    mine, theirs = _question_ci(lines), _question_ci(full_lines)
    if mine and theirs and (mine[1] < theirs[0] or mine[0] > theirs[1]):
        return f"{value:.2f} {'▲' if mine[0] > theirs[1] else '▼'}"
    return _against_full(value, _spread(full_lines))


def _overall_delta(difference: float, full: tuple[float, float] | None) -> str:
    """Pre-registered overall rule: an effect (▲/▼) needs |Δ| >= 3 points AND > 2 x std."""
    text = f"{difference:+.2f}"
    if full is None:
        return text
    if abs(difference) >= EFFECT_POINTS and abs(difference) > EFFECT_NOISE_FACTOR * full[1]:
        return f"{text} {'▲' if difference > 0 else '▼'}"
    return f"{text} ≈" if abs(difference) <= full[1] else text


def ablation_section(lines: list[dict], items: list[dict]) -> list[str]:
    items_by_id = {i["id"]: i for i in items}
    header = (
        "| Config | " + " | ".join(CATEGORY_ORDER) + " | Overall | Δ Overall vs A0 | Abstain P/R |"
        " False abstain | Fabricated IDs | Tools/q | Tokens/q | p95 ms |"
    )
    out = [header, "|" + "---|" * (len(CATEGORY_ORDER) + 9)]
    full = [line for line in lines if line["config"] == "A0"]
    for code, config in CONFIGS.items():
        mine = [line for line in lines if line["config"] == code]
        cells = []
        for category in CATEGORY_ORDER:
            subset = [line for line in mine if line["category"] == category]
            if not (category in CATEGORIES[code] and complete(subset)):
                cells.append(DASH)
            elif code == "A0":
                cells.append(fmt(_accuracy(subset)))
            else:
                same = [line for line in full if line["category"] == category]
                cells.append(_category_cell(_accuracy(subset), subset, same))
        if complete(mine):
            precision, recall, false_rate = abstention(mine, items_by_id)
            ops = operational(mine)
            overall = _accuracy(mine)
            delta = DASH
            baseline = _spread(full)
            if code != "A0" and baseline is not None:
                delta = _overall_delta(overall - baseline[0], baseline)
            cells += [
                fmt(overall), delta, f"{fmt(precision)}/{fmt(recall)}", fmt(false_rate),
                fmt(ops["fabricated_rate"]), f"{ops['tools_per_q']:.2f}",
                f"{ops['tokens_per_q']:.0f}", str(ops["p95_ms"]),
            ]  # fmt: skip
        else:
            cells += [DASH] * 8
        out.append(f"| {code} {config.name} | " + " | ".join(cells) + " |")
    out += [
        "",
        "Ablations ran once each (free tier, D25). Marks follow the pre-registered rules: ▲/▼ "
        "is an effect — in a category column, the ablation's 95% CI does not overlap the full "
        "system's; in Δ Overall, the difference is at least 3 points and more than 2 times "
        "the full system's repeat std. ≈ marks a difference within one std of the full "
        "system's repeats, which is not read as an effect. With fewer than two full-system "
        "repeats there is no yardstick and nothing is marked.",
    ]
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
    "- **Ablations ran once (free tier, D25).** Only the full system has repeats; a one-run "
    "ablation difference smaller than the full system's repeat spread is not read as an effect.",
    "- **Small categories.** 10–15 questions per category give wide confidence intervals.",
    "- **Broadcast impact questions are graded on department heads (D24),** not on every "
    "person to notify; the stated count is not scored yet.",
    "- **The match signal mostly rests on exact names** (retrieval benchmark), so the "
    "abstain ablation largely measures the prompt.",
]


# ---------------------------------------------------------------------- diagnostics


def _correct_call(item: dict, steps: list[dict]) -> bool | None:
    """Did the trace make the call the question needs? None where no single call is right."""
    spec = item.get("gold_spec") or {}
    if spec.get("type") == "upstream_tables":
        wanted = (
            "trace_lineage",
            {"node_id": spec["node_id"], "direction": "upstream", "depth": spec["depth"]},
        )
    elif spec.get("type") == "downstream_reports":
        wanted = (
            "trace_lineage",
            {"node_id": spec["table_id"], "direction": "downstream", "depth": spec["depth"]},
        )
    elif spec.get("type") == "impact_notify":
        wanted = ("impact_analysis", {"table_id": spec["table_id"]})
    else:
        return None
    name, args = wanted
    return any(
        step.get("name") == name
        and all((step.get("arguments") or {}).get(k) == v for k, v in args.items())
        for step in steps
        if step["kind"] == "tool"
    )


def diagnostics(lines: list[dict], items: list[dict]) -> dict:
    """Per category, numbers that explain a score without changing it (from the raw lines):
    over_inclusive_rate          answers with every gold ID and more besides
    tool_args_correct (L3, L5)   the trace called the right tool with the right arguments;
    accuracy_when_args_correct   with it: right call but wrong answer = lost in transcription
    in_cluster_precision (L4)    share of the answered requests that are in the right cluster
    """
    by_id = {item["id"]: item for item in items}
    out: dict[str, dict] = {}
    for category in CATEGORY_ORDER:
        done = [line for line in complete(lines) if line["category"] == category]
        if not done or category == "L6":
            continue
        stats: dict = {}
        over = 0
        for line in done:
            gold_ids = set(by_id[line["item_id"]]["gold"]["answer_ids"])
            given = set(line["result"]["answer"]["answer_ids"])
            over += bool(gold_ids) and gold_ids <= given and bool(given - gold_ids)
        stats["over_inclusive_rate"] = over / len(done)
        calls = [
            (line, _correct_call(by_id[line["item_id"]], line["result"]["steps"])) for line in done
        ]
        judged = [(line, ok) for line, ok in calls if ok is not None]
        if judged:
            right = [line for line, ok in judged if ok]
            stats["tool_args_correct"] = len(right) / len(judged)
            stats["accuracy_when_args_correct"] = _accuracy(right) if right else None
        if category == "L4":
            shares = []
            for line in done:
                given = line["result"]["answer"]["answer_ids"]
                gold_ids = set(by_id[line["item_id"]]["gold"]["answer_ids"])
                if given:
                    shares.append(sum(i in gold_ids for i in given) / len(given))
            stats["in_cluster_precision"] = statistics.mean(shares) if shares else None
        out[category] = stats
    return out


def diagnostics_section(lines: list[dict], items: list[dict]) -> list[str]:
    rows = diagnostics(lines, items)
    out = [
        "These numbers explain the scores above; they do not change the scores.",
        "",
        "| Category | Over-inclusive | Right tool call | Accuracy when the call was right | In-cluster precision |",
        "|---|---|---|---|---|",
    ]
    for category, stats in rows.items():
        out.append(
            f"| {category} | {fmt(stats['over_inclusive_rate'])} | {fmt(stats.get('tool_args_correct'))} "
            f"| {fmt(stats.get('accuracy_when_args_correct'))} | {fmt(stats.get('in_cluster_precision'))} |"
        )
    return out


def baselines_section(baselines: dict) -> list[str]:
    """Trivial answers without any LLM, scored like the agent (eval/baselines.py)."""
    header = "| Baseline | " + " | ".join(CATEGORY_ORDER) + " | What it answers |"
    out = [header, "|" + "---|" * (len(CATEGORY_ORDER) + 2)]
    for name, entry in baselines["baselines"].items():
        cells = []
        for category in CATEGORY_ORDER:
            cell = entry["accuracy"].get(category)
            cells.append(DASH if cell is None else f"{cell['accuracy']:.2f} (n={cell['n']})")
        out.append(f"| {name} | " + " | ".join(cells) + f" | {entry['description']} |")
    return out
