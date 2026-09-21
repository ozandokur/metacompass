"""Smoke test of the demo app (spec §10.2): it starts without a model, a prepared question
shows its recorded answer and trace, and free text stays off. The UI itself is checked by
hand at the phase checkpoint; this only proves the app imports, runs and answers."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import build_demo_cache
from metacompass.agent.llm import FakeLLM, LLMResponse
from metacompass.retrieval.embedders import HashEmbedder
from metacompass.service import build_components

APP = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"


@pytest.fixture(scope="module")
def generated_dir(writable_data_dir):
    """This module writes caches next to the data, so it gets a copy of the shared set."""
    return writable_data_dir


@pytest.fixture
def demo_cache(generated_dir, tmp_path) -> Path:
    body = {"answer": "Nobody here keeps salaries.", "answer_ids": [], "evidence_ids": [],
            "abstained": True}  # fmt: skip
    llm = FakeLLM([], then=LLMResponse(content=json.dumps(body), tool_calls=[], input_tokens=3,
                                       output_tokens=2, raw_model="fake"))  # fmt: skip
    dev = json.loads((build_demo_cache.ROOT / "eval" / "dev_set.json").read_text(encoding="utf-8"))[
        "items"
    ]
    chosen = build_demo_cache.select(dev, build_demo_cache.DEMO)
    components = build_components(generated_dir, HashEmbedder(dim=64))
    cache = build_demo_cache.build(chosen, components, llm, metadata={"model": "fake"})
    path = tmp_path / "cached_answers.json"
    path.write_text(json.dumps(cache), encoding="utf-8")
    return path


@pytest.fixture
def app(demo_cache, generated_dir, monkeypatch) -> AppTest:
    monkeypatch.setenv("METACOMPASS_DEMO_CACHE", str(demo_cache))
    monkeypatch.setenv("METACOMPASS_DATA_DIR", str(generated_dir))
    monkeypatch.setenv("METACOMPASS_EMBEDDER", "hash")
    # Blank settings count as missing: the app must work with no model at all.
    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY"):
        monkeypatch.setenv(name, "")
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    return at


def test_the_app_starts_without_a_model(app):
    assert not app.exception
    assert any("Synthetic" in md.value for md in app.markdown)


def test_a_prepared_question_shows_its_recorded_answer(app):
    labels = [button.label for button in app.sidebar.button]
    assert len(labels) == len(build_demo_cache.DEMO)
    app.sidebar.button[0].click().run()
    assert not app.exception
    shown = " ".join(md.value for md in app.markdown)
    assert "Nobody here keeps salaries." in shown
    assert app.expander  # the agent trace is on the page


def test_the_sidebar_says_how_the_prepared_questions_were_chosen(app):
    # They are dev questions the agent got right: a showcase, not a sample.
    captions = " ".join(caption.value for caption in app.sidebar.caption)
    assert "answered correctly" in captions and "test set" in captions


def test_without_a_model_there_is_no_free_text_box_only_a_pointer_to_run_it_locally(app):
    # Ozan, 2026-09-21: the public Space gets no model key (the eval owns the daily quota),
    # so a disabled box would only tease; it says how to ask your own question instead.
    assert len(app.sidebar.text_input) == 0
    captions = " ".join(caption.value for caption in app.sidebar.caption)
    assert "locally" in captions and "key" in captions
