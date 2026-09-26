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
NOT_RUN = "⏳ not run"  # report.py shows the same marker; one spelling, defined here
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


def flip_rate(lines: list[dict]) -> dict[str, float]:
    """Share of questions the repeats disagree about, per category and overall.

    The standard deviation over three repeats is a coarse estimate of the noise; this is a
    second read on the same runs. A category where answers flip often cannot carry a
    one-run ablation difference, whatever the point difference looks like.
    """
    done = complete(lines)
    by_question: dict[str, list[bool]] = {}
    category_of: dict[str, str] = {}
    for line in done:
        by_question.setdefault(line["item_id"], []).append(bool(line["score"]["correct"]))
        category_of[line["item_id"]] = line["category"]
    out: dict[str, list[bool]] = {}
    for question, scores in by_question.items():
        flipped = len(set(scores)) > 1  # one repeat can never flip
        out.setdefault(category_of[question], []).append(flipped)
        out.setdefault("Overall", []).append(flipped)
    return {
        key: sum(values) / len(values)
        for key, values in sorted(out.items(), key=lambda kv: kv[0] == "Overall")
    }


def _row(label: str, lines: list[dict], expected: int, flips: float | None = None) -> str:
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
    return (
        f"| {label} | {len(questions)} | {accuracy} | [{low:.2f}, {high:.2f}] "
        f"| {fmt(flips)} | {notes} |"
    )


def full_system_section(lines: list[dict], items: list[dict], repeats=None) -> list[str]:
    """Accuracy per category of the full system; `repeats` defaults to the test-set plan."""
    flips = flip_rate(lines)
    out = [
        "| Category | n | Accuracy | 95% CI | Flip rate | Notes |",
        "|---|---|---|---|---|---|",
    ]
    for category in CATEGORY_ORDER:
        subset = [line for line in lines if line["category"] == category]
        if complete(subset):
            planned_here = planned(items, "A0", category, repeats)
            out.append(_row(category, subset, planned_here, flips.get(category)))
    out.append(_row("Overall", lines, planned(items, "A0", repeats=repeats), flips.get("Overall")))
    return [
        *out,
        "",
        "**Flip rate** is the share of questions the repeats do not agree about. It reads the "
        "same runs as the standard deviation, per question instead of per repeat: where it is "
        "high the system is unstable on that category, and a one-run ablation difference there "
        "is not evidence of anything. It is a diagnostic; the rule for reading an ablation "
        "difference stays the one pre-registered above.",
    ]


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
        "repeats there is no yardstick and nothing is marked. Read every mark next to the "
        "flip rate of that category above: where the full system's own repeats disagree about "
        "many questions, one ablation run cannot say anything about that category.",
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


# What each ablation is there to answer. Written once, next to the code that reads it, so the
# sentence on the page cannot drift from the configuration it describes.
ABLATION_QUESTION = {
    "A1": "what BM25 adds on top of the dense retriever",
    "A2": "what the dense retriever adds on top of BM25",
    "A3": "what the `resolve_owner` tool adds over letting the model walk the chain itself",
    "A4": "what the abstain instructions and the match-quality signal add",
    "A5": "what the composite `impact_analysis` tool adds over chaining lineage and ownership",
}


def ablation_readings(lines: list[dict], items: list[dict]) -> list[str]:
    """One sentence per ablation: what it measures, and whether its run can say anything."""
    full = [line for line in lines if line["config"] == "A0"]
    baseline = _spread(full)
    flips = flip_rate(full)
    out: list[str] = []
    better: list[tuple[str, str, float, float]] = []
    for code, config in CONFIGS.items():
        if code == "A0":
            continue
        mine = complete([line for line in lines if line["config"] == code])
        head = f"- **{code} {config.name}** — {ABLATION_QUESTION[code]}."
        if not mine:
            out.append(f"{head} {NOT_RUN}")
            continue
        overall = _accuracy(mine)
        if baseline is None:
            out.append(
                f"{head} Overall {overall:.2f}; with fewer than two full-system repeats there is "
                "no noise estimate to read it against, so nothing is claimed."
            )
            continue
        mean, std = baseline
        difference = overall - mean
        effect = abs(difference) >= EFFECT_POINTS and abs(difference) > EFFECT_NOISE_FACTOR * std
        # The categories this ablation actually ran on are the only ones its flip rate matters in.
        noisiest = max(
            (c for c in CATEGORIES[code] if c in flips), key=lambda c: flips[c], default=None
        )
        # With std 0 the "> 2 x std" half of the pre-registered rule cannot fail, so saying the
        # rule was met would overstate it: what decided is the point bar alone. The rule itself
        # is not touched — it was fixed before the run — only what the page claims for it.
        toothless = std == 0
        if effect and toothless:
            verdict = (
                f"over the pre-registered bar, but read it carefully: the repeat std is "
                f"{std:.2f}, so the rule's noise term could not fail and only the "
                f"{EFFECT_POINTS:.2f} point bar decided"
            )
        elif effect:
            verdict = (
                f"an effect by the pre-registered rule (at least {EFFECT_POINTS:.2f} and more "
                f"than {EFFECT_NOISE_FACTOR}x the repeat std of {std:.2f})"
            )
        else:
            verdict = (
                f"inside the noise: the repeat std is {std:.2f}, so this one run does not "
                f"separate it from the full system"
            )
        sentence = (
            f"{head} Overall {overall:.2f} against the full system's {mean:.2f} "
            f"({difference:+.2f}), {verdict}."
        )
        if noisiest is not None and flips[noisiest] > 0:
            sentence += (
                f" Its noisiest category is {noisiest}, where the full system's own repeats "
                f"disagree about {flips[noisiest]:.0%} of the questions."
            )
        out.append(sentence)
        if difference > 0:
            better.append((code, config.name, overall, difference))
    if better:
        # An ablation scoring above the full system is a result about the design, not a
        # footnote: the component it removes is not earning its place on this question set.
        named = "; ".join(
            f"**{code} {name}** at {value:.2f} ({gap:+.2f})" for code, name, value, gap in better
        )
        out += [
            "",
            f"**These ablations beat the full system:** {named}. Switching that component off "
            "did not cost accuracy on this question set, it bought some. Whatever the component "
            "is for, this run does not show it paying for itself, and the honest reading is "
            "that the full system carries a part it has not earned.",
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
        wanted = set(gold["answer_ids"])
        missing = sorted(wanted - given)
        forbidden = sorted(set(gold["forbidden_ids"]) & given)
        extra = sorted(given - wanted - set(gold["forbidden_ids"]))
        if missing:
            parts.append("missing " + ", ".join(missing[:5]) + (" …" if len(missing) > 5 else ""))
        if forbidden:
            parts.append("gave forbidden " + ", ".join(forbidden))
        # Without this an over-inclusive answer, which is most of L5, explains nothing: it is
        # wrong precisely because of the IDs it added, and none of them is missing or forbidden.
        if extra and not missing:
            parts.append(
                f"every gold ID and {len(extra)} more: "
                + ", ".join(extra[:5])
                + (" …" if len(extra) > 5 else "")
            )
    if result["stripped_ids"]:
        parts.append("invented IDs removed: " + ", ".join(result["stripped_ids"]))
    parts.append(f"stopped: {result['stopped_reason']}, {result['tool_calls']} tool calls")
    return "; ".join(parts)


# The six kinds a wrong answer can be. The order they are tested in is the order below, and
# that order is a claim about cause: a lineage call on the wrong node also leaves the gold
# unseen, so if the ceiling were read first every wrong call would hide behind it.
ERROR_KINDS = (
    "missing abstain",  # the question has no answer in the metadata, and it answered anyway
    "needless abstain",  # the answer was there and it refused
    "wrong tool or arguments",  # the call the question needs was never made
    "retrieval ceiling",  # no tool result ever held a gold ID: the model never saw the answer
    "over-inclusive",  # every gold ID, plus more that are not
    "right tool, wrong reading",  # it was shown the answer and still gave another one
)


def classify(line: dict, item: dict, shown: dict[str, list[str]] | None = None) -> str:
    """Which of ERROR_KINDS a wrong answer is. Only call it on lines that scored wrong."""
    answer, gold = line["result"]["answer"], item["gold"]
    steps = line["result"]["steps"]
    seen = shown_ids(line, shown)
    if gold["should_abstain"]:
        return "missing abstain"
    if answer["abstained"]:
        return "needless abstain"
    if _correct_call(item, steps) is False:
        return "wrong tool or arguments"
    if _gold_unseen(item, steps, seen):
        return "retrieval ceiling"
    given, wanted = set(answer["answer_ids"]), set(gold["answer_ids"])
    if wanted and wanted <= given and given - wanted:
        return "over-inclusive"
    return "right tool, wrong reading"


def error_kinds(
    lines: list[dict], items: list[dict], shown: dict[str, list[str]] | None = None
) -> dict[str, Counter]:
    """Per category, how many wrong answers of each kind."""
    by_id = {i["id"]: i for i in items}
    out: dict[str, Counter] = {}
    for line in complete(lines):
        if line["score"]["correct"]:
            continue
        counts = out.setdefault(line["category"], Counter())
        counts[classify(line, by_id[line["item_id"]], shown)] += 1
    return out


def error_kinds_section(
    lines: list[dict], items: list[dict], shown: dict[str, list[str]] | None = None
) -> list[str]:
    """The shape of the failures: what kind, and how much of it retrieval can even reach."""
    counts = error_kinds(lines, items, shown)
    by_id = {i["id"]: i for i in items}
    out = [
        "| Category | Wrong | " + " | ".join(ERROR_KINDS) + " | Gold never retrieved |",
        "|" + "---|" * (len(ERROR_KINDS) + 3),
    ]
    for category in CATEGORY_ORDER:
        wrong = [
            line
            for line in complete(lines)
            if line["category"] == category and not line["score"]["correct"]
        ]
        if not wrong:
            continue
        kinds = counts.get(category, Counter())
        unseen = sum(
            _gold_unseen(by_id[line["item_id"]], line["result"]["steps"], shown_ids(line, shown))
            for line in wrong
        )
        cells = [str(kinds.get(kind, 0)) for kind in ERROR_KINDS]
        out.append(
            f"| {category} | {len(wrong)} | " + " | ".join(cells) + f" | {unseen} of {len(wrong)} |"
        )
    return [
        *out,
        "",
        "The kinds are read in the order of the columns, and that order is a claim about cause: "
        "a lineage call on the wrong node also leaves the gold unseen, so the wrong call is "
        "blamed before the ceiling. **Gold never retrieved** is the line between the agent and "
        "the search under it: those wrong answers were never shown the gold by any tool, so no "
        "prompt could have fixed them. The rest are the agent's own.",
        "",
        _basis(lines, shown),
    ]


BASIS_REPLAYED = (
    "What the model was shown is measured by replaying every stored tool call against the "
    "same tools and data (`scripts/replay_tool_outputs.py`): no model call, no quota, and the "
    "payload that comes back is the one the agent sent on, size cap included."
)


def _basis(lines: list[dict], shown: dict[str, list[str]] | None) -> str:
    """Which evidence the ceiling number rests on, and whether it rests on it everywhere."""
    if shown is None:
        return BASIS_TRACE
    covered, total = replay_coverage(lines, shown)
    if covered == total:
        return BASIS_REPLAYED
    return (
        f"{BASIS_REPLAYED} {total - covered} of {total} answers are not in the replay file yet "
        f"and are read off the trace instead, which overstates their ceiling; rerun "
        f"`scripts/replay_tool_outputs.py` once the run stops."
    )


BASIS_TRACE = (
    "Without the replay file this is read off the trace, which keeps only the first 300 "
    "characters of each tool result, so it **overstates** the ceiling: an ID further down a "
    "payload the model did read looks as if it was never retrieved. Run "
    "`scripts/replay_tool_outputs.py`."
)


def error_analysis(
    lines: list[dict],
    items: list[dict],
    per_category: int = 3,
    shown: dict[str, list[str]] | None = None,
) -> list[str]:
    """Up to three failures per category, picked from the raw lines in ID order."""
    items_by_id = {i["id"]: i for i in items}
    out = [
        "| Question | Kind | Raw line | Question text | What went wrong |",
        "|---|---|---|---|---|",
    ]
    for category in CATEGORY_ORDER:
        failures = sorted(
            (
                line
                for line in complete(lines)
                if line["category"] == category and not line["score"]["correct"]
            ),
            key=lambda line: (line["item_id"], line["repeat"]),
        )
        # Representative, not simply the lowest IDs: take the first failure of each kind
        # first, then fill up in ID order. Three examples of the same kind would hide the
        # rest of the shape of the category.
        chosen: list[dict] = []
        kinds_taken: set[str] = set()
        questions_taken: set[str] = set()
        for pass_by_kind in (True, False):
            for line in failures:
                if len(chosen) == per_category or line["item_id"] in questions_taken:
                    continue
                kind = classify(line, items_by_id[line["item_id"]], shown)
                if pass_by_kind and kind in kinds_taken:
                    continue
                kinds_taken.add(kind)
                questions_taken.add(line["item_id"])
                chosen.append(line)
        for line in sorted(chosen, key=lambda one: (one["item_id"], one["repeat"])):
            item = items_by_id[line["item_id"]]
            question = item["question"].replace("|", "/")
            raw = f"`{line['set']}_{line['config']}_r{line['repeat']}.jsonl`"
            out.append(
                f"| {line['item_id']} | {classify(line, item, shown)} | {raw} | {question} | "
                f"{_what_went_wrong(line, item)} |"
            )
    return out


# What each ID type means when it goes missing from an answer, for the sentence below.
ID_MEANING = {
    "EMP": "people to notify",
    "RPT": "reports that break",
    "TBL": "tables in the lineage",
    "REQ": "earlier requests",
    "MET": "metrics",
}


def missing_id_types(lines: list[dict], items: list[dict]) -> dict[str, int]:
    """For wrong answers that did answer: how many gold IDs of each type were left out.

    An impact answer can be wrong in two different ways — it can miss a report that breaks or
    miss a person to tell — and the score alone does not say which.
    """
    by_id = {i["id"]: i for i in items}
    missing: Counter = Counter()
    for line in complete(lines):
        if line["score"]["correct"] or line["result"]["answer"]["abstained"]:
            continue
        item = by_id.get(line["item_id"])
        if item is None:
            continue
        given = set(line["result"]["answer"]["answer_ids"])
        for gold_id in set(item["gold"]["answer_ids"]) - given:
            missing[gold_id.split("-")[0]] += 1
    return dict(missing)


def ablation_shift(
    lines: list[dict],
    items: list[dict],
    code: str,
    shown: dict[str, list[str]] | None = None,
) -> list[str]:
    """Where one ablation's failures differ from the full system's, on its own categories.

    The ablation table gives the score; this says what changed underneath it. Comparing the
    two on the categories the ablation ran is the only fair comparison, and the full system's
    figures are its mean over repeats so one unlucky repeat does not set the baseline.
    """
    categories = [c for c in CATEGORY_ORDER if c in CATEGORIES[code]]
    mine = complete([line for line in lines if line["config"] == code])
    full = complete(
        [line for line in lines if line["config"] == "A0" and line["category"] in categories]
    )
    if not mine or not full:
        return [NOT_RUN]
    repeats = len(_by_repeat(full)) or 1
    kinds_mine = error_kinds(mine, items, shown)
    kinds_full = error_kinds(full, items, shown)
    rows = [
        f"On {', '.join(categories)}, the categories {code} runs, against the full system's "
        f"{repeats} repeats (its counts are per repeat).",
        "",
        "| | Answers | Wrong | " + " | ".join(ERROR_KINDS) + " |",
        "|" + "---|" * (len(ERROR_KINDS) + 3),
    ]
    for label, group, kinds, divisor in (
        ("A0 full", full, kinds_full, repeats),
        (f"{code} {CONFIGS[code].name}", mine, kinds_mine, 1),
    ):
        wrong = sum(not line["score"]["correct"] for line in group)
        totals: Counter = Counter()
        for counts in kinds.values():
            totals.update(counts)
        cells = [f"{totals.get(kind, 0) / divisor:.1f}" for kind in ERROR_KINDS]
        rows.append(
            f"| {label} | {len(group) / divisor:.0f} | {wrong / divisor:.1f} | "
            + " | ".join(cells)
            + " |"
        )

    missing_mine = missing_id_types(mine, items)
    missing_full = missing_id_types(full, items)
    types = sorted(set(missing_mine) | set(missing_full))
    if types:
        rows += [
            "",
            "Gold IDs left out of an answer that was given, by type "
            "(again per repeat for the full system):",
            "",
            "| | " + " | ".join(f"{t} ({ID_MEANING.get(t, t)})" for t in types) + " |",
            "|" + "---|" * (len(types) + 1),
            "| A0 full | "
            + " | ".join(f"{missing_full.get(t, 0) / repeats:.1f}" for t in types)
            + " |",
            f"| {code} {CONFIGS[code].name} | "
            + " | ".join(str(missing_mine.get(t, 0)) for t in types)
            + " |",
        ]
    # Always the verdict, even when nothing was left out: "no shift" is a reading too.
    rows += ["", _what_the_component_holds(code, missing_mine, missing_full, repeats)]
    return rows


def _what_the_component_holds(
    code: str, mine: dict[str, int], full: dict[str, int], repeats: int
) -> str:
    """One sentence, from the numbers: which kind of ID the ablation starts dropping.

    Written as a generator rather than as prose so it cannot say something the table does not.
    """
    gaps = {kind: mine.get(kind, 0) - full.get(kind, 0) / repeats for kind in set(mine) | set(full)}
    worst = max(gaps, key=lambda kind: gaps[kind], default=None)
    if worst is None or gaps[worst] <= 0:
        return (
            f"Nothing the {code} answers leave out is more common than in the full system's, so "
            "on these questions the component is not what the score difference is about."
        )
    others = sorted((k for k in gaps if k != worst), key=lambda k: -gaps[k])
    rest = ", ".join(f"{k} {gaps[k]:+.1f}" for k in others) or "nothing else"
    return (
        f"**What the component holds up:** without it the answers leave out "
        f"{gaps[worst]:+.1f} more {worst} IDs per question set — {ID_MEANING.get(worst, worst)} — "
        f"against {rest}; that, not the number of tool calls, is what it was doing."
    )


def determinism_note(lines: list[dict]) -> list[str]:
    """Said only when the repeats never disagreed, because then the noise yardstick is zero."""
    full = complete([line for line in lines if line["config"] == "A0"])
    by_repeat = _by_repeat(full)
    if len(by_repeat) < 2 or flip_rate(full).get("Overall", 1.0) > 0:
        return []
    by_question: dict[str, set] = {}
    for line in full:
        by_question.setdefault(line["item_id"], set()).add(line["result"]["answer"]["answer"])
    identical = sum(len(texts) == 1 for texts in by_question.values())
    return [
        f"- **The {len(by_repeat)} repeats never disagreed, so the noise yardstick is zero.** "
        f"Every one of the {len(by_question)} questions scored the same in every repeat, and "
        f"{identical} of them came back with character-for-character the same answer, at "
        f"different latencies, so these were real calls and not a cache. At temperature 0 this "
        f"model is reproducible on this workload. The consequence is uncomfortable and is not "
        f"hidden: the pre-registered rule for reading an ablation is "
        f'"at least {EFFECT_POINTS:.2f} **and** more than {EFFECT_NOISE_FACTOR}x the repeat '
        f'std", and with a std of zero its noise term cannot fail, so every difference of '
        f"{EFFECT_POINTS:.2f} or more is marked as an effect on the strength of the point bar "
        f"alone. The two repeats beyond the first cost about two of the five run days and "
        f"measured a spread of exactly zero; spending them on a second run of each ablation "
        f"would have bought a real yardstick instead."
    ]


def retrieval_ceiling_note(
    lines: list[dict], items: list[dict], shown: dict[str, list[str]] | None = None
) -> list[str]:
    """The threat that is not about the agent at all, with the number behind it."""
    by_id = {i["id"]: i for i in items}
    wrong = [line for line in complete(lines) if not line["score"]["correct"]]
    if not wrong:
        return []
    unseen = sum(
        _gold_unseen(by_id[line["item_id"]], line["result"]["steps"], shown_ids(line, shown))
        for line in wrong
    )
    return [
        f"- **A retrieval ceiling sits under the agent's score.** {unseen} of its {len(wrong)} "
        f"wrong answers were never shown a gold ID by any tool, so no prompt or reasoning "
        f"change could have reached them; that part of the gap measures the retriever, not the "
        f"agent. The split per category is in the error analysis."
    ]


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
    "- **Temperature 0 is not determinism.** Two prompt versions on the dev set gave different "
    "answers to questions neither edit could affect, with different tool queries, so the same "
    "input can take a different path. The three repeats of the full system measure this; a "
    "single-run difference of one or two questions does not separate two systems.",
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


def shown_ids(line: dict, shown: dict[str, list[str]] | None) -> set[str] | None:
    """The IDs the model was really shown, from the replay file, or None without it."""
    if shown is None:
        return None
    seen = shown.get(f"{line['config']}/{line['repeat']}/{line['item_id']}")
    return None if seen is None else set(seen)


def replay_coverage(lines: list[dict], shown: dict[str, list[str]] | None) -> tuple[int, int]:
    """How many finished answers the replay file covers, of how many. (0, 0) without a file."""
    done = complete(lines)
    if shown is None or not done:
        return 0, len(done)
    return sum(shown_ids(line, shown) is not None for line in done), len(done)


def _gold_unseen(item: dict, steps: list[dict], seen: set[str] | None = None) -> bool:
    """True when the tools never put a gold ID in front of the model.

    With `seen` — the IDs recovered by replaying the stored calls
    (scripts/replay_tool_outputs.py) — this is exact. Without it the only evidence is the
    trace, which keeps 300 characters of each tool result, so an ID further down the payload
    looks as though it was never retrieved and the count comes out too high.
    """
    gold = item["gold"]["answer_ids"]
    if not gold:
        return False
    if seen is not None:
        return not any(gold_id in seen for gold_id in gold)
    text = " ".join(step.get("summary") or "" for step in steps if step["kind"] == "tool")
    return not any(gold_id in text for gold_id in gold)


def diagnostics(
    lines: list[dict], items: list[dict], shown: dict[str, list[str]] | None = None
) -> dict:
    """Per category, numbers that explain a score without changing it (from the raw lines):
    over_inclusive_rate          answers with every gold ID and more besides
    tool_args_correct (L3, L5)   the trace called the right tool with the right arguments;
    accuracy_when_args_correct   with it: right call but wrong answer = lost in transcription
    in_cluster_precision (L4)    share of the answered requests that are in the right cluster
    wrong_with_gold_unseen       wrong answers whose gold IDs were in no tool result at all:
                                 retrieval never offered the answer, so no prompt could fix it
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
        wrong = [line for line in done if not line["score"]["correct"]]
        stats["wrong_answers"] = len(wrong)
        stats["wrong_with_gold_unseen"] = sum(
            1
            for line in wrong
            if _gold_unseen(by_id[line["item_id"]], line["result"]["steps"], shown_ids(line, shown))
        )
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


def diagnostics_section(
    lines: list[dict], items: list[dict], shown: dict[str, list[str]] | None = None
) -> list[str]:
    rows = diagnostics(lines, items, shown)
    out = [
        "These numbers explain the scores above; they do not change the scores.",
        "",
        "| Category | Over-inclusive | Right tool call | Accuracy when the call was right "
        "| In-cluster precision | Gold never retrieved |",
        "|---|---|---|---|---|---|",
    ]
    for category, stats in rows.items():
        unseen = f"{stats['wrong_with_gold_unseen']} of {stats['wrong_answers']}"
        out.append(
            f"| {category} | {fmt(stats['over_inclusive_rate'])} | {fmt(stats.get('tool_args_correct'))} "
            f"| {fmt(stats.get('accuracy_when_args_correct'))} | {fmt(stats.get('in_cluster_precision'))} "
            f"| {unseen} |"
        )
    return [
        *out,
        "",
        '"Gold never retrieved" counts the wrong answers whose gold IDs appeared in no tool '
        "result: the retriever never put the answer in front of the model, so the failure "
        "belongs to retrieval, not to the agent's reasoning or its prompt.",
    ]


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
