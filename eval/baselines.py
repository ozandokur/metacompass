"""Trivial baselines: what a question scores without any LLM or reasoning (D25 plan).

Where the agent stands against these tells more than its accuracy alone. Each baseline
answers only the categories where it makes sense and is scored with scoring.py, exactly
like the agent:
  always_abstain         abstain on every question
  retrieval_top1         L1: the top search_assets hit; L4: the top find_similar_past_work hit
  recorded_owner         L2: the owner on record, without walking the succession chain
                         (the floor under ablation A3)
  all_heads              L5 broadcast: every department head
  default_depth_lineage  L3: the right trace_lineage call, but always with depth 3

Usage: python eval/baselines.py [--set test] [--data data/]
  writes eval/results/baselines_<set>.json
"""

import argparse
import json
import sys
from pathlib import Path

from configs import CONFIGS
from metacompass.config import load_settings
from metacompass.data.store import MetadataStore
from metacompass.graph import build_lineage_graph
from metacompass.retrieval.corpus import build_retrievers
from metacompass.retrieval.embedders import SentenceTransformerEmbedder
from metacompass.tools.registry import ToolRegistry, build_registry
from runinfo import ROOT, git_sha
from scoring import score

DEFAULT_DEPTH = 3
DESCRIPTIONS = {
    "always_abstain": "abstains on every question",
    "retrieval_top1": "the top search hit (L1) or past-work hit (L4), no reasoning",
    "recorded_owner": "the owner on record, no succession walk (the floor under A3)",
    "all_heads": "every department head, on the broadcast questions",
    "default_depth_lineage": "the right lineage call, always with depth 3",
}


def _answer(ids: list[str], abstained: bool = False) -> dict:
    return {"answer": "", "answer_ids": ids, "evidence_ids": [], "abstained": abstained}


def _top_hit(registry: ToolRegistry, tool: str, args: dict, key: str) -> list[str]:
    payload, _ = registry.call(tool, {**args, "top_k": 1})
    return [payload["hits"][0][key]] if payload.get("hits") else []


def answers(name: str, item: dict, registry: ToolRegistry, store: MetadataStore) -> dict | None:
    """The baseline's answer to one question, or None where it does not apply."""
    spec, category = item["gold_spec"], item["category"]
    if name == "always_abstain":
        return _answer([], abstained=True)
    if name == "retrieval_top1" and category == "L1":
        return _answer(_top_hit(registry, "search_assets", {"query": item["question"]}, "id"))
    if name == "retrieval_top1" and category == "L4":
        args = {"description": item["question"]}
        return _answer(_top_hit(registry, "find_similar_past_work", args, "request_id"))
    if name == "recorded_owner" and category == "L2":
        return _answer([store.get_asset(spec["asset_id"]).owner_id])
    if name == "all_heads" and item["subtype"] == "broadcast":
        heads = sorted(e.employee_id for e in store.employees.values() if e.is_department_head)
        return _answer(heads)
    if name == "default_depth_lineage" and category == "L3":
        upstream = spec["type"] == "upstream_tables"
        node = spec["node_id"] if upstream else spec["table_id"]
        args = {"node_id": node, "direction": "upstream" if upstream else "downstream",
                "depth": DEFAULT_DEPTH}  # fmt: skip
        payload, _ = registry.call("trace_lineage", args)
        wanted = "table" if upstream else "report"
        return _answer([n["id"] for n in payload["nodes"] if n["type"] == wanted])
    return None


def run_baselines(registry: ToolRegistry, store: MetadataStore, items: list[dict]) -> dict:
    result = {}
    for name, description in DESCRIPTIONS.items():
        per_category: dict[str, list[bool]] = {}
        for item in items:
            answer = answers(name, item, registry, store)
            if answer is not None:
                per_category.setdefault(item["category"], []).append(score(item, answer)["correct"])
        result[name] = {
            "description": description,
            "accuracy": {
                category: {"accuracy": sum(hits) / len(hits), "n": len(hits)}
                for category, hits in sorted(per_category.items())
            },
        }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score trivial baselines without an LLM.")
    parser.add_argument("--set", choices=["dev", "test"], default="test")
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    args = parser.parse_args(argv)
    settings = load_settings()
    store = MetadataStore.from_dir(args.data)
    embedder = SentenceTransformerEmbedder(settings.embedding_model)
    retrievers = build_retrievers(store, embedder, cache_dir=args.data / "cache")
    registry = build_registry(store, retrievers, build_lineage_graph(store), CONFIGS["A0"])
    items = json.loads((ROOT / "eval" / f"{args.set}_set.json").read_text(encoding="utf-8"))[
        "items"
    ]
    result = {
        "metadata": {"git_sha": git_sha(), "set": args.set, "embedder": embedder.name},
        "baselines": run_baselines(registry, store, items),
    }
    out = ROOT / "eval" / "results" / f"baselines_{args.set}.json"
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    for name, entry in result["baselines"].items():
        cells = ", ".join(f"{c} {v['accuracy']:.2f}" for c, v in entry["accuracy"].items())
        print(f"{name:22} {cells}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
