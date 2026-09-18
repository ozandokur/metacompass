"""The agent: a plain, bounded tool-calling loop (spec §8.2, decision D18).

One question in, one AgentResult out. The model sees the system prompt and the question
and may call tools; every tool result goes back to it as the exact JSON the output cap was
measured on (registry.payload_json). The loop always ends with an answer: when the tool
budget or the turn limit runs out it asks once more for a final answer without tools, a
broken answer gets one repair turn, and a failing LLM is retried twice before the agent
gives a plain abstention. The grounding check runs last, in every configuration (D12).
"""

import logging
import time
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel

from metacompass.agent.answer import FinalAnswer, abstained_answer, enforce_grounding, parse_final
from metacompass.agent.llm import LLMClient, LLMResponse, ToolCall, cost_usd
from metacompass.agent.prompts import (
    FORCE_FINAL_INSTRUCTION,
    REPAIR_INSTRUCTION,
    build_system_prompt,
)
from metacompass.tools.registry import ToolRegistry, payload_json

logger = logging.getLogger(__name__)

BUDGET_ERROR = {
    "error": {"code": "BUDGET", "message": "Tool budget exhausted. Answer now or abstain."}
}
# Messages the user sees when the loop cannot get an answer; no technical details.
LLM_ERROR_MESSAGE = "Sorry, the language model is not reachable right now. Please try again later."
PARSE_FAILURE_MESSAGE = "Sorry, I could not put together a well-formed answer to this question."
NO_FINAL_MESSAGE = "I could not finish answering within the allowed number of steps."
RETRY_DELAYS = (1.0, 2.0)  # seconds before the 2nd and 3rd attempt: exponential backoff
SUMMARY_CHARS = 300

StopReason = Literal["final", "tool_budget", "turn_limit", "parse_failure", "llm_error"]


class Step(BaseModel):
    """One LLM turn or one tool call, for the trace."""

    kind: Literal["llm", "tool"]
    name: str | None = None  # tool name
    arguments: dict | None = None
    summary: str  # tool: start of the result JSON; llm: what the model did
    duration_ms: int
    input_tokens: int = 0
    output_tokens: int = 0


class AgentResult(BaseModel):
    question: str
    config_name: str
    answer: FinalAnswer
    steps: list[Step]
    stopped_reason: StopReason
    stripped_ids: list[str]  # IDs removed by the grounding check
    tool_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int


class LLMUnavailable(Exception):
    """The LLM failed on every attempt."""


def _ms(since: float) -> int:
    return round((time.perf_counter() - since) * 1000)


class _Run:
    """What one question's run accumulates."""

    def __init__(self) -> None:
        self.steps: list[Step] = []
        self.seen_ids: set[str] = set()
        self.tool_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0


class Agent:
    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        *,
        prices: tuple[float, float] = (0.0, 0.0),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.config = registry.config  # one source for the prompt, the tools and the limits
        self.prices = prices  # USD per million input / output tokens
        self.sleep = sleep

    def run(self, question: str) -> AgentResult:
        started = time.perf_counter()
        run = _Run()
        messages = [
            {"role": "system", "content": build_system_prompt(self.config)},
            {"role": "user", "content": question},
        ]
        try:
            answer, reason = self._converse(messages, run)
        except LLMUnavailable:
            answer, reason = abstained_answer(LLM_ERROR_MESSAGE), "llm_error"
        answer, stripped = enforce_grounding(answer, run.seen_ids)
        return AgentResult(
            question=question,
            config_name=self.config.name,
            answer=answer,
            steps=run.steps,
            stopped_reason=reason,
            stripped_ids=stripped,
            tool_calls=run.tool_calls,
            input_tokens=run.input_tokens,
            output_tokens=run.output_tokens,
            cost_usd=cost_usd(run.input_tokens, run.output_tokens, *self.prices),
            latency_ms=_ms(started),
        )

    def _converse(self, messages: list[dict], run: _Run) -> tuple[FinalAnswer, StopReason]:
        specs = self.registry.specs()
        llm_turns = 0
        while True:
            if llm_turns == self.config.max_llm_turns:
                return self._force_final(messages, run), "turn_limit"
            response = self._chat(messages, specs, run)
            llm_turns += 1
            if response.tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content,
                        "tool_calls": [c.model_dump() for c in response.tool_calls],
                    }
                )
                over_budget = False
                for call in response.tool_calls:
                    if run.tool_calls == self.config.max_tool_calls:
                        # Every call still gets a result, so the conversation stays valid.
                        payload, over_budget = BUDGET_ERROR, True
                        run.steps.append(
                            Step(kind="tool", name=call.name, arguments=call.arguments,
                                 summary="error: BUDGET", duration_ms=0)
                        )  # fmt: skip
                    else:
                        payload = self._call_tool(call, run)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": call.name,
                            "content": payload_json(payload),
                        }
                    )
                if over_budget:
                    return self._force_final(messages, run), "tool_budget"
                continue

            answer = parse_final(response.content)
            if answer is None:
                answer = self._repair(messages, response, run)
                if answer is None:
                    return abstained_answer(PARSE_FAILURE_MESSAGE), "parse_failure"
            return answer, "final"

    def _call_tool(self, call: ToolCall, run: _Run) -> dict:
        started = time.perf_counter()
        payload, ids = self.registry.call(call.name, call.arguments)
        run.tool_calls += 1
        run.seen_ids.update(ids)
        summary = (
            f"error: {payload['error']['code']}"
            if "error" in payload
            else payload_json(payload)[:SUMMARY_CHARS]
        )
        run.steps.append(
            Step(kind="tool", name=call.name, arguments=call.arguments, summary=summary,
                 duration_ms=_ms(started))
        )  # fmt: skip
        return payload

    def _repair(self, messages: list[dict], broken: LLMResponse, run: _Run) -> FinalAnswer | None:
        """One more turn, without tools and in JSON mode, to fix an unreadable answer."""
        messages.append({"role": "assistant", "content": broken.content})
        messages.append({"role": "user", "content": REPAIR_INSTRUCTION})
        return parse_final(self._chat(messages, None, run, json_mode=True).content)

    def _force_final(self, messages: list[dict], run: _Run) -> FinalAnswer:
        """The budget or the turn limit is used up: ask once for an answer without tools."""
        messages.append({"role": "user", "content": FORCE_FINAL_INSTRUCTION})
        answer = parse_final(self._chat(messages, None, run, json_mode=True).content)
        return answer if answer is not None else abstained_answer(NO_FINAL_MESSAGE)

    def _chat(
        self, messages: list[dict], tools: list[dict] | None, run: _Run, json_mode: bool = False
    ) -> LLMResponse:
        """One LLM turn, retried with backoff; raises LLMUnavailable after the last try."""
        for attempt in range(len(RETRY_DELAYS) + 1):
            started = time.perf_counter()
            try:
                response = self.llm.chat(messages, tools, json_mode)
            except Exception as exc:
                # Only the exception type goes into the trace; the message may hold
                # provider details that do not belong in results or in front of a user.
                logger.warning("LLM call failed (attempt %d): %r", attempt + 1, exc)
                run.steps.append(
                    Step(
                        kind="llm", summary=f"error: {type(exc).__name__}", duration_ms=_ms(started)
                    )
                )
                if attempt == len(RETRY_DELAYS):
                    raise LLMUnavailable from None
                self.sleep(RETRY_DELAYS[attempt])
                continue
            run.input_tokens += response.input_tokens
            run.output_tokens += response.output_tokens
            did = [c.name for c in response.tool_calls]
            run.steps.append(
                Step(kind="llm", summary=f"tool calls: {', '.join(did)}" if did else "answer",
                     duration_ms=_ms(started), input_tokens=response.input_tokens,
                     output_tokens=response.output_tokens)
            )  # fmt: skip
            return response
        raise AssertionError("unreachable")  # the loop either returns or raises
