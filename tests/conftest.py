"""Shared pytest fixtures.

The synthetic dataset is generated once per test session into a temporary folder, so
tests always check the current generator code and never a stale data/ directory.
"""

import json
import os
import shutil
from pathlib import Path

import pandas as pd
import pytest

from metacompass.data.generate import generate, write_outputs

# Override to check that the invariants hold for other seeds too (the gate uses 42).
SEED = int(os.environ.get("METACOMPASS_TEST_SEED", "42"))
TABLE_FILES = [
    "employees",
    "reports",
    "tables",
    "report_table_edges",
    "table_table_edges",
    "metrics",
    "requests",
]


@pytest.fixture(scope="session")
def pristine_data_dir(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("generated")
    write_outputs(generate(seed=SEED), out)
    return out


@pytest.fixture(scope="session")
def generated_dir(pristine_data_dir) -> Path:
    return pristine_data_dir


@pytest.fixture(scope="session")
def writable_data_dir(pristine_data_dir, tmp_path_factory) -> Path:
    """A copy of the dataset for tests that write caches next to it (embeddings, LLM answers).

    The generated set must stay exactly what the generator wrote: the determinism test hashes
    every file in it, so a cache written there by an earlier test would fail it. Modules that
    write override generated_dir with this copy.
    """
    out = tmp_path_factory.mktemp("writable") / "data"
    shutil.copytree(pristine_data_dir, out)
    return out


@pytest.fixture(scope="session")
def raw(generated_dir) -> dict[str, pd.DataFrame]:
    """All seven CSVs as string DataFrames; missing values are empty strings."""
    return {
        name: pd.read_csv(generated_dir / "raw" / f"{name}.csv", dtype=str, keep_default_na=False)
        for name in TABLE_FILES
    }


@pytest.fixture(scope="session")
def meta(generated_dir) -> dict:
    return json.loads((generated_dir / "_meta.json").read_text(encoding="utf-8"))


MINI_DIR = Path(__file__).parent / "fixtures" / "mini"


@pytest.fixture(scope="session")
def mini_dir() -> Path:
    """Hand-written fixture data; see tests/fixtures/mini/README.md for its cases."""
    return MINI_DIR


@pytest.fixture(scope="session")
def mini_ctx(mini_dir, tmp_path_factory):
    """Tool context over the mini fixture, with the network-free HashEmbedder."""
    from metacompass.data.store import MetadataStore
    from metacompass.graph import build_lineage_graph
    from metacompass.retrieval.corpus import build_retrievers
    from metacompass.retrieval.embedders import HashEmbedder
    from metacompass.tools.schemas import ToolContext

    store = MetadataStore.from_dir(mini_dir)
    cache = tmp_path_factory.mktemp("mini_cache")
    return ToolContext(
        store=store,
        retrievers=build_retrievers(store, HashEmbedder(dim=64), cache_dir=cache),
        graph=build_lineage_graph(store),
    )


@pytest.fixture(scope="session")
def real_ctx(generated_dir, tmp_path_factory):
    """Tool context over the generated seed-42 data, with the HashEmbedder."""
    from metacompass.data.store import MetadataStore
    from metacompass.graph import build_lineage_graph
    from metacompass.retrieval.corpus import build_retrievers
    from metacompass.retrieval.embedders import HashEmbedder
    from metacompass.tools.schemas import ToolContext

    store = MetadataStore.from_dir(generated_dir)
    cache = tmp_path_factory.mktemp("real_cache")
    return ToolContext(
        store=store,
        retrievers=build_retrievers(store, HashEmbedder(dim=64), cache_dir=cache),
        graph=build_lineage_graph(store),
    )
