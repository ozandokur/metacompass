"""Recovers which record IDs each answer's model was actually shown (phase 8, no quota).

    python scripts/replay_tool_outputs.py [--set test]

The stored trace keeps only the first 300 characters of every tool result. That is enough to
read a trace, but not enough to answer the question the error analysis rests on: *was the
answer ever in front of the model, or did retrieval never offer it?* Judged on the truncated
summaries, a broadcast `impact_analysis` result looks as if it never named the people it
names, and the "gold never retrieved" number comes out far too high.

The tool calls themselves are stored in full, and the tools are deterministic over the fixed
data, so the calls can simply be made again: no model, no network, no quota. Each call goes
through the same registry the run used, built from that line's own configuration, because
A1/A2 retrieve differently and A3/A5 have a tool switched off. What comes back is the payload
the agent would have sent to the model, size cap and all, so the IDs in it are exactly the
IDs the model saw.

Output: eval/results/shown_ids_<set>.json, read by eval/report.py.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "src"))

OUTPUT_NAME = "shown_ids_test.json"


def key(line: dict) -> str:
    """One answer: its configuration, repeat and question."""
    return f"{line['config']}/{line['repeat']}/{line['item_id']}"


def ids_shown(line: dict, registry) -> list[str]:
    """Every record ID the tools put in front of the model, first appearance first."""
    seen: dict[str, None] = {}
    for step in line["result"]["steps"]:
        if step["kind"] != "tool":
            continue
        _, ids = registry.call(step["name"], step.get("arguments") or {})
        for record_id in ids:
            seen.setdefault(record_id, None)
    return list(seen)


def build_registries(data_dir: Path, embedder_name: str):
    """One registry per configuration, sharing the store, graph and retrievers."""
    from configs import CONFIGS
    from metacompass.data.store import MetadataStore
    from metacompass.graph import build_lineage_graph
    from metacompass.retrieval.corpus import build_retrievers
    from metacompass.retrieval.embedders import HashEmbedder, SentenceTransformerEmbedder
    from metacompass.tools.registry import build_registry

    store = MetadataStore.from_dir(data_dir)
    embedder = (
        HashEmbedder(dim=64)
        if embedder_name == "hash"
        else SentenceTransformerEmbedder(embedder_name)
    )
    retrievers = build_retrievers(store, embedder, cache_dir=data_dir / "cache")
    graph = build_lineage_graph(store)
    return {
        code: build_registry(store, retrievers, graph, config) for code, config in CONFIGS.items()
    }


def replay(results: Path, registries: dict, set_name: str = "test") -> dict[str, list[str]]:
    shown: dict[str, list[str]] = {}
    for path in sorted(results.glob(f"{set_name}_A*_r*.jsonl")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            line = json.loads(raw)
            if line.get("incomplete"):
                continue
            shown[key(line)] = ids_shown(line, registries[line["config"]])
    return shown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay stored tool calls to recover IDs shown.")
    parser.add_argument("--set", default="test", choices=["dev", "test"])
    parser.add_argument("--results-dir", type=Path, default=ROOT / "eval" / "results")
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--embedder", default=None, help="'hash' for a fast, unfaithful replay")
    args = parser.parse_args(argv)

    from metacompass.config import load_settings

    embedder = args.embedder or load_settings().embedding_model
    registries = build_registries(args.data, embedder)
    shown = replay(args.results_dir, registries, args.set)
    out = args.results_dir / f"shown_ids_{args.set}.json"
    out.write_text(
        json.dumps({"embedder": embedder, "shown": shown}, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    total = sum(len(ids) for ids in shown.values())
    print(f"wrote {out} ({len(shown)} answers, {total} IDs shown)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
