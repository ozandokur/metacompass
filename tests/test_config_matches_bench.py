"""The configured embedding model and match signal are the ones the retrieval benchmark chose.

The choice is made by pre-registered rules in eval/run_retrieval_bench.py (choose_model,
choose_signal) from committed result files; this test stops config.py from drifting away
from those results.
"""

import json
from pathlib import Path

import pytest

import run_retrieval_bench as bench
from metacompass import config
from metacompass.config import Settings

RESULTS = Path(__file__).resolve().parents[1] / "eval" / "results"
MODELS = ("all-MiniLM-L6-v2", "bge-small-en-v1.5")


@pytest.fixture(scope="module")
def runs() -> dict[str, dict]:
    return {
        name: json.loads((RESULTS / f"retrieval_bench_{name}.json").read_text(encoding="utf-8"))
        for name in MODELS
    }


def test_embedding_model_is_the_ab_winner(runs):
    winner = bench.choose_model(runs)
    assert Settings().embedding_model.rsplit("/", 1)[-1] == winner


def test_match_signal_is_the_winners_best_variant(runs):
    signal = runs[bench.choose_model(runs)]["signal"]
    assert signal["kind"] == config.MATCH_SIGNAL
    assert signal["best"]["z"]["threshold"] == config.TAU_Z
    assert signal["best"]["cosine"]["threshold"] == config.TAU


def test_env_example_names_the_same_model():
    example = (RESULTS.parents[1] / ".env.example").read_text(encoding="utf-8")
    assert f"EMBEDDING_MODEL={Settings().embedding_model}\n" in example
