"""Makes a fresh checkout ready to answer at once: the data, the embedding model, the dense
index cache (spec §11.1).

    python scripts/warm_up.py

The Docker image runs this at build time, so the first visitor does not wait for the
embedding model to download and the documents to be encoded. It generates the data with
seed 42 only when data/raw is missing, so a checkout that already has data keeps it.
Deterministic, no LLM.
"""

import argparse
import sys
from pathlib import Path

from metacompass.config import PROJECT_ROOT, load_settings
from metacompass.data.generate import generate, write_outputs
from metacompass.retrieval.embedders import HashEmbedder, SentenceTransformerEmbedder
from metacompass.service import build_components

SEED = 42


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare data and indices for serving.")
    parser.add_argument("--data", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--embedder", choices=["model", "hash"], default="model")
    args = parser.parse_args(argv)
    if not (args.data / "raw").is_dir():
        write_outputs(generate(seed=SEED), args.data)
        print(f"generated the data with seed {SEED} in {args.data}")
    embedder = (
        HashEmbedder(dim=64)
        if args.embedder == "hash"
        else SentenceTransformerEmbedder(load_settings().embedding_model)
    )
    components = build_components(args.data, embedder)
    print(
        f"ready: {len(components.store.reports)} reports, indices cached in {args.data / 'cache'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
