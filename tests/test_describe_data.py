"""The data card is generated from the data and must match what the generator produces now."""

from pathlib import Path

import pytest

import describe_data
from conftest import SEED

ROOT = Path(__file__).resolve().parents[1]


def test_card_covers_every_section(generated_dir):
    card = describe_data.build_card(generated_dir)
    assert "all data here is synthetic" in card.lower()
    for table in describe_data.TABLES:
        assert f"### {table}" in card
    for code in ["N1", "N2", "N3", "N4", "N5", "N6", "N7", "S1", "S2", "C2", "C3", "C4"]:
        assert f"| {code} |" in card


def test_committed_card_is_up_to_date(generated_dir):
    if SEED != 42:
        pytest.skip("the committed card describes the seed-42 dataset")
    committed = (ROOT / "docs" / "data_card.md").read_text(encoding="utf-8")
    assert committed == describe_data.build_card(generated_dir), (
        "docs/data_card.md is stale: run python scripts/describe_data.py"
    )
