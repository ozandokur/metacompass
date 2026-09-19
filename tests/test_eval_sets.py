"""Checks on the committed evaluation sets (spec §9.2, §9.5): the retrieval benchmark set,
then the dev and test question sets."""

import json
import re
from collections import Counter
from pathlib import Path

import pytest

import build_sets
import gold
import question_sets
import set_rules
from conftest import SEED

ROOT = Path(__file__).resolve().parents[1]
RETRIEVAL_SET = ROOT / "eval" / "retrieval_set.json"
QUESTION_SETS = {name: ROOT / "eval" / f"{name}_set.json" for name in ("dev", "test")}

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


# ====================================================================== dev and test sets


@pytest.fixture(scope="module")
def qsets() -> dict[str, list[dict]]:
    return {
        name: json.loads(path.read_text(encoding="utf-8"))["items"]
        for name, path in QUESTION_SETS.items()
    }


@pytest.fixture(scope="module")
def retrieval_targets(items) -> set[str]:
    return {i["gold"]["answer_ids"][0] for i in items if i["gold"]["answer_ids"]}


def _all(qsets):
    return [(name, item) for name, items in qsets.items() for item in items]


def test_question_counts_follow_the_plan(qsets):
    for name, plan in (("test", question_sets.TEST_PLAN), ("dev", question_sets.DEV_PLAN)):
        counts = Counter((i["category"], i["subtype"]) for i in qsets[name])
        expected = {(c, sub): n for c, subs in plan.items() for sub, n in subs.items()}
        assert dict(counts) == expected, name
    # Spec §9.2 category totals.
    assert Counter(i["category"] for i in qsets["test"]) == {
        "L1": 15, "L2": 15, "L3": 15, "L4": 15, "L5": 10, "L6": 15, "MX": 15,
    }  # fmt: skip
    assert Counter(i["category"] for i in qsets["dev"]) == {
        "L1": 4, "L2": 5, "L3": 4, "L4": 4, "L5": 3, "L6": 6, "MX": 4,
    }  # fmt: skip
    for name, item in _all(qsets):
        assert item["id"].startswith("dev-" if name == "dev" else item["category"]), item["id"]
    ids = [item["id"] for _, item in _all(qsets)]
    questions = [item["question"] for _, item in _all(qsets)]
    assert len(set(ids)) == len(ids) == 130
    assert len(set(questions)) == len(questions)


def test_committed_question_sets_match_the_builder(qsets, data, items):
    raw, meta = data
    rebuilt = question_sets.build_question_sets(raw, meta, set_rules.load_templates(), 42, items)
    for name in ("dev", "test"):
        assert qsets[name] == rebuilt[name], f"eval/{name}_set.json is stale: rebuild it"


def test_question_gold_recomputes_from_gold_spec(qsets, data):
    raw, meta = data
    for _, item in _all(qsets):
        assert gold.compute_gold(item["gold_spec"], raw, meta) == item["gold"], item["id"]


def test_dev_and_test_share_no_primary_target(qsets):
    dev = {i["primary_target"] for i in qsets["dev"]}
    test = {i["primary_target"] for i in qsets["test"]}
    assert dev & test == set()
    for name in ("dev", "test"):  # and no target is asked about twice within a set
        targets = [i["primary_target"] for i in qsets[name]]
        assert len(set(targets)) == len(targets), name


def test_l1_never_targets_a_retrieval_set_asset(qsets, retrieval_targets):
    # Spec §9.2 (2026-09-18): tau and the model were chosen on the retrieval set.
    for _, item in _all(qsets):
        if item["category"] == "L1":
            assert not set(item["gold"]["answer_ids"]) & retrieval_targets, item["id"]


def test_gold_ids_are_not_given_away_in_the_question(qsets):
    for _, item in _all(qsets):
        if not item.get("allow_id_in_question"):
            leaked = [i for i in item["gold"]["answer_ids"] if i in item["question"]]
            assert leaked == [], item["id"]


def test_scoring_rule_per_category(qsets):
    expected = {
        "L1": "contains_all", "L2": "contains_all", "L3": "set_f1", "L4": "contains_any",
        "L6": "abstain",
    }  # fmt: skip
    for _, item in _all(qsets):
        rule = item["scoring"]
        single = len(item["gold"]["answer_ids"]) == 1
        if item["category"] in expected:
            assert rule == expected[item["category"]], item["id"]
        elif item["category"] == "L5":
            assert rule == ("set_f1" if item["subtype"] == "individual" else "contains_all")
        else:
            # Q-F5-1b: F1 on one ID collapses to exact match and puts "right person plus one
            # more" (F1 0.67) with "no idea"; a single-ID gold is scored contains_all.
            set_rule = item["subtype"] == "metric_owners" and not single
            assert rule == ("set_f1" if set_rule else "contains_all"), item["id"]


def test_no_set_f1_question_has_a_single_gold_id(qsets):
    for _, item in _all(qsets):
        if item["scoring"] == "set_f1":
            assert len(item["gold"]["answer_ids"]) > 1, item["id"]


def test_answerable_questions_have_gold_and_l6_abstains(qsets):
    for _, item in _all(qsets):
        if item["category"] == "L6":
            assert item["gold"]["should_abstain"] is True, item["id"]
            assert item["gold"]["answer_ids"] == [], item["id"]
        else:
            assert item["gold"]["should_abstain"] is False, item["id"]
            assert item["gold"]["answer_ids"], item["id"]


def test_paraphrased_questions_do_not_borrow_the_target_words(qsets, data):
    raw, meta = data
    templates = set_rules.load_templates()
    reports = raw["reports"].set_index("report_id")
    for _, item in _all(qsets):
        question = item["question"]
        if (item["category"], item["subtype"]) == ("L1", "paraphrase"):
            target = item["gold"]["answer_ids"][0]
            text = reports.at[target, "description"] + " " + reports.at[target, "tags"]
            frame = set_rules.frame_words(templates["questions"]["L1"]["paraphrase"])
            assert set_rules.name_overlap(question, reports.at[target, "name"]) <= 0.30
            assert set_rules.content_overlap(question, text, frame) <= 0.20, item["id"]
        topic = question_sets.topic_of(item)
        if topic is not None:
            text = question_sets.cluster_text(raw, meta, topic)
            frame = question_sets.question_frame(templates, item)
            assert set_rules.content_overlap(question, text, frame) <= 0.20, item["id"]


def test_l5_questions_follow_the_notify_modes(qsets, data):
    raw, _ = data
    layer = dict(zip(raw["tables"]["table_id"], raw["tables"]["layer"], strict=True))
    for name, items in qsets.items():
        l5 = [i for i in items if i["category"] == "L5"]
        for item in l5:
            people = gold.impact_notify(raw, item["gold_spec"]["table_id"])["people"]
            if item["subtype"] == "individual":
                assert 2 <= len(people) <= 20, item["id"]
                assert "min_mentioned_count" not in item["gold"]
            else:
                assert len(people) > 20, item["id"]
                assert item["gold"]["min_mentioned_count"] == len(people)
                # Not every department: "announce to all heads" must not be right by default.
                departments = raw["employees"]["department"].nunique()
                assert len(item["gold"]["answer_ids"]) < departments, item["id"]
                assert str(len(people)) in item["notes"]
                # Announcing to a department nobody in it needs to hear about is wrong.
                heads = set(item["gold"]["answer_ids"]) | set(item["gold"]["forbidden_ids"])
                assert len(heads) == departments and item["gold"]["forbidden_ids"], item["id"]
        individual = [layer[i["gold_spec"]["table_id"]] for i in l5 if i["subtype"] == "individual"]
        assert "mart" in individual and any(x != "mart" for x in individual), name
        broadcast = [tuple(i["gold"]["answer_ids"]) for i in l5 if i["subtype"] == "broadcast"]
        assert len(set(broadcast)) == len(broadcast), name  # different department sets


def test_the_coo_is_in_as_few_broadcast_golds_as_the_data_allows(qsets, data):
    # Q-F5-2: EMP-001 (COO, the root) must not be a free point in every broadcast answer.
    # The data offers three distinct head sets and two of them contain EMP-001, so with
    # three distinct test questions the fewest possible is 2 (geçici karar, Q-F5-2b).
    raw, meta = data
    minimum = question_sets.fewest_coo_broadcasts(raw, meta, len(
        [i for i in qsets["test"] if i["subtype"] == "broadcast"]))  # fmt: skip
    test_golds = [i["gold"]["answer_ids"] for i in qsets["test"] if i["subtype"] == "broadcast"]
    assert sum("EMP-001" in g for g in test_golds) == minimum
    assert minimum == 2


def test_disambiguation_questions_ask_in_plain_words(qsets):
    # Q-F5-1a: "Which report is X, the version limited to my territory?" read badly.
    for _, item in _all(qsets):
        if item["subtype"] == "disambiguation" and "near duplicate" in item["notes"]:
            assert item["question"].startswith("Is there "), item["question"]
            assert "the version" not in item["question"] and ", the " not in item["question"]


def test_mx_chains_are_linked_and_use_individual_tables(qsets, data):
    raw, meta = data
    requests = raw["requests"].set_index("request_id")
    for _, item in _all(qsets):
        if item["category"] != "MX":
            continue
        steps = item["gold_spec"]["steps"]
        first = gold.compute_gold(steps[0], raw, meta)
        if item["subtype"] == "metric_owners":
            tables = first["answer_ids"]
            assert steps[0] == {
                "type": "upstream_tables",
                "node_id": item["primary_target"],
                "depth": 1,
            }
            assert sorted(steps[1]["asset_ids"]) == tables, item["id"]
            for table in tables:  # D24: MX chains only use tables in individual mode
                assert len(gold.impact_notify(raw, table)["people"]) <= 20, (item["id"], table)
        elif item["subtype"] == "deprecated_replacement":
            old = item["primary_target"]
            assert first["answer_ids"] == [meta["deprecated_map"][old]], item["id"]
            assert steps[1]["asset_id"] == meta["deprecated_map"][old]
        else:
            produced = {requests.at[r, "resulting_report_id"] for r in first["answer_ids"]} - {""}
            assert produced == {steps[1]["asset_id"]}, item["id"]


def test_l2_subtypes_match_the_ownership_structure(qsets, data):
    raw, meta = data
    owners = gold._owners(raw)
    people = gold._people(raw)
    heads = gold._heads(people)
    chains = meta["chains"]
    for name, items in qsets.items():
        for item in (i for i in items if i["category"] == "L2"):
            owner = owners[item["gold_spec"]["asset_id"]]
            sub = item["subtype"]
            if sub == "active":
                assert people[owner]["status"] == "active", item["id"]
            elif sub in ("S1", "S2"):
                assert owner in chains[sub], item["id"]
            else:
                heads_of = {
                    c[0]: split
                    for c, split in zip(chains[sub], meta["eval_split"][sub], strict=True)
                }
                assert heads_of[owner] == name, item["id"]  # the chain belongs to this set
            if sub == "C4":
                assert item["gold"]["answer_ids"] == [heads[people[owner]["department"]]]


def test_l3_gold_sets_are_small_enough_to_list(qsets):
    for _, item in _all(qsets):
        if item["category"] == "L3":
            assert 2 <= len(item["gold"]["answer_ids"]) <= 15, item["id"]


def test_l6_questions_ask_for_something_that_is_not_there(qsets, data):
    raw, meta = data
    reserved = json.loads((set_rules.VOCAB_DIR / "reserved_near_miss.json").read_text("utf-8"))
    topics = {t["topic"] for t in reserved["unused_request_topics"]}
    names = [set_rules.norm(n) for n in _names(raw).values()]
    for _, item in _all(qsets):
        if item["category"] != "L6":
            continue
        if item["subtype"] == "near_miss":
            assert not [n for n in names if n in set_rules.norm(item["question"])], item["id"]
        if item["subtype"] == "never_done":
            assert item["primary_target"].removeprefix("topic:") in topics, item["id"]
        if item["subtype"] == "null_formula":
            assert item["primary_target"] in meta["null_formula_metrics"], item["id"]


def test_builder_refuses_a_question_that_gives_its_answer_away(qsets, data, retrieval_targets):
    raw, meta = data
    broken = [dict(i) for i in qsets["test"]]
    l2 = next(i for i in broken if i["category"] == "L2")
    l2["question"] = f"Is it {l2['gold']['answer_ids'][0]}? " + l2["question"]
    with pytest.raises(ValueError, match="gives away"):
        question_sets.validate_question_set(
            "test", broken, raw, meta, set_rules.load_templates(), retrieval_targets
        )


def test_review_sample_shows_three_questions_per_category(qsets, data):
    text = question_sets.review_sample(qsets["test"], data[0])
    for category in ("L1", "L2", "L3", "L4", "L5", "L6", "MX"):
        assert text.count(f"| {category}-") == 3, category
    # Q-F5-1c: the stated count is a note the scorer never reads; it has its own column.
    assert "| unscored note |" in text
    assert "must mention" not in text.split("| unscored note |")[0]


def test_lineage_candidate_counts_add_up(data):
    # Q-F5-4: how many L3 targets the 2-15 ID rule removes, and whether the kept ones are
    # the shallow part of the graph.
    raw, meta = data
    report = question_sets.lineage_candidates(raw, meta)
    assert set(report) == {"metric_upstream", "report_upstream", "staging_downstream"}
    for stats in report.values():
        assert stats["kept"] + stats["too_few"] + stats["too_many"] == stats["candidates"]
        assert stats["kept"] >= 1
        assert set(stats["full_lineage_size"]) == {"kept", "removed"}
