"""Free-tier quota guard for the LLM (D25): the eval spends no money, it spends quota.

The Gemini free tier limits requests per minute (RPM), input tokens per minute (TPM) and
requests per day (RPD, reset at midnight Pacific time). QuotaGuardedLLM wraps a provider
client and
  - waits before a call until the last 60 seconds leave room for one more request and its
    estimated input tokens,
  - stops with QuotaExhausted, before calling, once today's requests reach RPD,
  - on a 429 waits as long as the server says, or backs off 1, 2, 4, 8, 16 s with jitter,
    and after five refused retries stops with QuotaExhausted,
  - counts only answered requests, in a JSON log kept across runs (eval/results/quota_log.json).
A stop is clean: the runner writes nothing for the unanswered question and resumes later.
Wrap order: CachedLLM(QuotaGuardedLLM(provider)), so cached answers use no quota at all.
"""

import json
import random
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from metacompass.agent.llm import LLMClient, LLMResponse, QuotaExhausted, RateLimited

PACIFIC = ZoneInfo("America/Los_Angeles")  # where the daily quota resets
BACKOFF = (1, 2, 4, 8, 16)  # seconds before each retry after a 429 without a hint
WINDOW = 60.0
# The provider's minute is not aligned with ours; one extra second avoids a 429 at the edge.
MARGIN = 1.0
CHARS_PER_TOKEN = 4  # rough English average, used only to guess a request's size ahead


@dataclass(frozen=True)
class QuotaLimits:
    rpm: int | None = None
    rpd: int | None = None
    tpm: int | None = None


class QuotaLog:
    """Requests and tokens answered per Pacific-time day, persisted as JSON."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.clock = clock

    def today(self) -> str:
        return datetime.fromtimestamp(self.clock(), PACIFIC).date().isoformat()

    def _load(self) -> dict:
        if self.path.is_file():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {"limits": {}, "days": {}}

    def used_today(self) -> dict:
        return self._load()["days"].get(self.today(), {"requests": 0, "tokens": 0})

    def record(self, tokens: int, limits: QuotaLimits) -> None:
        data = self._load()
        day = data["days"].setdefault(self.today(), {"requests": 0, "tokens": 0})
        day["requests"] += 1
        day["tokens"] += tokens
        data["limits"] = asdict(limits)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def estimate_input_tokens(messages: list[dict], tools: list[dict] | None) -> int:
    text = json.dumps(messages, ensure_ascii=False) + json.dumps(tools or [], ensure_ascii=False)
    return len(text) // CHARS_PER_TOKEN + 1


class QuotaGuardedLLM:
    def __init__(
        self,
        inner: LLMClient,
        limits: QuotaLimits,
        log: QuotaLog,
        *,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.inner = inner
        self.model = inner.model
        self.limits = limits
        self.log = log
        self.clock = clock
        self.sleep = sleep
        self.rng = rng or random.Random()
        self._window: deque[tuple[float, int]] = deque()  # (time, input tokens) per call

    def _wait_for_room(self, expected_tokens: int) -> None:
        while True:
            now = self.clock()
            while self._window and self._window[0][0] <= now - WINDOW:
                self._window.popleft()
            rpm_ok = self.limits.rpm is None or len(self._window) < self.limits.rpm
            used = sum(tokens for _, tokens in self._window)
            # An empty window always lets a call through: waiting cannot make room for more.
            tpm_ok = (
                self.limits.tpm is None
                or not self._window
                or used + expected_tokens <= self.limits.tpm
            )
            if rpm_ok and tpm_ok:
                return
            self.sleep(self._window[0][0] + WINDOW + MARGIN - now)

    def chat(
        self, messages: list[dict], tools: list[dict] | None, json_mode: bool = False
    ) -> LLMResponse:
        if self.limits.rpd is not None and self.log.used_today()["requests"] >= self.limits.rpd:
            raise QuotaExhausted(f"daily request quota ({self.limits.rpd}) used up for today")
        self._wait_for_room(estimate_input_tokens(messages, tools))
        for attempt in range(len(BACKOFF) + 1):
            try:
                response = self.inner.chat(messages, tools, json_mode)
            except RateLimited as refused:
                if attempt == len(BACKOFF):
                    raise QuotaExhausted("still rate limited after 5 retries") from None
                delay = refused.retry_after
                if delay is None:
                    delay = BACKOFF[attempt] * self.rng.uniform(0.5, 1.5)
                self.sleep(delay)
                continue
            self._window.append((self.clock(), response.input_tokens))
            self.log.record(response.input_tokens + response.output_tokens, self.limits)
            return response
        raise AssertionError("unreachable")  # the loop either returns or raises
