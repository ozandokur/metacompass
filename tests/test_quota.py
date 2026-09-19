"""Free-tier quota guard (D25): throttling to RPM and TPM, the daily request cap in Pacific
time, and 429 handling. A fake clock stands in for time; nothing sleeps for real."""

import json
import random
from datetime import UTC, datetime

import pytest

from metacompass.agent.llm import FakeLLM, LLMResponse, QuotaExhausted, RateLimited
from metacompass.agent.quota import BACKOFF, QuotaGuardedLLM, QuotaLimits, QuotaLog

NOON_UTC = datetime(2026, 9, 19, 12, 0, tzinfo=UTC).timestamp()
MESSAGES = [{"role": "user", "content": "hi"}]


class Clock:
    def __init__(self, now: float = NOON_UTC) -> None:
        self.now, self.slept = now, []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def ok(input_tokens: int = 10, output_tokens: int = 5) -> LLMResponse:
    return LLMResponse(
        content="ok", tool_calls=[], input_tokens=input_tokens, output_tokens=output_tokens,
        raw_model="fake",
    )  # fmt: skip


def guarded(tmp_path, script, clock, *, rpm=None, rpd=None, tpm=None, then=None):
    log = QuotaLog(tmp_path / "quota_log.json", clock=clock.time)
    inner = FakeLLM(script, then=then)
    llm = QuotaGuardedLLM(
        inner, QuotaLimits(rpm=rpm, rpd=rpd, tpm=tpm), log,
        clock=clock.time, sleep=clock.sleep, rng=random.Random(0),
    )  # fmt: skip
    return llm, inner, log


def test_requests_per_minute_are_throttled(tmp_path):
    clock = Clock()
    llm, _, _ = guarded(tmp_path, [], clock, rpm=2, then=ok())
    for _ in range(3):
        llm.chat(MESSAGES, None)
    # The third call waits until the first leaves the 60-second window (plus a margin).
    assert clock.slept == [pytest.approx(61.0)]


def test_tokens_per_minute_are_throttled(tmp_path):
    clock = Clock()
    llm, _, _ = guarded(tmp_path, [], clock, tpm=1000, then=ok(input_tokens=600))
    llm.chat(MESSAGES, None)
    llm.chat(MESSAGES, None)  # 600 + a small estimate still fits
    assert clock.slept == []
    llm.chat(MESSAGES, None)  # 1,200 used in this minute: wait for the window to clear
    assert clock.slept == [pytest.approx(61.0)]


def test_the_daily_cap_stops_before_calling_the_model(tmp_path):
    clock = Clock()
    llm, inner, log = guarded(tmp_path, [ok(), ok()], clock, rpd=2)
    llm.chat(MESSAGES, None)
    llm.chat(MESSAGES, None)
    with pytest.raises(QuotaExhausted, match="daily"):
        llm.chat(MESSAGES, None)
    assert len(inner.requests) == 2
    assert log.used_today() == {"requests": 2, "tokens": 30}


def test_the_day_turns_over_at_midnight_pacific(tmp_path):
    clock = Clock(datetime(2026, 9, 19, 6, 59, tzinfo=UTC).timestamp())  # 23:59 PDT, Sep 18
    log = QuotaLog(tmp_path / "quota_log.json", clock=clock.time)
    assert log.today() == "2026-09-18"
    clock.now += 120
    assert log.today() == "2026-09-19"


def test_a_429_waits_as_long_as_the_server_says(tmp_path):
    clock = Clock()
    llm, _, log = guarded(tmp_path, [RateLimited(7.0), ok()], clock)
    assert llm.chat(MESSAGES, None).content == "ok"
    assert clock.slept == [7.0]
    assert log.used_today()["requests"] == 1  # the refused attempt is not counted


def test_a_429_without_a_hint_backs_off_with_jitter_then_stops_cleanly(tmp_path):
    clock = Clock()
    llm, inner, log = guarded(tmp_path, [RateLimited(None)] * 6, clock)
    with pytest.raises(QuotaExhausted, match="rate limited"):
        llm.chat(MESSAGES, None)
    assert BACKOFF == (1, 2, 4, 8, 16)
    assert len(clock.slept) == 5 and len(inner.requests) == 6
    for waited, base in zip(clock.slept, BACKOFF, strict=True):
        assert 0.5 * base <= waited <= 1.5 * base
    assert log.used_today() == {"requests": 0, "tokens": 0}


def test_the_log_survives_between_runs_and_records_the_limits(tmp_path):
    clock = Clock()
    llm, _, _ = guarded(tmp_path, [ok(100, 20)], clock, rpm=10, rpd=250, tpm=250_000)
    llm.chat(MESSAGES, None)
    again = QuotaLog(tmp_path / "quota_log.json", clock=clock.time)
    assert again.used_today() == {"requests": 1, "tokens": 120}
    saved = json.loads((tmp_path / "quota_log.json").read_text(encoding="utf-8"))
    assert saved["limits"] == {"rpm": 10, "rpd": 250, "tpm": 250_000}
    assert saved["days"] == {"2026-09-19": {"requests": 1, "tokens": 120}}
