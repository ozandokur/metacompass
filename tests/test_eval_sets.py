"""Checks on the committed evaluation sets (spec §9.2, §9.5). Phase 2: the retrieval set."""

import json
import re
from pathlib import Path

import pytest

import build_sets
import gold
from conftest import SEED

ROOT = Path(__file__).resolve().parents[1]
RETRIEVAL_SET = ROOT / "eval" / "retrieval_set.json"

pytestmark = pytest.mark.skipif(SEED != 42, reason="the committed sets describe the seed-42 data")


@pytest.fixture(scope="module")
def items() -> list[dict]:
    return json.loads(RETRIEVAL_SET.read_text(encoding="utf-8"))["items"]


@pytest.fixture(scope="module")
def data(generated_dir):
    return gold.load_raw(generated_dir), gold.load_meta(generated_dir)


def _names(raw) -> dict[str, str]:
    names = dict(zip(raw["reports"]["report_id"], raw["reports"]["name"], strict=True))
    names |= dict(zip(raw["tables"]["table_id"], raw["tables"]["name"], strict=True))
    names |= dict(zip(raw["metrics"]["metric_id"], raw["metrics"]["name"], strict=True))
    return names


def test_counts_per_type(items):
    counts = {kind: sum(1 for i in items if i["type"] == kind) for kind in "EPDN"}
    assert counts == {"E": 15, "P": 15, "D": 15, "N": 15}
    assert len({i["id"] for i in items}) == 60
    assert len({i["query"] for i in items}) == 60


def test_committed_set_matches_the_builder(data):
    raw, meta = data
    rebuilt = build_sets.build_retrieval_set(raw, meta, build_sets.load_templates(), seed=42)
    committed = json.loads(RETRIEVAL_SET.read_text(encoding="utf-8"))
    assert committed["items"] == rebuilt, "eval/retrieval_set.json is stale: rebuild it"


def test_gold_recomputes_from_gold_spec(items, data):
    raw, meta = data
    for item in items:
        assert gold.compute_gold(item["gold_spec"], raw, meta) == item["gold"], item["id"]


def test_answerable_targets_exist_and_negatives_have_none(items, data):
    names = _names(data[0])
    for item in items:
        if item["type"] == "N":
            assert item["gold"] == {"answer_ids": [], "forbidden_ids": [], "should_abstain": True}
        else:
            assert item["gold"]["answer_ids"][0] in names
            assert item["gold"]["should_abstain"] is False


def test_paraphrase_queries_barely_overlap_the_target_name(items, data):
    names = _names(data[0])
    for item in items:
        if item["type"] == "P":
            target = item["gold"]["answer_ids"][0]
            assert build_sets.name_overlap(item["query"], names[target]) <= 0.30, item["id"]


def test_disambiguation_targets_the_active_member_of_a_designed_pair(items, data):
    raw, meta = data
    status = dict(zip(raw["reports"]["report_id"], raw["reports"]["status"], strict=True))
    pairs = {frozenset(p) for p in meta["near_duplicate_pairs"]}
    pairs |= {frozenset(p) for p in meta["deprecated_map"].items()}
    for item in items:
        if item["type"] == "D":
            target, (forbidden,) = item["gold"]["answer_ids"][0], item["gold"]["forbidden_ids"]
            assert status[target] == "active"
            assert frozenset((target, forbidden)) in pairs


def test_negative_queries_name_nothing_that_exists(items, data):
    def norm(text: str) -> str:
        return " " + " ".join(re.findall(r"[a-z0-9]+", text.lower())) + " "

    names = [norm(n) for n in _names(data[0]).values()]
    for item in items:
        if item["type"] == "N":
            assert not [n for n in names if n in norm(item["query"])], item["id"]


def test_paraphrase_queries_barely_overlap_the_target_description(items, data):
    # Name overlap alone let 9 of 15 v1 queries reuse description words, which fed BM25 the
    # answer. Content words of the query (minus stop words and the template's own words) may
    # hit the target's description and tags at most 20% of the time.
    raw, _ = data
    reports = raw["reports"].set_index("report_id")
    for item in items:
        if item["type"] == "P":
            target = item["gold"]["answer_ids"][0]
            text = reports.at[target, "description"] + " " + reports.at[target, "tags"]
            overlap = build_sets.description_overlap(
                item["query"], text, build_sets.load_templates()
            )
            assert overlap <= 0.20, (item["id"], round(overlap, 2))


def test_paraphrase_targets_are_unique_by_subject_and_dimension(items, data):
    _, meta = data
    combos = [
        (meta["report_subjects"][r], meta["report_qualifiers"][r]) for r in meta["report_subjects"]
    ]
    for item in items:
        if item["type"] == "P":
            target = item["gold"]["answer_ids"][0]
            combo = (meta["report_subjects"][target], meta["report_qualifiers"][target])
            assert combos.count(combo) == 1, (item["id"], combo)
            assert combo[1] != "none", item["id"]
