"""Retrieval benchmark: BM25 vs dense vs hybrid on the 60-query set, plus the tau sweep (spec §5.8).

No LLM is involved. For every query and mode it records the rank of the target asset in
the top 10, then reports recall@1, recall@5 and MRR per query type (E, P, D). The match
signal does not depend on the mode, so the tau sweep uses one signal per query: a query
should be "strong" if it targets an existing asset (E, P, D) and "weak" if not (N).
Tau is the grid value with the best macro-F1 over those two classes.

Usage: python eval/run_retrieval_bench.py [--data data/] [--out eval/results/retrieval_bench.json]
"""

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from metacompass.config import load_settings
from metacompass.data.store import MetadataStore
from metacompass.retrieval.corpus import build_retrievers
from metacompass.retrieval.embedders import Embedder, SentenceTransformerEmbedder

ROOT = Path(__file__).resolve().parents[1]
MODES = ("bm25", "dense", "hybrid")
RANKED_TYPES = ("E", "P", "D")
TOP_K = 10
TAU_GRID = [round(0.30 + 0.05 * i, 2) for i in range(9)]


def rank_of(target: str, ranked_ids: list[str]) -> int | None:
    return ranked_ids.index(target) + 1 if target in ranked_ids else None


def recall_at(ranks: list[int | None], k: int) -> float:
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks) if ranks else 0.0


def mean_reciprocal_rank(ranks: list[int | None]) -> float:
    return sum(1 / r for r in ranks if r is not None) / len(ranks) if ranks else 0.0


def macro_f1(truth: list[str], pred: list[str]) -> float:
    """Mean F1 of the "strong" and "weak" classes; a class with no support scores 0."""
    scores = []
    for cls in ("strong", "weak"):
        tp = sum(1 for t, p in zip(truth, pred, strict=True) if t == cls and p == cls)
        fp = sum(1 for t, p in zip(truth, pred, strict=True) if t != cls and p == cls)
        fn = sum(1 for t, p in zip(truth, pred, strict=True) if t == cls and p != cls)
        scores.append(2 * tp / (2 * tp + fp + fn) if tp else 0.0)
    return sum(scores) / len(scores)


def tau_sweep(records: list[dict], taus: list[float]) -> list[dict]:
    truth = ["weak" if r["type"] == "N" else "strong" for r in records]
    rows = []
    for tau in taus:
        pred = [
            "strong" if r["exact_match"] or r["top_dense_cosine"] >= tau else "weak"
            for r in records
        ]
        positives = [p for t, p in zip(truth, pred, strict=True) if t == "strong"]
        negatives = [p for t, p in zip(truth, pred, strict=True) if t == "weak"]
        rows.append(
            {
                "tau": tau,
                "macro_f1": round(macro_f1(truth, pred), 4),
                "strong_rate_positive": round(positives.count("strong") / len(positives), 4)
                if positives
                else 0.0,
                "weak_rate_negative": round(negatives.count("weak") / len(negatives), 4)
                if negatives
                else 0.0,
            }
        )
    return rows


def choose_tau(sweep: list[dict]) -> float:
    """Best macro-F1; on a plateau of equal scores take the middle (lower middle if even).

    The middle of a plateau is the choice least sensitive to small shifts in cosines.
    """
    best = max(row["macro_f1"] for row in sweep)
    tied = [row["tau"] for row in sweep if abs(row["macro_f1"] - best) < 1e-9]
    return tied[(len(tied) - 1) // 2]


def _git_sha() -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout

    sha = git("rev-parse", "--short", "HEAD").strip() or "unknown"
    # Only tracked changes count: untracked result files are outputs, not code.
    return sha + ("-dirty" if git("status", "--porcelain", "--untracked-files=no").strip() else "")


def run(data_dir: Path, set_path: Path, embedder: Embedder, cache_dir: Path) -> dict:
    store = MetadataStore.from_dir(data_dir)
    retriever = build_retrievers(store, embedder, cache_dir)["assets"]
    items = json.loads(set_path.read_text(encoding="utf-8"))["items"]

    records = []
    for item in items:
        target = item["gold"]["answer_ids"][0] if item["gold"]["answer_ids"] else None
        forbidden = item["gold"]["forbidden_ids"]
        record = {"id": item["id"], "type": item["type"], "target": target, "ranks": {}}
        record["forbidden_ranks"], record["top3"] = {}, {}
        for mode in MODES:
            result = retriever.search(item["query"], mode=mode, top_k=TOP_K)
            ranked = [hit.doc_id for hit in result.hits]
            record["ranks"][mode] = rank_of(target, ranked) if target else None
            record["forbidden_ranks"][mode] = [rank_of(f, ranked) for f in forbidden]
            record["top3"][mode] = ranked[:3]
            record["exact_match"] = result.signal.exact_match  # identical in every mode
            record["top_dense_cosine"] = result.signal.top_dense_cosine
        records.append(record)

    modes = {}
    for mode in MODES:
        summary = {}
        for kind in (*RANKED_TYPES, "all"):
            ranks = [
                r["ranks"][mode]
                for r in records
                if r["type"] in (RANKED_TYPES if kind == "all" else (kind,))
            ]
            summary[kind] = {
                "n": len(ranks),
                "recall@1": round(recall_at(ranks, 1), 4),
                "recall@5": round(recall_at(ranks, 5), 4),
                "mrr": round(mean_reciprocal_rank(ranks), 4),
            }
        # D queries: how often the wrong member of the pair ranks above the right one.
        d_records = [r for r in records if r["type"] == "D"]
        summary["D"]["forbidden_above_target"] = round(
            sum(
                1
                for r in d_records
                if r["forbidden_ranks"][mode][0] is not None
                and (r["ranks"][mode] is None or r["forbidden_ranks"][mode][0] < r["ranks"][mode])
            )
            / len(d_records),
            4,
        )
        modes[mode] = summary

    sweep = tau_sweep(records, TAU_GRID)
    tau = choose_tau(sweep)
    chosen = next(row for row in sweep if row["tau"] == tau)
    return {
        "meta": {
            "embedding_model": embedder.name,
            "data_seed": json.loads((data_dir / "_meta.json").read_text(encoding="utf-8"))["seed"],
            "retrieval_set": set_path.relative_to(ROOT).as_posix(),
            "n_queries": {kind: sum(1 for r in records if r["type"] == kind) for kind in "EPDN"},
            "top_k": TOP_K,
            "git_sha": _git_sha(),
            "run_date": date.today().isoformat(),
        },
        "modes": modes,
        "tau_sweep": sweep,
        "chosen_tau": tau,
        "negatives_weak_rate": chosen["weak_rate_negative"],
        "positives_strong_rate": chosen["strong_rate_positive"],
        "per_query": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the retrieval benchmark (no LLM).")
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--set", type=Path, default=ROOT / "eval" / "retrieval_set.json")
    parser.add_argument(
        "--out", type=Path, default=ROOT / "eval" / "results" / "retrieval_bench.json"
    )
    args = parser.parse_args(argv)

    embedder = SentenceTransformerEmbedder(load_settings().embedding_model)
    result = run(args.data, args.set, embedder, args.data / "cache")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes((json.dumps(result, indent=2) + "\n").encode("utf-8"))

    print(f"{'mode':8} {'E r@1':>6} {'P r@1':>6} {'D r@1':>6} {'MRR':>6}")
    for mode, s in result["modes"].items():
        print(
            f"{mode:8} {s['E']['recall@1']:6.2f} {s['P']['recall@1']:6.2f} "
            f"{s['D']['recall@1']:6.2f} {s['all']['mrr']:6.2f}"
        )
    print(
        f"chosen tau = {result['chosen_tau']}, negatives flagged weak = {result['negatives_weak_rate']:.0%}"
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
