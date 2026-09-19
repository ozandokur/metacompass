"""The Gemini provider client (spec §8.1, D25): message conversion, response parsing and HTTP
errors, all against a mocked transport; no network."""

import json

import httpx
import pytest

from metacompass.agent.llm import (
    GeminiClient,
    ProviderError,
    RateLimited,
    ToolCall,
    gemini_request,
    gemini_response,
    make_llm,
)
from metacompass.config import Settings

TOOLS = [
    {
        "name": "get_record",
        "description": "Get a record.",
        "parameters": {"type": "object", "properties": {"record_id": {"type": "string"}}},
    }
]


def conversation() -> list[dict]:
    return [
        {"role": "system", "content": "You are MetaCompass."},
        {"role": "user", "content": "What is RPT-0001?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "name": "get_record", "arguments": {"record_id": "RPT-0001"}},
                {"id": "c2", "name": "get_record", "arguments": {"record_id": "RPT-0002"}},
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "name": "get_record", "content": '{"a":1}'},
        {"role": "tool", "tool_call_id": "c2", "name": "get_record", "content": '{"b":2}'},
        {"role": "user", "content": "No more tools."},
    ]


def test_request_maps_the_conversation_to_generate_content():
    body = gemini_request(conversation(), TOOLS, json_mode=True)
    assert body["systemInstruction"] == {"parts": [{"text": "You are MetaCompass."}]}
    user, model, results = body["contents"]
    assert user == {"role": "user", "parts": [{"text": "What is RPT-0001?"}]}
    assert model["role"] == "model"
    assert model["parts"][0] == {
        "functionCall": {"id": "c1", "name": "get_record", "args": {"record_id": "RPT-0001"}}
    }
    # Both tool results and the next instruction travel in one user turn.
    assert results["role"] == "user"
    assert results["parts"] == [
        {"functionResponse": {"id": "c1", "name": "get_record", "response": {"a": 1}}},
        {"functionResponse": {"id": "c2", "name": "get_record", "response": {"b": 2}}},
        {"text": "No more tools."},
    ]
    assert body["tools"] == [
        {
            "functionDeclarations": [
                {
                    "name": "get_record",
                    "description": "Get a record.",
                    "parametersJsonSchema": TOOLS[0]["parameters"],
                }
            ]
        }
    ]
    assert body["generationConfig"] == {"temperature": 0.0, "responseMimeType": "application/json"}


def test_request_without_tools_or_json_mode():
    body = gemini_request(conversation()[:2], None, json_mode=False)
    assert "tools" not in body
    assert body["generationConfig"] == {"temperature": 0.0}


def test_a_model_turn_is_sent_back_exactly_as_it_came():
    # Thinking models sign their turns; the signature must come back unchanged.
    raw_turn = {
        "role": "model",
        "parts": [
            {"functionCall": {"id": "c1", "name": "get_record", "args": {"record_id": "RPT-0001"}},
             "thoughtSignature": "c2lnbmF0dXJl"},
        ],
    }  # fmt: skip
    messages = conversation()[:3]
    messages[2]["provider_state"] = {"content": raw_turn}
    body = gemini_request(messages, TOOLS, json_mode=False)
    assert body["contents"][1] == raw_turn


def test_calls_the_model_gave_no_id_are_answered_without_one():
    response = gemini_response(
        {"candidates": [{"content": {"role": "model", "parts": [
            {"functionCall": {"name": "get_record", "args": {"record_id": "RPT-0001"}}}]}}]},
        "gemini-flash",
    )  # fmt: skip
    call = response.tool_calls[0]
    messages = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": None, "tool_calls": [call.model_dump()],
         "provider_state": response.provider_state},
        {"role": "tool", "tool_call_id": call.id, "name": "get_record", "content": "{}"},
    ]  # fmt: skip
    part = gemini_request(messages, TOOLS, json_mode=False)["contents"][-1]["parts"][0]
    assert part == {"functionResponse": {"name": "get_record", "response": {}}}


def test_response_parsing():
    data = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {"text": "thinking...", "thought": True},
                        {"text": '{"answer": "x"}'},
                        {"functionCall": {"id": "f9", "name": "get_record", "args": {"record_id": "TBL-001"}}},
                    ],
                }
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 1200, "toolUsePromptTokenCount": 30,
            "candidatesTokenCount": 40, "thoughtsTokenCount": 60, "totalTokenCount": 1330,
        },
        "modelVersion": "gemini-flash-001",
    }  # fmt: skip
    response = gemini_response(data, "gemini-flash")
    assert response.content == '{"answer": "x"}'  # thoughts are not the answer
    assert response.tool_calls == [
        ToolCall(id="f9", name="get_record", arguments={"record_id": "TBL-001"})
    ]
    assert (response.input_tokens, response.output_tokens) == (1230, 100)
    assert response.raw_model == "gemini-flash-001"
    assert response.provider_state == {"content": data["candidates"][0]["content"]}


def test_a_blocked_answer_has_no_content():
    response = gemini_response({"candidates": [], "usageMetadata": {}}, "gemini-flash")
    assert (response.content, response.tool_calls) == (None, [])


def client(handler) -> GeminiClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return GeminiClient("gemini-flash", "secret-key-123", http=http)


def test_client_posts_with_the_key_in_a_header_not_the_url():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["key"] = str(request.url), request.headers.get("x-goog-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": "hi"}]}}]}
        )

    out = client(handler).chat(conversation()[:2], TOOLS)
    assert seen["url"].endswith("/v1beta/models/gemini-flash:generateContent")
    assert "secret-key-123" not in seen["url"]
    assert seen["key"] == "secret-key-123"
    assert seen["body"]["contents"][0]["parts"][0]["text"] == "What is RPT-0001?"
    assert out.content == "hi"


@pytest.mark.parametrize(
    ("headers", "body", "expected"),
    [
        ({"Retry-After": "7"}, {}, 7.0),
        ({}, {"error": {"code": 429, "details": [
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"}]}}, 37.0),
        ({}, {"error": {"code": 429, "message": "quota"}}, None),
    ],
)  # fmt: skip
def test_429_becomes_rate_limited_with_the_servers_hint(headers, body, expected):
    def handler(request):
        return httpx.Response(429, headers=headers, json=body)

    with pytest.raises(RateLimited) as error:
        client(handler).chat(conversation()[:2], None)
    assert error.value.retry_after == expected


def test_other_http_errors_never_show_the_key():
    def handler(request):
        return httpx.Response(400, json={"error": {"message": "bad request for secret-key-123"}})

    with pytest.raises(ProviderError) as error:
        client(handler).chat(conversation()[:2], None)
    assert "secret-key-123" not in str(error.value)
    assert "400" in str(error.value)


def test_make_llm_builds_the_configured_provider():
    settings = Settings(llm_provider="google", llm_model="gemini-flash", llm_api_key="k")
    assert isinstance(make_llm(settings), GeminiClient)
    with pytest.raises(ValueError, match="provider"):
        make_llm(Settings(llm_provider="other", llm_model="m", llm_api_key="k"))
    with pytest.raises(ValueError, match="LLM_"):
        make_llm(Settings())
