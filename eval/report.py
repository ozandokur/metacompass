"""Renders eval/results.md from raw result files (spec §9.1 rule 4, §9.11).

results.md is only ever written by this script, from files under eval/results/, so no
number in it is typed by hand: even the sentences that explain a change compute their
numbers from the JSON files. Sections without results yet say "⏳ not run".

Retrieval files:
  retrieval_bench_<model>.json      current set, one per embedding model (the A/B)
  retrieval_bench_v1.json           the first benchmark, as recorded (leaky paraphrases)
  retrieval_bench_v1_rescored.json  the v1 set re-scored with the current metrics
Agent files (run_eval.py):
  <set>_<config>_r<repeat>.jsonl   one scored AgentResult per line (git SHA inside)
  quota_log.json                   free-tier requests and tokens per Pacific-time day (D25)

Usage: python eval/report.py [--results-dir eval/results] [--set test] [--out eval/results.md]
"""

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import agent_report
import run_retrieval_bench as bench
from metacompass.config import MATCH_SIGNAL, TAU, TAU_Z

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "eval" / "results"
NOT_RUN = "⏳ not run"
MODES = ("bm25", "dense", "hybrid")


def load_retrieval(results_dir: Path = RESULTS) -> dict | None:
    def read(path: Path) -> dict | None:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    models = {
        path.stem.removeprefix("retrieval_bench_"): read(path)
        for path in sorted(results_dir.glob("retrieval_bench_*.json"))
        if not path.stem.startswith("retrieval_bench_v1")
    }
    if not models:
        return None
    return {
        "models": models,
        "v1": read(results_dir / "retrieval_bench_v1.json"),
        "v1_rescored": read(results_dir / "retrieval_bench_v1_rescored.json"),
    }


def _f(value: float) -> str:
    return f"{value:.2f}"


def _headline_table(run: dict) -> list[str]:
    lines = [
        "| Mode | E r@1 | E r@5 | P r@5 | P topic_hit@5 | D pair_coverage@5 | MRR (E+P+D) |",
        "|---|---|---|---|---|---|---|",
    ]
    for mode in MODES:
        s = run["modes"][mode]
        cells = [
            s["E"]["recall@1"], s["E"]["recall@5"], s["P"]["recall@5"],
            s["P"]["topic_hit@5"], s["D"]["pair_coverage@5"], s["all"]["mrr"],
        ]  # fmt: skip
        lines.append(f"| {mode} | " + " | ".join(_f(c) for c in cells) + " |")
    return lines


def _signal_extras(run: dict) -> tuple[int, int]:
    """Paraphrase and negative queries the signal calls strong without an exact match."""
    sig = run["signal"]
    field = "top_dense_cosine" if sig["kind"] == "cosine" else "dense_z"

    def count(kind: str) -> int:
        return sum(
            1
            for r in run["per_query"]
            if r["type"] == kind and not r["exact_match"] and r[field] >= sig["threshold"]
        )

    return count("P"), count("N")


def _count(share: float, n: int) -> int:
    return round(share * n)


def _retrieval_section(retrieval: dict | None) -> list[str]:
    lines = ["## Retrieval benchmark (no LLM)", ""]
    if retrieval is None:
        return [*lines, NOT_RUN, ""]
    models = retrieval["models"]
    winner = bench.choose_model(models)
    run = models[winner]
    meta = run["meta"]
    n = meta["n_queries"]
    lines += [
        f"Set `eval/retrieval_set.json`: {n['E']} exact (E), {n['P']} paraphrase (P), "
        f"{n['D']} disambiguation (D) and {n['N']} negative (N) queries over 370 assets; "
        f"top {meta['top_k']} hits; data seed {meta['data_seed']}; git `{meta['git_sha']}`; "
        f"run {meta['run_date']}.",
        "",
        "Headline metrics: exact queries must find the named asset; paraphrase queries are "
        "judged by recall@5 and by `topic_hit@5` (any report of the right topic in the top 5, "
        "which separates a retrieval miss from a question with several plausible siblings); "
        "disambiguation queries by `pair_coverage@5` (both members of the designed pair in the "
        "top 5). Choosing the right member of a pair is the agent's job and is measured in L1.",
        "",
        f"### Headline — `{winner}`",
        "",
        *_headline_table(run),
        "",
        "### Diagnostic — recall@1",
        "",
        "| Mode | E r@1 (table / acronym / report ID) | P r@1 | D r@1 | D: other member first |",
        "|---|---|---|---|---|",
    ]
    for mode in MODES:
        s = run["modes"][mode]
        sub = s["E_recall@1_by_subtype"]
        e = " / ".join(_f(sub[k]) for k in ("table name", "metric acronym", "report ID"))
        lines.append(
            f"| {mode} | {e} | {_f(s['P']['recall@1'])} | {_f(s['D']['recall@1'])} | "
            f"{s['D']['forbidden_above_target']:.0%} |"
        )

    ids = {mode: run["modes"][mode]["E_recall@1_by_subtype"]["report ID"] for mode in MODES}
    lines += [
        "",
        "**Known property — RRF and ID queries.** When a query is a bare report ID, BM25 puts "
        f"the report first ({ids['bm25']:.0%} recall@1) but the dense retriever never sees IDs "
        "(they are left out of the dense text on purpose), so its ranking is noise; fused with "
        f"it, hybrid recall@1 on report-ID queries is {ids['hybrid']:.0%}. RRF averages ranks, so "
        "a retriever that knows nothing still pulls the other one's first place down. This is "
        "kept visible instead of patched: the agent opens a known ID with `get_record`, not search.",
        "",
    ]

    sig = run["signal"]
    extra_p, extra_n = _signal_extras(run)
    lines += [
        "### Match signal",
        "",
        "A search is `strong` if the query names an asset exactly, or if the closest dense "
        "match stands out: either its cosine is at least τ (absolute), or it lies at least τ_z "
        "standard deviations above the mean cosine of the filtered corpus (relative). Both "
        "thresholds are swept; the variant with the better macro-F1 of strong (E, P, D) versus "
        "weak (N) is used, a tie keeping the absolute one.",
        "",
        "| Model | best τ (cosine) | macro-F1 | best τ_z (z) | macro-F1 | in use |",
        "|---|---|---|---|---|---|",
    ]
    for name, r in models.items():
        best = r["signal"]["best"]
        lines.append(
            f"| {name} | {best['cosine']['threshold']:.2f} | {best['cosine']['macro_f1']:.3f} | "
            f"{best['z']['threshold']:.2f} | {best['z']['macro_f1']:.3f} | "
            f"{r['signal']['kind']} ≥ {r['signal']['threshold']} |"
        )
    lines += [""]
    if sig["equals_exact_match"]:
        lines.append(
            "**The signal in use is in practice equal to `exact_match`:** at its threshold no "
            "query without an exact name or ID comes out strong. The A4 ablation therefore "
            "measures only the prompt."
        )
    else:
        lines.append(
            f"With `{winner}` the signal in use is `{sig['kind']} ≥ {sig['threshold']}` "
            f"(macro-F1 {sig['macro_f1']:.3f}). Beyond exact matches it calls {extra_p} of "
            f"{n['P']} paraphrase queries and {extra_n} of {n['N']} negative queries strong, so "
            "it still rests mostly on exact names and IDs."
        )
    lines += [
        "",
        f"<details><summary>Threshold sweeps for {winner}</summary>",
        "",
        "| variant | threshold | macro-F1 | E/P/D strong | N weak |",
        "|---|---|---|---|---|",
    ]
    for variant in ("cosine", "z"):
        for row in run["sweeps"][variant]:
            lines.append(
                f"| {variant} | {row['tau']:.2f} | {row['macro_f1']:.3f} | "
                f"{row['strong_rate_positive']:.0%} | {row['weak_rate_negative']:.0%} |"
            )
    lines += ["", "</details>", ""]

    lines += [
        "### Embedding model A/B",
        "",
        "One run per model on the same set. The rule was pre-registered in "
        "`eval/run_retrieval_bench.py:choose_model` before either run: hybrid MRR decides if the "
        f"gap is at least {bench.MRR_MARGIN}; otherwise the better signal macro-F1 decides if the "
        f"gap is at least {bench.F1_MARGIN}; otherwise the incumbent `{bench.INCUMBENT_MODEL}` stays.",
        "",
        "| Model | hybrid MRR | dense P r@5 | dense P topic_hit@5 | hybrid P topic_hit@5 | "
        "hybrid D pair_coverage@5 | signal macro-F1 |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, r in models.items():
        m = r["modes"]
        lines.append(
            f"| {name} | {_f(m['hybrid']['all']['mrr'])} | {_f(m['dense']['P']['recall@5'])} | "
            f"{_f(m['dense']['P']['topic_hit@5'])} | {_f(m['hybrid']['P']['topic_hit@5'])} | "
            f"{_f(m['hybrid']['D']['pair_coverage@5'])} | {r['signal']['macro_f1']:.3f} |"
        )
    lines += ["", f"Chosen: `{winner}`.", ""]
    lines += _before_after(retrieval)
    return lines


def _before_after(retrieval: dict) -> list[str]:
    v1, v1r = retrieval["v1"], retrieval["v1_rescored"]
    if v1 is None or v1r is None:
        return []
    same = retrieval["models"].get(v1r["meta"]["embedding_model"])
    lines = ["### Before and after the paraphrase-leakage fix", ""]
    if same is not None:
        n_p = same["meta"]["n_queries"]["P"]
        old_leak, new_leak = v1r["leakage"], same["leakage"]
        topic = {
            label: {mode: _count(run["modes"][mode]["P"]["topic_hit@5"], n_p) for mode in MODES}
            for label, run in (("v1", v1r), ("v2", same))
        }
        lines += [
            "**What changed and why.** The first retrieval set checked paraphrase queries only "
            "against the target report's name. Its paraphrases still reused words of the "
            "target's description and tags: on average "
            f"{old_leak['p_description_overlap_mean']:.0%} of a paraphrase query's content words "
            f"appeared there, and {old_leak['p_queries_over_limit']} of {n_p} queries were above "
            f"the {old_leak['limit']:.0%} limit introduced afterwards. The builder now enforces "
            "that limit and rejects targets whose topic and dimension are shared with another "
            "report; the paraphrase pools were rewritten. The v2 set averages "
            f"{new_leak['p_description_overlap_mean']:.0%} with {new_leak['p_queries_over_limit']} "
            "queries above the limit. The data was regenerated in between (ownership rule update), "
            "so v1 and v2 target different reports; both are scored by the same code and model "
            f"(`{v1r['meta']['embedding_model']}`).",
            "",
            "**How the leak moved the numbers.** On the leaky v1 paraphrases BM25 put a report of "
            f"the right topic in its top 5 for {topic['v1']['bm25']} of {n_p} queries and dense for "
            f"{topic['v1']['dense']}; on v2 BM25 manages {topic['v2']['bm25']} and dense "
            f"{topic['v2']['dense']}. The leak had been handing BM25 the answer; without it dense "
            "leads on paraphrases, which is what the benchmark was meant to show. Several numbers "
            "got worse. That is the point: the comparison between the modes is now valid.",
            "",
            f"v1 set re-scored with the current metrics (`{v1r['meta']['embedding_model']}`):",
            "",
            *_headline_table(v1r),
            "",
            f"v2 set, same model (`{same['meta']['embedding_model']}`):",
            "",
            *_headline_table(same),
            "",
        ]
    lines += [
        f"v1 as originally recorded (git `{v1['meta'].get('git_sha', '?')}`, "
        f"{v1['meta'].get('run_date', '?')}; the metrics of that time):",
        "",
        "| Mode | E r@1 | E r@5 | P r@1 | P r@5 | D r@1 | D r@5 | MRR | Negatives flagged weak |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    weak = f"{v1['negatives_weak_rate']:.0%}"
    for mode in MODES:
        s = v1["modes"][mode]
        cells = [_f(s[t][k]) for t in ("E", "P", "D") for k in ("recall@1", "recall@5")]
        lines.append(f"| {mode} | " + " | ".join(cells) + f" | {_f(s['all']['mrr'])} | {weak} |")
    return [*lines, ""]


def load_runs(results_dir: Path, set_name: str) -> list[dict]:
    """Every raw agent line of one question set in results_dir (not its subfolders)."""
    lines = []
    for path in sorted(results_dir.glob(f"{set_name}_*.jsonl")):
        lines += [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines() if row]
    return lines


# Written on 2026-09-19; the model-choice rule and the frozen configuration on 2026-09-20,
# both before any test-set run. Pinned by PREREGISTERED_DIGEST
# (tests/test_agent_report.py): the rules for reading the results cannot move after the
# results are in.
PREREGISTERED = [
    "- **A4 measures the prompt more than the signal.** A4 switches off the abstain "
    "instructions and the match-quality signal together, and the retrieval benchmark showed "
    "that the signal is strong almost only when a query names an item exactly (learning "
    "note 04). A difference in A4 is read as the effect of the abstain prompt.",
    "- **L3 and L4 measure tool choice and transcription**, not multi-step reasoning: one "
    "right call answers them, and the rest is copying the IDs it returns.",
    "- **The broadcast impact sample is biased.** Broadcast questions come only from hub tables "
    "that reach some, not all, departments, so they lean to the smaller hubs; and on them "
    "individual notification accuracy is not measured, only the department heads (D24).",
    "- **How the model was chosen (written before the candidate runs).** The free tier gives "
    "every Flash model 20 requests a day, which cannot carry a 665-answer plan (about 2,400 "
    "calls); the Flash-Lite class gives 500 a day. The model is therefore chosen by "
    "measurement on the dev set, never on the test set, by this rule: **primary criterion** "
    "the number of answers lost to the agent's own machinery (stop reason parse_failure, "
    "tool_budget or llm_error), **secondary criterion** the overall dev accuracy. A model "
    "whose daily limit cannot finish the plan inside 15 days is not a candidate, whatever it "
    "scores. Both candidates' numbers are reported below, and choosing the model is not one "
    "of the three dev prompt iterations.",
    "- **Frozen before the test run.** Model `gemini-3.1-flash-lite` on the Google AI Studio "
    "free tier (500 requests a day per AI Studio; no refusal has contradicted it, and the "
    "guard learns the real limit from the first one), API `v1beta`, prompt `v5`, match signal "
    "z ≥ "
    "4.25, embedding model `BAAI/bge-small-en-v1.5`, data seed 42; the git SHA is on every "
    "result line. If any of these has to change after the test run starts, the test run starts "
    "over. The prompt was frozen on the dev set alone, where v3, v4 and v5 scored 24, 24 and 23 "
    "of 30. Answers moved between versions on questions the edit could not touch, so this "
    "provider is not deterministic at temperature 0 and a one-question difference cannot "
    "separate two prompts; v5 is the version with no known gap left in its output contract.",
    "- **When an ablation difference is real.** In a category: the 95% CIs of the ablation "
    "and of the full system do not overlap. Overall: the difference is at least 3 points "
    "and more than 2 times the standard deviation of the full system's three repeats. "
    "Anything less is not read as an effect of the ablated component.",
]
PREREGISTERED_DIGEST = "d145e5272dde1f3ba3410fcad8d098a245740c804d25a24d58c9be267e09de67"


def preregistration_digest() -> str:
    return hashlib.sha256("\n".join(PREREGISTERED).encode("utf-8")).hexdigest()


PROMPT_VERSIONS = [
    "Prompt versions: **v1** is the spec §8.4 system prompt with the D24 broadcast line; "
    "**v2 = v1 + schema/payload simplification** (no automatic titles in the tool schemas, "
    "no numeric retrieval scores or query echo in tool results), made on the input "
    "measurement before any result was seen, so it does not count as one of the three dev "
    "iterations. The version pin covers the system prompt and the tool schemas.",
]


def composition_section(files: dict[str, dict], tokens: dict | None = None) -> list[str]:
    """Input per dev question by source, one row per prompt version (no generation).

    The shares are of real tokens when the model counted them (countTokens), else of
    characters; chars/4 stays next to the real count so the estimate can be judged."""
    real = (tokens or {}).get("versions", {})
    out = [
        "| Prompt | LLM turns/q | Input chars/q | ≈ tokens/q (chars/4) | Real tokens/q | System | Tool schemas | Tool results | Other |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for version, data in sorted(files.items()):
        counted = real.get(version)
        share = counted["share_by_source"] if counted else data["share_by_source"]
        real_cell = f"{counted['tokens_per_question']:,.0f}" if counted else "—"
        out.append(
            f"| {version} | {data['mean_llm_turns']:.1f} | {data['mean_input_chars_per_question']:,} "
            f"| {data['mean_input_tokens_per_question_estimate']:,} | {real_cell} "
            f"| {share['system']:.0%} | {share['tools']:.0%} | {share['tool_results']:.0%} "
            f"| {share['other']:.0%} |"
        )
    how = (
        "Real tokens: the model's countTokens for each source as that version sends it, "
        "times the source's characters (no generation)."
        if real
        else "Real token counts from the live runs replace the chars/4 estimate."
    )
    return [
        *out,
        "",
        "Measured by `eval/measure_input.py`: each dev question's shortest tool path played "
        f"through the real loop with a scripted model. {how}",
    ]


def prompt_iteration_section(iterations: dict) -> list[str]:
    """Each prompt version's dev run, from eval/results/prompt_iterations.json (spec §9.1)."""
    versions = iterations["versions"]
    categories = sorted({c for v in versions for c in v["by_category"]})
    out = [
        f"Every version answered the same {versions[0]['answers']} dev questions once; the test "
        "set was never used to choose a prompt.",
        "",
        "| Prompt | Dev accuracy | "
        + " | ".join(categories)
        + " | Abstain P | Abstain R | Calls/answer | |",
        "|---" * (len(categories) + 5) + "|",
    ]
    for v in versions:
        cells = " | ".join(
            f"{v['by_category'][c]['correct']}/{v['by_category'][c]['n']}"
            if c in v["by_category"]
            else "—"
            for c in categories
        )
        mark = "frozen" if v["version"] == iterations["frozen"] else "replaced"
        out.append(
            f"| {v['version']} | {v['accuracy']:.2f} | {cells} | "
            f"{agent_report.fmt(v['abstain_precision'])} | {agent_report.fmt(v['abstain_recall'])} "
            f"| {v['calls_per_answer']:.1f} | {mark} |"
        )
    return out


def model_choice_section(choice: dict) -> list[str]:
    """Which model was chosen and why, from eval/results/model_choice.json (D25, branch B)."""
    out = [
        f"Rule, written before the candidate runs — {choice['rule']}.",
        "",
        "| Model | Dev answered | Lost to machinery | Dev accuracy | LLM calls/answer "
        "| Requests/day | Plan days | |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in choice["candidates"]:
        verdict = "chosen" if c["model"] == choice["chosen"] else "not a candidate"
        if c["feasible"] and c["model"] != choice["chosen"]:
            verdict = "runner-up"
        out.append(
            f"| {c['model']} | {c['answered']}/{c['planned']} | {c['machinery_losses']} "
            f"| {c['accuracy']:.2f} | {c['calls_per_answer']:.1f} | {c['rpd']} "
            f"| {c['plan_days']} | {verdict} |"
        )
    partial = [c for c in choice["candidates"] if c["unanswered"]]
    caveat = [
        "*"
        + "; ".join(f"{c['model']} reached {c['answered']} of {c['planned']}" for c in partial)
        + ": the daily quota stopped the run, so that accuracy covers only those questions "
        "and says little about the model.*"
    ]
    return [
        *out,
        "",
        f"**Decision:** {choice['reason']}",
        "",
        *(caveat + [""] if partial else []),
        "The free tier limits requests per project **and per model**, so each candidate answered "
        'the same 30 dev questions out of its own daily allowance. "Plan days" is the measured '
        "calls per answer times the 665 answers of the run plan, divided by the daily limit: the "
        "reason a model can be better and still unusable here. Choosing the model is not one of "
        "the three dev prompt iterations, and no test-set answer was looked at.",
    ]


def _test_set_notes(items: list[dict]) -> list[str]:
    """Limits of the question set itself, counted from the set file."""
    l3 = Counter(item["gold_spec"]["depth"] for item in items if item["category"] == "L3")
    broadcast = sorted(
        item["gold"]["min_mentioned_count"] for item in items if item["subtype"] == "broadcast"
    )
    depths = ", ".join(f"depth {d}: {n}" for d, n in sorted(l3.items()))
    return [
        f"- **L3 leans to shallow targets.** Lineage golds are kept to 2–15 IDs, which removes "
        f"the metrics and staging tables with the largest lineage; the L3 questions use {depths}.",
        f"- **Broadcast questions reach {', '.join(map(str, broadcast))} people**, the small end "
        "of the hub tables (D24, Q-F5-2).",
    ]


def _metadata(runs: list[dict]) -> str:
    signal = f"z ≥ {TAU_Z}" if MATCH_SIGNAL == "z" else f"cosine ≥ {TAU}"
    if not runs:
        return f"Run metadata: agent model `—` · prompt `—` · signal {signal} · data seed 42 · agent runs: none yet."

    def values(key: str) -> str:
        return ", ".join(sorted({str(line.get(key, "—")) for line in runs}))

    return (
        f"Run metadata: agent model `{values('model')}` · API `{values('api_version')}` · "
        f"prompt `{values('prompt_version')}` · signal {signal} · data seed 42 · "
        f"git `{values('git_sha')}` · dates {values('date')}"
    )


def render_results(
    retrieval: dict | None,
    runs: list[dict] | None = None,
    items: list[dict] | None = None,
    set_name: str = "test",
    quota: dict | None = None,
    composition: dict[str, dict] | None = None,
    baselines: dict | None = None,
    tokens: dict | None = None,
    model_choice: dict | None = None,
    iterations: dict | None = None,
) -> str:
    runs = runs or []
    full = [line for line in runs if line["config"] == "A0"]
    lines = [
        "# Evaluation Results",
        "",
        _metadata(runs),
        "All data is synthetic. This page is generated by `eval/report.py`; do not edit it by hand.",
        "",
        *_retrieval_section(retrieval),
    ]

    def section(title: str, body: list[str] | None) -> None:
        lines.extend([f"## {title}", "", *(body or [NOT_RUN]), ""])

    has_full = bool(agent_report.complete(full))
    note = f"Question set `{set_name}`."
    # The plan's repeats hold for the test set; a dev run is judged on the repeats it has.
    repeats = None if set_name == "test" else max((line["repeat"] for line in full), default=1)
    section("Pre-registered reading rules (written before the test run)", PREREGISTERED)
    section(
        "Model choice and free-tier quota",
        model_choice_section(model_choice) if model_choice else None,
    )
    section(
        "Run plan and free-tier limits",
        agent_report.run_plan_section(runs, items, quota) if runs else None,
    )
    section(
        "Prompt versions and input size",
        [
            *PROMPT_VERSIONS,
            *(["", *prompt_iteration_section(iterations)] if iterations else []),
            *(["", *composition_section(composition, tokens)] if composition else []),
        ],
    )
    section(
        "Trivial baselines (no LLM)",
        agent_report.baselines_section(baselines) if baselines else None,
    )
    section(
        "Agent — full system (3 repeats, mean ± std, 95% CI)",
        [note, "", *agent_report.full_system_section(full, items, repeats)] if has_full else None,
    )
    section(
        "Diagnostics (not scores)",
        agent_report.diagnostics_section(full, items) if has_full else None,
    )
    if has_full:
        precision, recall, false_rate = agent_report.abstention(full, {i["id"]: i for i in items})
        body = [
            "| Precision | Recall | False abstain rate |",
            "|---|---|---|",
            f"| {agent_report.fmt(precision)} | {agent_report.fmt(recall)} | {agent_report.fmt(false_rate)} |",
        ]
        section("Abstention", body)
    else:
        section("Abstention", None)
    section(
        "Ablation (leave-one-out)", agent_report.ablation_section(runs, items) if runs else None
    )
    section("Operational", agent_report.operational_section(full, quota) if has_full else None)
    section("Error analysis", agent_report.error_analysis(full, items) if has_full else None)
    notes = _test_set_notes(items) if items and set_name == "test" else []
    section("Threats to validity", [*agent_report.THREATS, *notes])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render eval/results.md from raw results.")
    parser.add_argument("--results-dir", type=Path, default=RESULTS)
    parser.add_argument("--set", default="test", choices=["dev", "test"])
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "results.md")
    args = parser.parse_args(argv)
    runs = load_runs(args.results_dir, args.set)
    items = json.loads((ROOT / "eval" / f"{args.set}_set.json").read_text(encoding="utf-8"))[
        "items"
    ]
    quota_path = args.results_dir / "quota_log.json"
    quota = json.loads(quota_path.read_text(encoding="utf-8")) if quota_path.is_file() else None
    results = args.results_dir
    composition = {
        path.stem.removeprefix("input_composition_"): json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(results.glob("input_composition_v*.json"))
    }
    baselines_path = results / f"baselines_{args.set}.json"
    baselines = (
        json.loads(baselines_path.read_text(encoding="utf-8")) if baselines_path.is_file() else None
    )
    tokens_path = results / "input_tokens.json"
    tokens = json.loads(tokens_path.read_text(encoding="utf-8")) if tokens_path.is_file() else None
    choice_path = results / "model_choice.json"
    choice = json.loads(choice_path.read_text(encoding="utf-8")) if choice_path.is_file() else None
    iterations_path = results / "prompt_iterations.json"
    iterations = (
        json.loads(iterations_path.read_text(encoding="utf-8"))
        if iterations_path.is_file()
        else None
    )
    page = render_results(
        load_retrieval(),
        runs,
        items,
        args.set,
        quota,
        composition or None,
        baselines,
        tokens,
        choice,
        iterations,
    )
    args.out.write_bytes(page.encode("utf-8"))
    print(f"wrote {args.out} ({len(runs)} agent answers from {args.results_dir})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
