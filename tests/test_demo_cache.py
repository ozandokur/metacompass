"""The demo's prepared answers (spec §10.2, phase 7): which questions, from where, and the
guarantee that none of them comes from the test set."""

import json

import pytest

import build_demo_cache
from metacompass.agent.llm import FakeLLM, LLMResponse
from metacompass.retrieval.embedders import HashEmbedder
from metacompass.service import build_components

ROOT_SETS = build_demo_cache.ROOT / "eval"


@pytest.fixture(scope="module")
def generated_dir(writable_data_dir):
    """This module writes caches next to the data, so it gets a copy of the shared set."""
    return writable_data_dir


def dev_items() -> list[dict]:
    return json.loads((ROOT_SETS / "dev_set.json").read_text(encoding="utf-8"))["items"]


def test_the_demo_has_one_question_per_category_and_two_mixed():
    categories = [item_id.split("-")[1] for _, item_id in build_demo_cache.DEMO]
    assert sorted(categories) == ["L1", "L2", "L3", "L4", "L5", "L6", "MX", "MX"]


def test_every_demo_question_is_a_dev_question_and_none_is_in_the_test_set():
    # Phase 7 task 3: showing test questions would leak the test set into the demo.
    dev = {item["id"]: item for item in dev_items()}
    test = json.loads((ROOT_SETS / "test_set.json").read_text(encoding="utf-8"))["items"]
    test_questions = {item["question"] for item in test}
    for _, item_id in build_demo_cache.DEMO:
        assert item_id in dev
        assert dev[item_id]["question"] not in test_questions


def test_a_demo_question_outside_the_dev_set_is_refused():
    with pytest.raises(ValueError, match="dev-L9-99"):
        build_demo_cache.select(dev_items(), [("Lookup", "dev-L9-99")])


def test_the_cache_file_carries_each_answer_with_its_provenance(generated_dir):
    body = {"answer": "Nothing found.", "answer_ids": [], "evidence_ids": [], "abstained": True}
    llm = FakeLLM([], then=LLMResponse(content=json.dumps(body), tool_calls=[], input_tokens=1,
                                       output_tokens=1, raw_model="fake"))  # fmt: skip
    components = build_components(generated_dir, HashEmbedder(dim=64))
    chosen = build_demo_cache.select(dev_items(), build_demo_cache.DEMO[:2])
    cache = build_demo_cache.build(chosen, components, llm, metadata={"model": "fake"})
    assert [q["item_id"] for q in cache["questions"]] == [i for _, i in build_demo_cache.DEMO[:2]]
    first = cache["questions"][0]
    assert first["label"] == build_demo_cache.DEMO[0][0]
    assert first["result"]["answer"]["abstained"] is True
    assert first["result"]["steps"]  # the trace travels with the answer
    assert cache["metadata"]["model"] == "fake"
