"""LLM client layer (spec §8.1): the scripted FakeLLM, the response cache and the cost rule."""

import json

import pytest

from metacompass.agent.llm import CachedLLM, FakeLLM, LLMResponse, ToolCall, cost_usd


def text(content: str, tokens: tuple[int, int] = (10, 5)) -> LLMResponse:
    return LLMResponse(
        content=content, tool_calls=[], input_tokens=tokens[0], output_tokens=tokens[1],
        raw_model="fake",
    )  # fmt: skip


def call(name: str, **arguments) -> LLMResponse:
    return LLMResponse(
        content=None, tool_calls=[ToolCall(id="c1", name=name, arguments=arguments)],
        input_tokens=10, output_tokens=5, raw_model="fake",
    )  # fmt: skip


MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]


def test_fake_llm_plays_its_script_and_records_every_request():
    llm = FakeLLM([call("get_record", record_id="RPT-0001"), text("done")])
    first = llm.chat(MESSAGES, tools=[{"name": "get_record"}])
    later_messages = [*MESSAGES, {"role": "assistant", "content": None}]
    second = llm.chat(later_messages, tools=None, json_mode=True)
    assert first.tool_calls[0].arguments == {"record_id": "RPT-0001"}
    assert second.content == "done"
    assert [r["json_mode"] for r in llm.requests] == [False, True]
    assert llm.requests[0]["tools"] == [{"name": "get_record"}]
    assert llm.requests[1]["messages"] == later_messages


def test_fake_llm_keeps_a_copy_of_the_messages():
    llm = FakeLLM([text("a")])
    messages = [dict(m) for m in MESSAGES]
    llm.chat(messages, tools=None)
    messages.append({"role": "user", "content": "later"})
    assert len(llm.requests[0]["messages"]) == 2  # what was sent, not what came later


def test_fake_llm_raises_scripted_exceptions_and_stops_at_the_end():
    llm = FakeLLM([RuntimeError("provider down")])
    with pytest.raises(RuntimeError, match="provider down"):
        llm.chat(MESSAGES, tools=None)
    with pytest.raises(AssertionError, match="script"):
        llm.chat(MESSAGES, tools=None)


def test_fake_llm_can_repeat_a_response_forever():
    llm = FakeLLM([], then=call("search_assets", query="x"))
    for _ in range(20):
        assert llm.chat(MESSAGES, tools=None).tool_calls[0].name == "search_assets"


def test_cached_llm_answers_a_repeated_request_from_disk(tmp_path):
    inner = FakeLLM([text("from the model")])  # a second real call would fail the script
    cached = CachedLLM(inner, tmp_path, cache_salt="dev")
    first = cached.chat(MESSAGES, tools=None)
    again = cached.chat(MESSAGES, tools=None)
    assert first == again == text("from the model")
    assert len(inner.requests) == 1
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["content"] == "from the model"


def test_cache_key_covers_messages_tools_json_mode_salt_and_model(tmp_path):
    variants = [
        (MESSAGES, None, False, "dev", "fake"),
        ([*MESSAGES, {"role": "user", "content": "more"}], None, False, "dev", "fake"),
        (MESSAGES, [{"name": "get_record"}], False, "dev", "fake"),
        (MESSAGES, None, True, "dev", "fake"),
        (MESSAGES, None, False, "repeat-1", "fake"),
        (MESSAGES, None, False, "dev", "other-model"),
    ]
    keys = {CachedLLM.key(m, t, j, salt, model) for m, t, j, salt, model in variants}
    assert len(keys) == len(variants)


def test_cached_llm_does_not_cache_failures(tmp_path):
    inner = FakeLLM([RuntimeError("timeout"), text("ok")])
    cached = CachedLLM(inner, tmp_path, cache_salt="dev")
    with pytest.raises(RuntimeError):
        cached.chat(MESSAGES, tools=None)
    assert cached.chat(MESSAGES, tools=None).content == "ok"


def test_cost_is_tokens_times_price_per_million():
    # 12,000 input tokens at $0.40/M and 3,000 output tokens at $1.60/M.
    assert cost_usd(12_000, 3_000, 0.40, 1.60) == pytest.approx(0.0048 + 0.0048)
    assert cost_usd(0, 0, 0.40, 1.60) == 0.0
