"""Shared pytest fixtures.

The synthetic dataset is generated once per test session into a temporary folder, so
tests always check the current generator code and never a stale data/ directory.
"""

import json
import os
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
def generated_dir(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("generated")
    write_outputs(generate(seed=SEED), out)
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
