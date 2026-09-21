"""The HTTP API (spec §10.1), driven through TestClient with a scripted model."""

import json

import pytest
from fastapi.testclient import TestClient

from metacompass.agent.llm import FakeLLM, LLMResponse
from metacompass.api import create_app
from metacompass.config import PROMPT_VERSION
from metacompass.retrieval.embedders import HashEmbedder
from metacompass.service import build_components


@pytest.fixture(scope="module")
def generated_dir(writable_data_dir):
    """This module writes caches next to the data, so it gets a copy of the shared set."""
    return writable_data_dir


def final(answer_ids: list[str], abstained: bool = False) -> LLMResponse:
    body = {"answer": "text", "answer_ids": answer_ids, "evidence_ids": [], "abstained": abstained}
    return LLMResponse(
        content=json.dumps(body), tool_calls=[], input_tokens=10, output_tokens=5, raw_model="fake"
    )


@pytest.fixture(scope="module")
def components(generated_dir):
    return build_components(generated_dir, HashEmbedder(dim=64))


@pytest.fixture
def client(components):
    # No IDs in the scripted answer: the grounding check would strip IDs no tool returned.
    app = create_app(components=components, llm=FakeLLM([], then=final([], abstained=True)))
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_health_names_the_seed_and_the_prompt_version(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "data_seed": 42, "prompt_version": PROMPT_VERSION}


def test_a_valid_question_returns_the_whole_agent_result(client):
    response = client.post("/ask", json={"question": "How much does Jill Rhodes earn?"})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"]["abstained"] is True
    assert body["config_name"] == "full"
    assert "steps" in body and body["stopped_reason"] == "final"


@pytest.mark.parametrize(
    "payload",
    [
        {"question": ""},
        {"question": "x" * 501},
        {"question": "Who owns RPT-0001?", "config": "A4"},  # ablations are not served
        {},
    ],
)
def test_bad_questions_are_refused_with_422(client, payload):
    assert client.post("/ask", json=payload).status_code == 422


def test_a_record_is_served_by_id(client, components):
    record_id = next(iter(components.store.reports))
    response = client.get(f"/records/{record_id}")
    assert response.status_code == 200
    assert record_id in json.dumps(response.json())


def test_a_missing_record_is_404(client):
    response = client.get("/records/RPT-9999")
    assert response.status_code == 404
    assert "RPT-9999" in response.json()["detail"]


def test_a_malformed_record_id_is_422(client):
    assert client.get("/records/not-an-id").status_code == 422


def test_an_internal_error_shows_no_stack_trace(components):
    class Broken:
        model = "broken"

        def chat(self, messages, tools, json_mode=False):
            raise RuntimeError("secret internals at /home/user/app.py line 12")

    app = create_app(components=components, llm=Broken())
    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.post("/ask", json={"question": "Who owns RPT-0001?"})
    # The loop turns provider failures into llm_error; either way nothing internal leaks.
    assert "secret internals" not in response.text
    assert "Traceback" not in response.text


def test_without_a_model_the_api_says_so_and_still_serves_records(components):
    app = create_app(components=components, llm=None)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        asked = test_client.post("/ask", json={"question": "Who owns RPT-0001?"})
        record = test_client.get(f"/records/{next(iter(components.store.reports))}")
    assert asked.status_code == 503
    assert "model" in asked.json()["detail"]
    assert record.status_code == 200
