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

from metacompass.config import GEMINI_API_VERSION, Settings


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
    """The provider answered 429. `retry_after` is its own hint in seconds, if it gave one;
    `quota_id` and `quota_value` name the quota that ran out and its limit, if it said."""

    def __init__(
        self, retry_after: float | None, quota_id: str | None = None, quota_value: int | None = None
    ) -> None:
        super().__init__(f"rate limited ({quota_id or 'quota unknown'}, retry after {retry_after})")
        self.retry_after = retry_after
        self.quota_id = quota_id
        self.quota_value = quota_value


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


GEMINI_BASE = f"https://generativelanguage.googleapis.com/{GEMINI_API_VERSION}/models/{{model}}"
GEMINI_URL = GEMINI_BASE + ":generateContent"
# The role of the turn that carries functionResponse parts. The generateContent reference
# pages checked on 2026-09-19 did not say it; "user" is tried first and the first live call
# settles it (PROGRESS, Q-D25-3). The alternatives to try on a 400 are "function", "tool".
FUNCTION_RESPONSE_ROLE = "user"
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
    messages: list[dict],
    tools: list[dict] | None,
    json_mode: bool,
    temperature: float = 0.0,
    function_response_role: str = FUNCTION_RESPONSE_ROLE,
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
            _append(contents, function_response_role, {"functionResponse": response})
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
    """An LLMResponse from a generateContent answer.

    Anything but the expected shape is a ProviderError, never an empty answer: a blocked
    prompt, a candidate without content, missing usage counts or a malformed call would
    otherwise reach the loop as "no answer" and turn into an abstention nobody chose. The
    loop retries a ProviderError and then reports llm_error, which is not scored.
    """
    candidates = data.get("candidates") or []
    if not candidates:
        reason = (data.get("promptFeedback") or {}).get("blockReason", "no reason given")
        raise ProviderError(f"Gemini returned no candidate ({reason})")
    content = candidates[0].get("content") or {}
    parts = content.get("parts")
    if not parts:
        reason = candidates[0].get("finishReason", "no reason given")
        raise ProviderError(f"Gemini returned a candidate without content ({reason})")
    usage = data.get("usageMetadata")
    if not usage or "promptTokenCount" not in usage:
        raise ProviderError("Gemini returned no usage counts")
    try:
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
    except (KeyError, TypeError, AttributeError) as error:
        raise ProviderError(f"Gemini returned an unexpected part ({error!r})") from None
    return LLMResponse(
        content=text or None,
        tool_calls=calls,
        # Tokens the quota and the cost count: prompt plus tool-use prompt in, visible and
        # thinking output out.
        input_tokens=usage.get("promptTokenCount", 0) + usage.get("toolUsePromptTokenCount", 0),
        output_tokens=usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0),
        raw_model=data.get("modelVersion", model),
        provider_state={"content": content},
    )


def _rate_limited(response: httpx.Response) -> RateLimited:
    """A 429 as RateLimited: the wait hint (Retry-After header, else RetryInfo.retryDelay)
    and, if the body names it, the quota that ran out (QuotaFailure.violations)."""
    retry_after = quota_id = quota_value = None
    header = response.headers.get("retry-after")
    if header is not None and header.replace(".", "", 1).isdigit():
        retry_after = float(header)
    try:
        details = response.json().get("error", {}).get("details", [])
    except ValueError:
        details = []
    for detail in details:
        kind = detail.get("@type", "")
        if kind.endswith("RetryInfo") and retry_after is None:
            match = re.fullmatch(r"([0-9.]+)s", detail.get("retryDelay", ""))
            if match:
                retry_after = float(match.group(1))
        elif kind.endswith("QuotaFailure") and detail.get("violations"):
            violation = detail["violations"][0]
            quota_id = violation.get("quotaId")
            value = str(violation.get("quotaValue", ""))
            quota_value = int(value) if value.isdigit() else None
    return RateLimited(retry_after, quota_id, quota_value)


class GeminiClient:
    """The Gemini API's generateContent over HTTPS, temperature 0 (spec §8.1).

    Plain HTTP instead of the google-genai SDK (SPEC-DEVIATION, D25): the request is the
    documented REST shape, the 429 wait hints are readable, and no dependency is added.
    The key goes in the x-goog-api-key header, never in the URL, so it cannot end up in an
    error message or a log line.
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        *,
        http: httpx.Client | None = None,
        timeout: float = 120.0,
        function_response_role: str = FUNCTION_RESPONSE_ROLE,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._http = http or httpx.Client(timeout=timeout)
        self.function_response_role = function_response_role

    def _headers(self) -> dict:
        return {"x-goog-api-key": self._api_key}

    def check_model(self) -> None:
        """Fail before a run, not on its first question, if the model does not exist."""
        response = self._http.get(GEMINI_BASE.format(model=self.model), headers=self._headers())
        if response.status_code != 200:
            raise ProviderError(
                f"model {self.model!r} is not available (HTTP {response.status_code})"
            )

    def chat(
        self, messages: list[dict], tools: list[dict] | None, json_mode: bool = False
    ) -> LLMResponse:
        body = gemini_request(
            messages, tools, json_mode, function_response_role=self.function_response_role
        )
        response = self._http.post(
            GEMINI_URL.format(model=self.model), headers=self._headers(), json=body
        )
        if response.status_code == 429:
            raise _rate_limited(response)
        if response.status_code == 503:
            # "The model is overloaded": transient capacity, handled like a rate limit
            # (backoff, not counted, a clean stop if it lasts), never as a failed answer.
            refused = _rate_limited(response)
            raise RateLimited(refused.retry_after, quota_id="UNAVAILABLE")
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
