"""The LLM behind the agent, behind one small interface (spec §8.1).

Messages are kept in a provider-neutral form and only a provider client converts them:
  {"role": "system" | "user", "content": str}
  {"role": "assistant", "content": str | None, "tool_calls": [{"id", "name", "arguments"}],
   "provider_state": dict | None}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str}
Tools are the dicts ToolRegistry.specs() returns. FakeLLM plays a script for the tests (no
network, no cost); CachedLLM stores every answer on disk so a repeated request is free and
gives the same answer. GeminiClient talks to the Gemini API's generateContent endpoint
over plain HTTPS (D25, H1: Google AI Studio free tier).
"""

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import BaseModel

from metacompass.config import Settings


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
    # What the provider needs back on the next turn, opaque to the loop (Gemini: the model
    # turn exactly as returned, because thinking models sign it).
    provider_state: dict | None = None


class RateLimited(Exception):
    """The provider answered 429. `retry_after` is its own hint in seconds, if it gave one."""

    def __init__(self, retry_after: float | None) -> None:
        super().__init__(f"rate limited (retry after {retry_after})")
        self.retry_after = retry_after


class QuotaExhausted(Exception):
    """The daily quota is used up, or rate limiting did not clear: the run stops cleanly."""


class ProviderError(Exception):
    """Any other failed call; the message never contains the API key."""


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
        path.write_text(response.model_dump_json(), encoding="utf-8", newline="\n")
        return response


# ---------------------------------------------------------------------- Gemini


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Tool calls the model sent without an ID get one of these, so the loop can pair results
# with calls; they are left out again when the result is sent back.
LOCAL_ID_PREFIX = "local-"


def _append(contents: list[dict], role: str, part: dict) -> None:
    """Add a part, merging it into the previous turn if that has the same role: tool results
    and the loop's next instruction travel together as one user turn."""
    if contents and contents[-1]["role"] == role:
        contents[-1]["parts"].append(part)
    else:
        contents.append({"role": role, "parts": [part]})


def gemini_request(
    messages: list[dict], tools: list[dict] | None, json_mode: bool, temperature: float = 0.0
) -> dict:
    """The generateContent request body for a provider-neutral conversation."""
    contents: list[dict] = []
    system = [m["content"] for m in messages if m["role"] == "system"]
    for message in messages:
        role = message["role"]
        if role == "user":
            _append(contents, "user", {"text": message["content"]})
        elif role == "tool":
            response = {"name": message["name"], "response": json.loads(message["content"])}
            if not message["tool_call_id"].startswith(LOCAL_ID_PREFIX):
                response = {"id": message["tool_call_id"], **response}
            _append(contents, "user", {"functionResponse": response})
        elif role == "assistant":
            state = message.get("provider_state") or {}
            if "content" in state:
                # Thinking models sign their turn; it must go back exactly as it came.
                contents.append(copy.deepcopy(state["content"]))
                continue
            parts = [{"text": message["content"]}] if message.get("content") else []
            for call in message.get("tool_calls", []):
                function_call = {"name": call["name"], "args": call["arguments"]}
                if not call["id"].startswith(LOCAL_ID_PREFIX):
                    function_call = {"id": call["id"], **function_call}
                parts.append({"functionCall": function_call})
            contents.append({"role": "model", "parts": parts})
    body: dict = {"contents": contents, "generationConfig": {"temperature": temperature}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
    if tools:
        declarations = [
            {
                "name": t["name"],
                "description": t["description"],
                "parametersJsonSchema": t["parameters"],
            }
            for t in tools
        ]
        body["tools"] = [{"functionDeclarations": declarations}]
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    return body


def gemini_response(data: dict, model: str) -> LLMResponse:
    """An LLMResponse from a generateContent answer. No candidate (a blocked prompt) means
    no content and no calls, which the loop treats as an unreadable answer."""
    candidates = data.get("candidates") or []
    content = candidates[0].get("content", {}) if candidates else {}
    parts = content.get("parts", [])
    text = "".join(p["text"] for p in parts if "text" in p and not p.get("thought"))
    calls = [
        ToolCall(
            id=part["functionCall"].get("id") or f"{LOCAL_ID_PREFIX}{i}",
            name=part["functionCall"]["name"],
            arguments=part["functionCall"].get("args", {}),
        )
        for i, part in enumerate(parts)
        if "functionCall" in part
    ]
    usage = data.get("usageMetadata", {})
    return LLMResponse(
        content=text or None,
        tool_calls=calls,
        # Tokens the quota and the cost count: prompt plus tool-use prompt in, visible and
        # thinking output out.
        input_tokens=usage.get("promptTokenCount", 0) + usage.get("toolUsePromptTokenCount", 0),
        output_tokens=usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0),
        raw_model=data.get("modelVersion", model),
        provider_state={"content": content} if content else None,
    )


def _retry_after(response: httpx.Response) -> float | None:
    """The server's wait hint on a 429: the Retry-After header, else RetryInfo.retryDelay."""
    header = response.headers.get("retry-after")
    if header is not None:
        try:
            return float(header)
        except ValueError:
            pass
    try:
        details = response.json().get("error", {}).get("details", [])
    except ValueError:
        return None
    for detail in details:
        if detail.get("@type", "").endswith("RetryInfo"):
            match = re.fullmatch(r"([0-9.]+)s", detail.get("retryDelay", ""))
            if match:
                return float(match.group(1))
    return None


class GeminiClient:
    """The Gemini API's generateContent over HTTPS, temperature 0 (spec §8.1).

    Plain HTTP instead of the google-genai SDK (SPEC-DEVIATION, D25): the request is the
    documented REST shape, the 429 wait hints are readable, and no dependency is added.
    The key goes in the x-goog-api-key header, never in the URL, so it cannot end up in an
    error message or a log line.
    """

    def __init__(
        self, model: str, api_key: str, *, http: httpx.Client | None = None, timeout: float = 120.0
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._http = http or httpx.Client(timeout=timeout)

    def chat(
        self, messages: list[dict], tools: list[dict] | None, json_mode: bool = False
    ) -> LLMResponse:
        response = self._http.post(
            GEMINI_URL.format(model=self.model),
            headers={"x-goog-api-key": self._api_key},
            json=gemini_request(messages, tools, json_mode),
        )
        if response.status_code == 429:
            raise RateLimited(_retry_after(response))
        if response.status_code >= 400:
            try:
                reason = response.json().get("error", {}).get("status", "")
            except ValueError:
                reason = ""
            raise ProviderError(f"Gemini API error: HTTP {response.status_code} {reason}".strip())
        return gemini_response(response.json(), self.model)


def make_llm(settings: Settings) -> LLMClient:
    """The provider client the settings name (H1)."""
    if not settings.has_llm:
        raise ValueError("set LLM_PROVIDER, LLM_MODEL and LLM_API_KEY in .env")
    if settings.llm_provider.lower() in ("google", "gemini"):
        return GeminiClient(settings.llm_model, settings.llm_api_key.get_secret_value())
    raise ValueError(f"unsupported LLM provider {settings.llm_provider!r}; use 'google'")
