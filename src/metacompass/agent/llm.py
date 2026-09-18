"""The LLM behind the agent, behind one small interface (spec §8.1).

Messages are kept in a provider-neutral form and only a provider client converts them:
  {"role": "system" | "user", "content": str}
  {"role": "assistant", "content": str | None, "tool_calls": [{"id", "name", "arguments"}]}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str}
Tools are the dicts ToolRegistry.specs() returns. FakeLLM plays a script for the tests (no
network, no cost); CachedLLM stores every answer on disk so a repeated request is free and
gives the same answer. The provider client arrives once the provider is chosen (H1).
"""

import copy
import hashlib
import json
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict


class LLMResponse(BaseModel):
    content: str | None
    tool_calls: list[ToolCall]
    input_tokens: int
    output_tokens: int
    raw_model: str


class LLMClient(Protocol):
    model: str

    def chat(
        self, messages: list[dict], tools: list[dict] | None, json_mode: bool = False
    ) -> LLMResponse: ...


def cost_usd(input_tokens: int, output_tokens: int, price_in: float, price_out: float) -> float:
    """Dollar cost of one call; prices are per million tokens (H3, from .env)."""
    return input_tokens * price_in / 1e6 + output_tokens * price_out / 1e6


class FakeLLM:
    """Returns scripted responses in order and records every request it gets.

    A script item that is an exception is raised instead of returned. After the script,
    `then` is returned forever if given; otherwise the test asked for more turns than it
    planned, which is a failure.
    """

    model = "fake"

    def __init__(
        self, script: list[LLMResponse | Exception], then: LLMResponse | None = None
    ) -> None:
        self.script = list(script)
        self.then = then
        self.requests: list[dict] = []

    def chat(
        self, messages: list[dict], tools: list[dict] | None, json_mode: bool = False
    ) -> LLMResponse:
        # Deep copies: the loop keeps appending to its list, and a test must see what was
        # actually sent at this turn.
        self.requests.append(
            {
                "messages": copy.deepcopy(messages),
                "tools": copy.deepcopy(tools),
                "json_mode": json_mode,
            }
        )
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        if self.then is not None:
            return self.then
        raise AssertionError(f"FakeLLM script ran out after {len(self.requests) - 1} responses")


class CachedLLM:
    """Wraps a client; answers seen before come from `cache_dir` as JSON files.

    The key covers everything that can change an answer. `cache_salt` separates runs that
    must not share answers: fixed during dev iterations, the repeat index in eval repeats.
    Failures are not cached, so a retry after an outage reaches the model again.
    """

    def __init__(self, inner: LLMClient, cache_dir: Path, cache_salt: str = "") -> None:
        self.inner = inner
        self.model = inner.model
        self.cache_dir = Path(cache_dir)
        self.cache_salt = cache_salt

    @staticmethod
    def key(
        messages: list[dict], tools: list[dict] | None, json_mode: bool, salt: str, model: str
    ) -> str:
        blob = json.dumps(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "json_mode": json_mode,
                "salt": salt,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def chat(
        self, messages: list[dict], tools: list[dict] | None, json_mode: bool = False
    ) -> LLMResponse:
        name = self.key(messages, tools, json_mode, self.cache_salt, self.model)
        path = self.cache_dir / f"{name}.json"
        if path.is_file():
            return LLMResponse.model_validate_json(path.read_text(encoding="utf-8"))
        response = self.inner.chat(messages, tools, json_mode)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(response.model_dump_json(), encoding="utf-8")
        return response
