"""The agent loop (spec §8.2, §8.6): the twelve scenarios, all with FakeLLM and no network."""

import json

import pytest

from metacompass.agent.llm import FakeLLM, LLMResponse, QuotaExhausted, RateLimited, ToolCall
from metacompass.agent.loop import BUDGET_ERROR, Agent
from metacompass.agent.prompts import FORCE_FINAL_INSTRUCTION, REPAIR_INSTRUCTION
from metacompass.config import ALL_SIX_TOOLS, AgentConfig
from metacompass.tools.registry import build_registry, payload_json


def tool(name: str, call_id: str = "c1", tokens=(100, 20), **arguments) -> LLMResponse:
    return LLMResponse(
        content=None, tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
        input_tokens=tokens[0], output_tokens=tokens[1], raw_model="fake",
    )  # fmt: skip


def text(content: str, tokens=(100, 20)) -> LLMResponse:
    return LLMResponse(
        content=content, tool_calls=[], input_tokens=tokens[0], output_tokens=tokens[1],
        raw_model="fake",
    )  # fmt: skip


def final(answer_ids, evidence_ids=(), abstained=False, answer="Here is the answer.", **kw):
    body = {
        "answer": answer, "answer_ids": list(answer_ids), "evidence_ids": list(evidence_ids),
        "abstained": abstained,
    }  # fmt: skip
    return text(json.dumps(body), **kw)


def make(mini_ctx, script, then=None, prices=(0.0, 0.0), **config):
    registry = build_registry(
        mini_ctx.store, mini_ctx.retrievers, mini_ctx.graph, AgentConfig(**config)
    )
    llm = FakeLLM(script, then)
    delays: list[float] = []
    return Agent(llm, registry, prices=prices, sleep=delays.append), llm, delays


QUESTION = "Who should I ask about Weekly Sales Summary (RPT-0002)?"


# 1
def test_one_tool_call_then_a_valid_final_answer(mini_ctx):
    agent, llm, _ = make(
        mini_ctx, [tool("resolve_owner", asset_id="RPT-0002"), final(["EMP-004"], ["RPT-0002"])]
    )
    result = agent.run(QUESTION)
    assert result.stopped_reason == "final"
    assert (result.answer.answer_ids, result.answer.abstained) == (["EMP-004"], False)
    assert result.tool_calls == 1
    system, user, assistant, tool_message = llm.requests[1]["messages"]
    assert (system["role"], user) == ("system", {"role": "user", "content": QUESTION})
    assert assistant["tool_calls"] == [
        {"id": "c1", "name": "resolve_owner", "arguments": {"asset_id": "RPT-0002"}}
    ]
    expected, _ = agent.registry.call("resolve_owner", {"asset_id": "RPT-0002"})
    assert tool_message == {
        "role": "tool",
        "tool_call_id": "c1",
        "name": "resolve_owner",
        "content": payload_json(expected),
    }
    assert [s.kind for s in result.steps] == ["llm", "tool", "llm"]


# 2
def test_the_ninth_tool_call_gets_a_budget_error_and_the_model_must_answer(mini_ctx):
    calls = [tool("get_record", call_id=f"c{i}", record_id="RPT-0001") for i in range(1, 10)]
    agent, llm, _ = make(mini_ctx, [*calls, final(["RPT-0001"])])
    result = agent.run("Tell me about RPT-0001.")
    assert result.stopped_reason == "tool_budget"
    assert result.tool_calls == 8
    last = llm.requests[-1]
    assert json.loads(last["messages"][-2]["content"]) == BUDGET_ERROR
    assert last["messages"][-1] == {"role": "user", "content": FORCE_FINAL_INSTRUCTION}
    assert (last["tools"], last["json_mode"]) == (None, True)
    assert result.answer.answer_ids == ["RPT-0001"]  # forced, but still an answer


# 3
def test_a_model_that_never_stops_calling_tools_hits_the_turn_limit(mini_ctx):
    endless = tool("search_assets", query="dealer sales")
    agent, llm, _ = make(mini_ctx, [], then=endless, max_tool_calls=50)
    result = agent.run("Find dealer sales reports.")
    assert result.stopped_reason == "turn_limit"
    assert result.answer.abstained is True
    assert len(llm.requests) == 10 + 1  # ten turns, then the forced final turn
    assert llm.requests[-1]["tools"] is None


# 4
def test_a_broken_final_answer_is_repaired_once(mini_ctx):
    agent, llm, _ = make(mini_ctx, [text("EMP-004, I think"), final([], abstained=True)])
    result = agent.run(QUESTION)
    assert result.stopped_reason == "final"
    assert result.answer.abstained is True
    repair = llm.requests[-1]
    assert repair["messages"][-1] == {"role": "user", "content": REPAIR_INSTRUCTION}
    assert (repair["tools"], repair["json_mode"]) == (None, True)


# 5
def test_a_broken_answer_that_stays_broken_ends_as_a_parse_failure(mini_ctx):
    agent, _, _ = make(mini_ctx, [text("not json"), text("{still not json")])
    result = agent.run(QUESTION)
    assert result.stopped_reason == "parse_failure"
    assert (result.answer.abstained, result.answer.answer_ids) == (True, [])


# 6
def test_a_tool_error_goes_back_to_the_model_and_the_loop_goes_on(mini_ctx):
    agent, llm, _ = make(
        mini_ctx, [tool("get_record", record_id="RPT-0999"), final([], abstained=True)]
    )
    result = agent.run("What is RPT-0999?")
    tool_message = llm.requests[1]["messages"][-1]
    assert json.loads(tool_message["content"])["error"]["code"] == "NOT_FOUND"
    assert result.stopped_reason == "final"
    assert "RPT-0999" in result.answer.answer or result.answer.abstained


# 7
def test_an_llm_that_keeps_failing_ends_with_a_plain_message(mini_ctx):
    boom = [RuntimeError("Traceback: secret provider detail")] * 3
    agent, llm, delays = make(mini_ctx, boom)
    result = agent.run(QUESTION)
    assert result.stopped_reason == "llm_error"
    assert result.answer.abstained is True
    assert "secret" not in result.answer.answer and "Traceback" not in result.answer.answer
    assert len(llm.requests) == 3  # the first try and two retries
    assert delays == [1.0, 2.0]  # exponential backoff


def test_an_llm_failure_that_recovers_is_retried(mini_ctx):
    agent, _, delays = make(mini_ctx, [RuntimeError("blip"), final([], abstained=True)])
    result = agent.run(QUESTION)
    assert result.stopped_reason == "final"
    assert delays == [1.0]


# 8
def test_an_id_no_tool_returned_is_stripped(mini_ctx):
    agent, _, _ = make(
        mini_ctx,
        [tool("resolve_owner", asset_id="RPT-0002"), final(["EMP-004", "EMP-099"], ["RPT-0002"])],
    )
    result = agent.run(QUESTION)
    assert result.stripped_ids == ["EMP-099"]
    assert (result.answer.answer_ids, result.answer.abstained) == (["EMP-004"], False)


def test_an_answer_made_only_of_unseen_ids_becomes_an_abstention(mini_ctx):
    # No tool was called, so even an ID from the question counts as unseen.
    agent, _, _ = make(mini_ctx, [final(["EMP-004"], ["RPT-0002"], answer="EMP-004 owns it.")])
    result = agent.run(QUESTION)
    assert result.stripped_ids == ["EMP-004", "RPT-0002"]
    assert (result.answer.answer_ids, result.answer.abstained) == ([], True)


# 9
def test_a3_hides_resolve_owner_and_refuses_calls_to_it(mini_ctx):
    a3 = [t for t in ALL_SIX_TOOLS if t != "resolve_owner"]
    agent, llm, _ = make(
        mini_ctx,
        [tool("resolve_owner", asset_id="RPT-0002"), final([], abstained=True)],
        tools_enabled=a3,
    )
    agent.run(QUESTION)
    assert "resolve_owner" not in [spec["name"] for spec in llm.requests[0]["tools"]]
    error = json.loads(llm.requests[1]["messages"][-1]["content"])["error"]
    assert error["code"] == "INVALID_ARGUMENT"


# 10
def test_without_abstain_instructions_the_prompt_has_no_abstain_section(mini_ctx):
    agent, llm, _ = make(mini_ctx, [final([], abstained=True)], abstain_instructions=False)
    agent.run(QUESTION)
    system = llm.requests[0]["messages"][0]["content"]
    assert "\nABSTAIN\n" not in system


# 11
def test_without_match_quality_the_search_output_has_no_signal(mini_ctx):
    agent, llm, _ = make(
        mini_ctx,
        [tool("search_assets", query="parts returns"), final([], abstained=True)],
        show_match_quality=False,
    )
    agent.run("Is there a parts returns report?")
    assert "signal" not in json.loads(llm.requests[1]["messages"][-1]["content"])


# 12
def test_cost_and_tokens_add_up_over_all_turns(mini_ctx):
    agent, _, _ = make(
        mini_ctx,
        [
            tool("resolve_owner", asset_id="RPT-0002", tokens=(1000, 200)),
            final(["EMP-004"], ["RPT-0002"], tokens=(1500, 300)),
        ],
        prices=(0.40, 1.60),
    )
    result = agent.run(QUESTION)
    assert (result.input_tokens, result.output_tokens) == (2500, 500)
    assert result.cost_usd == pytest.approx(2500 * 0.40 / 1e6 + 500 * 1.60 / 1e6)
    assert result.latency_ms >= 0
    assert result.config_name == "full"


# ---------------------------------------------------------------------- free-tier quota (D25)


def test_an_exhausted_quota_stops_the_run_instead_of_abstaining(mini_ctx):
    agent, llm, delays = make(mini_ctx, [QuotaExhausted("daily requests used up")])
    with pytest.raises(QuotaExhausted):
        agent.run(QUESTION)
    assert (len(llm.requests), delays) == (1, [])  # no retries, no llm_error answer


def test_a_rate_limit_reaching_the_loop_is_not_an_llm_error(mini_ctx):
    agent, llm, delays = make(mini_ctx, [RateLimited(3.0)])
    with pytest.raises(RateLimited):
        agent.run(QUESTION)
    assert (len(llm.requests), delays) == (1, [])


def test_provider_state_travels_with_the_assistant_turn(mini_ctx):
    signed = tool("resolve_owner", asset_id="RPT-0002").model_copy(
        update={"provider_state": {"content": {"role": "model", "parts": ["signed"]}}}
    )
    agent, llm, _ = make(mini_ctx, [signed, final(["EMP-004"], ["RPT-0002"])])
    agent.run(QUESTION)
    assistant = llm.requests[1]["messages"][2]
    assert assistant["provider_state"] == {"content": {"role": "model", "parts": ["signed"]}}


def test_each_llm_step_records_what_its_input_is_made_of(mini_ctx):
    agent, llm, _ = make(
        mini_ctx, [tool("resolve_owner", asset_id="RPT-0002"), final(["EMP-004"], ["RPT-0002"])]
    )
    result = agent.run(QUESTION)
    first, second = [s for s in result.steps if s.kind == "llm"]
    system = llm.requests[0]["messages"][0]["content"]
    tools = json.dumps(llm.requests[0]["tools"], ensure_ascii=False, separators=(",", ":"))
    expected, _ = agent.registry.call("resolve_owner", {"asset_id": "RPT-0002"})
    assert first.input_chars == {
        "system": len(system), "tools": len(tools), "tool_results": 0, "other": len(QUESTION),
    }  # fmt: skip
    assert second.input_chars["tool_results"] == len(payload_json(expected))
    assert second.input_chars["other"] > len(QUESTION)  # the question plus the model's call
