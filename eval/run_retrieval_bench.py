"""Retrieval benchmark: BM25 vs dense vs hybrid on the 60-query set (spec §5.8, updated 2026-09-18).

No LLM is involved. For every query and mode it records where the target lands in the top
10. Headline metrics per query type:
  E  recall@1 / recall@5 of the named asset
  P  recall@5 and topic_hit@5 (any report of the right topic in the top 5). topic_hit
     separates "retrieval missed the topic" from "gold asks for one sibling out of several"
  D  pair_coverage@5: both members of the designed pair in the top 5. Picking the right
     member (the active one, the right variant) is the agent's job, measured in L1
recall@1 per type is kept as a diagnostic. The match signal is the same in every mode, so
both signal variants (absolute cosine tau, relative z tau_z) are swept once per query:
a query should be "strong" if it targets an existing asset (E, P, D), "weak" if not (N).

Usage: python eval/run_retrieval_bench.py --model sentence-transformers/all-MiniLM-L6-v2
"""

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import build_sets
from metacompass.data.store import MetadataStore
from metacompass.retrieval.corpus import build_retrievers
from metacompass.retrieval.embedders import Embedder, SentenceTransformerEmbedder

ROOT = Path(__file__).resolve().parents[1]
MODES = ("bm25", "dense", "hybrid")
RANKED_TYPES = ("E", "P", "D")
E_SUBTYPES = ("table name", "metric acronym", "report ID")
TOP_K = 10
TAU_GRID = [round(0.30 + 0.05 * i, 2) for i in range(9)]
TAU_Z_GRID = [round(0.50 + 0.25 * i, 2) for i in range(23)]  # fixed before any z was seen
INCUMBENT_MODEL = "all-MiniLM-L6-v2"
MRR_MARGIN, F1_MARGIN = 0.02, 0.005  # pre-registered model A/B rule, see choose_model


def rank_of(target: str, ranked_ids: list[str]) -> int | None:
    return ranked_ids.index(target) + 1 if target in ranked_ids else None


def recall_at(ranks: list[int | None], k: int) -> float:
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks) if ranks else 0.0


def mean_reciprocal_rank(ranks: list[int | None]) -> float:
    return sum(1 / r for r in ranks if r is not None) / len(ranks) if ranks else 0.0


def topic_hit(target: str, ranked_ids: list[str], subjects: dict[str, str], k: int) -> bool:
    """Is any report of the target's topic (the target or a sibling) in the top k?"""
    topic = subjects[target]
    return any(subjects.get(doc) == topic for doc in ranked_ids[:k])


def pair_covered(target: str, other: str, ranked_ids: list[str], k: int) -> bool:
    top = ranked_ids[:k]
    return target in top and other in top


def macro_f1(truth: list[str], pred: list[str]) -> float:
    """Mean F1 of the "strong" and "weak" classes; a class with no support scores 0."""
    scores = []
    for cls in ("strong", "weak"):
        tp = sum(1 for t, p in zip(truth, pred, strict=True) if t == cls and p == cls)
        fp = sum(1 for t, p in zip(truth, pred, strict=True) if t != cls and p == cls)
        fn = sum(1 for t, p in zip(truth, pred, strict=True) if t == cls and p != cls)
        scores.append(2 * tp / (2 * tp + fp + fn) if tp else 0.0)
    return sum(scores) / len(scores)


def tau_sweep(
    records: list[dict], taus: list[float], field: str = "top_dense_cosine"
) -> list[dict]:
    """macro-F1 and class rates for each threshold on one signal field."""
    truth = ["weak" if r["type"] == "N" else "strong" for r in records]
    rows = []
    for tau in taus:
        pred = ["strong" if r["exact_match"] or r[field] >= tau else "weak" for r in records]
        positives = [p for t, p in zip(truth, pred, strict=True) if t == "strong"]
        negatives = [p for t, p in zip(truth, pred, strict=True) if t == "weak"]
        rows.append(
            {
                "tau": tau,
                "macro_f1": round(macro_f1(truth, pred), 4),
                "strong_rate_positive": _rate(positives, "strong"),
                "weak_rate_negative": _rate(negatives, "weak"),
            }
        )
    return rows


def _rate(labels: list[str], label: str) -> float:
    return round(labels.count(label) / len(labels), 4) if labels else 0.0


def choose_tau(sweep: list[dict]) -> float:
    """Best macro-F1; on a plateau of equal scores take the middle (lower middle if even).

    The middle of a plateau is the choice least sensitive to small shifts in the signal.
    """
    best = max(row["macro_f1"] for row in sweep)
    tied = [row["tau"] for row in sweep if abs(row["macro_f1"] - best) < 1e-9]
    return tied[(len(tied) - 1) // 2]


def _best(sweep: list[dict]) -> tuple[float, float]:
    tau = choose_tau(sweep)
    return tau, next(row["macro_f1"] for row in sweep if row["tau"] == tau)


def choose_signal(cosine_sweep: list[dict], z_sweep: list[dict]) -> tuple[str, float, float]:
    """(kind, threshold, macro-F1) of the better variant; a tie keeps the absolute cosine."""
    cos_tau, cos_f1 = _best(cosine_sweep)
    z_tau, z_f1 = _best(z_sweep)
    if z_f1 > cos_f1 + 1e-9:
        return "z", z_tau, z_f1
    return "cosine", cos_tau, cos_f1


def signal_equals_exact_match(records: list[dict], kind: str, threshold: float) -> bool:
    """True if, at this threshold, only exact names/IDs ever come out strong."""
    field = "top_dense_cosine" if kind == "cosine" else "dense_z"
    return not any(not r["exact_match"] and r[field] >= threshold for r in records)


def choose_model(runs: dict[str, dict]) -> str:
    """Pre-registered A/B rule (written down before the runs, 2026-09-18).

    Primary: hybrid-mode MRR over E+P+D; a gap of at least MRR_MARGIN decides. Otherwise the
    better signal macro-F1 decides if the gap is at least F1_MARGIN. Otherwise the
    incumbent stays: changing the model has to earn its place.
    """

    def mrr(name: str) -> float:
        return runs[name]["modes"]["hybrid"]["all"]["mrr"]

    def f1(name: str) -> float:
        return runs[name]["signal"]["macro_f1"]

    best = INCUMBENT_MODEL if INCUMBENT_MODEL in runs else sorted(runs)[0]
    for name in sorted(runs):
        if name == best:
            continue
        if abs(mrr(name) - mrr(best)) >= MRR_MARGIN:
            better = mrr(name) > mrr(best)
        else:
            better = f1(name) - f1(best) >= F1_MARGIN
        if better:
            best = name
    return best


def _git_sha() -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout

    sha = git("rev-parse", "--short", "HEAD").strip() or "unknown"
    # Only tracked changes count: untracked result files are outputs, not code.
    dirty = git("status", "--porcelain", "--untracked-files=no").strip()
    return sha + ("-dirty" if dirty else "")


def _forbidden_first(record: dict, mode: str) -> bool:
    other, target = record["forbidden_ranks"][mode][0], record["ranks"][mode]
    return other is not None and (target is None or other < target)


def _summaries(records: list[dict]) -> dict:
    modes = {}
    for mode in MODES:
        summary = {}
        for kind in (*RANKED_TYPES, "all"):
            types = RANKED_TYPES if kind == "all" else (kind,)
            ranks = [r["ranks"][mode] for r in records if r["type"] in types]
            summary[kind] = {
                "n": len(ranks),
                "recall@1": round(recall_at(ranks, 1), 4),
                "recall@5": round(recall_at(ranks, 5), 4),
                "mrr": round(mean_reciprocal_rank(ranks), 4),
            }
        p = [r for r in records if r["type"] == "P"]
        d = [r for r in records if r["type"] == "D"]
        summary["P"]["topic_hit@5"] = round(sum(r["topic_hit5"][mode] for r in p) / len(p), 4)
        summary["D"]["pair_coverage@5"] = round(
            sum(r["pair_covered5"][mode] for r in d) / len(d), 4
        )
        summary["D"]["forbidden_above_target"] = round(
            sum(_forbidden_first(r, mode) for r in d) / len(d), 4
        )
        summary["E_recall@1_by_subtype"] = {
            sub: round(recall_at([r["ranks"][mode] for r in records if r["subtype"] == sub], 1), 4)
            for sub in E_SUBTYPES
        }
        modes[mode] = summary
    return modes


def _subtype(item: dict) -> str:
    if item["type"] == "E":
        return next(s for s in E_SUBTYPES if item["notes"].startswith(s))
    if item["type"] == "D":
        return "deprecated" if item["notes"].startswith("deprecated") else "near duplicate"
    return item["type"]


def run(
    data_dir: Path, set_path: Path, embedder: Embedder, cache_dir: Path, label: str = ""
) -> dict:
    store = MetadataStore.from_dir(data_dir)
    meta = json.loads((data_dir / "_meta.json").read_text(encoding="utf-8"))
    subjects = meta["report_subjects"]
    templates = build_sets.load_templates()
    retriever = build_retrievers(store, embedder, cache_dir)["assets"]
    items = json.loads(set_path.read_text(encoding="utf-8"))["items"]

    records = []
    for item in items:
        target = item["gold"]["answer_ids"][0] if item["gold"]["answer_ids"] else None
        forbidden = item["gold"]["forbidden_ids"]
        record = {
            "id": item["id"],
            "type": item["type"],
            "subtype": _subtype(item),
            "target": target,
            "ranks": {},
            "forbidden_ranks": {},
            "topic_hit5": {},
            "pair_covered5": {},
            "top3": {},
        }
        for mode in MODES:
            result = retriever.search(item["query"], mode=mode, top_k=TOP_K)
            ranked = [hit.doc_id for hit in result.hits]
            record["ranks"][mode] = rank_of(target, ranked) if target else None
            record["forbidden_ranks"][mode] = [rank_of(f, ranked) for f in forbidden]
            if target in subjects:
                record["topic_hit5"][mode] = topic_hit(target, ranked, subjects, k=5)
            if item["type"] == "D":
                record["pair_covered5"][mode] = pair_covered(target, forbidden[0], ranked, k=5)
            record["top3"][mode] = ranked[:3]
            record["exact_match"] = result.signal.exact_match  # identical in every mode
            record["top_dense_cosine"] = result.signal.top_dense_cosine
            record["dense_z"] = result.signal.dense_z
        if item["type"] == "P":
            report = store.report(target)
            text = report.description + " " + report.tags
            record["name_overlap"] = round(build_sets.name_overlap(item["query"], report.name), 4)
            record["description_overlap"] = round(
                build_sets.description_overlap(item["query"], text, templates), 4
            )
        records.append(record)

    cosine_sweep = tau_sweep(records, TAU_GRID, "top_dense_cosine")
    z_sweep = tau_sweep(records, TAU_Z_GRID, "dense_z")
    kind, threshold, f1 = choose_signal(cosine_sweep, z_sweep)
    chosen = next(
        r for r in (cosine_sweep if kind == "cosine" else z_sweep) if r["tau"] == threshold
    )
    overlaps = [r["description_overlap"] for r in records if r["type"] == "P"]
    return {
        "meta": {
            "label": label,
            "embedding_model": embedder.name,
            "data_seed": meta["seed"],
            "retrieval_set": set_path.resolve().relative_to(ROOT).as_posix(),
            "n_queries": {t: sum(1 for r in records if r["type"] == t) for t in "EPDN"},
            "top_k": TOP_K,
            "git_sha": _git_sha(),
            "run_date": date.today().isoformat(),
        },
        "modes": _summaries(records),
        "sweeps": {"cosine": cosine_sweep, "z": z_sweep},
        "signal": {
            "kind": kind,
            "threshold": threshold,
            "macro_f1": f1,
            "positives_strong_rate": chosen["strong_rate_positive"],
            "negatives_weak_rate": chosen["weak_rate_negative"],
            "equals_exact_match": signal_equals_exact_match(records, kind, threshold),
            "best": {
                variant: dict(zip(("threshold", "macro_f1"), _best(sweep), strict=True))
                for variant, sweep in (("cosine", cosine_sweep), ("z", z_sweep))
            },
        },
        "leakage": {
            "p_description_overlap_mean": round(sum(overlaps) / len(overlaps), 4),
            "p_queries_over_limit": sum(
                1 for o in overlaps if o > build_sets.MAX_DESCRIPTION_OVERLAP
            ),
            "limit": build_sets.MAX_DESCRIPTION_OVERLAP,
        },
        "per_query": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the retrieval benchmark (no LLM).")
    parser.add_argument("--model", required=True, help="sentence-transformers model name")
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--set", type=Path, default=ROOT / "eval" / "retrieval_set.json")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--label", default="", help="free text stored in the result metadata")
    args = parser.parse_args(argv)

    embedder = SentenceTransformerEmbedder(args.model)
    out = args.out or ROOT / "eval" / "results" / f"retrieval_bench_{embedder.name}.json"
    result = run(args.data, args.set, embedder, args.data / "cache", args.label)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(result, indent=2) + "\n").encode("utf-8"))

    print(f"{'mode':8} {'E r@1':>6} {'P r@5':>6} {'P topic':>8} {'D pair':>7} {'MRR':>6}")
    for mode, s in result["modes"].items():
        print(
            f"{mode:8} {s['E']['recall@1']:6.2f} {s['P']['recall@5']:6.2f} "
            f"{s['P']['topic_hit@5']:8.2f} {s['D']['pair_coverage@5']:7.2f} {s['all']['mrr']:6.2f}"
        )
    sig = result["signal"]
    print(
        f"signal: {sig['kind']} >= {sig['threshold']} (macro-F1 {sig['macro_f1']:.3f}; "
        f"best cosine {sig['best']['cosine']}, best z {sig['best']['z']}); "
        f"equals exact match: {sig['equals_exact_match']}"
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
