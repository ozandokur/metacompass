"""Deterministic scoring (spec §9.6): one table of cases per scoring rule."""

import pytest

from scoring import score


def item(rule: str, answer_ids, forbidden_ids=(), should_abstain=False) -> dict:
    return {
        "scoring": rule,
        "gold": {
            "answer_ids": list(answer_ids),
            "forbidden_ids": list(forbidden_ids),
            "should_abstain": should_abstain,
        },
    }


def ans(ids=(), abstained=False) -> dict:
    return {"answer": "...", "answer_ids": list(ids), "evidence_ids": [], "abstained": abstained}


@pytest.mark.parametrize(
    ("given", "correct"),
    [
        (ans(["EMP-081"]), True),
        (ans(["EMP-081", "RPT-0142"]), True),  # extra IDs are fine
        (ans([]), False),  # empty answer
        (ans(["EMP-081", "EMP-044"]), False),  # a forbidden ID (the owner who left)
        (ans(["EMP-081"], abstained=True), False),  # abstaining is never right here
    ],
)
def test_contains_all(given, correct):
    assert score(item("contains_all", ["EMP-081"], ["EMP-044"]), given)["correct"] is correct


@pytest.mark.parametrize(
    ("given", "correct", "hits"),
    [
        (ans(["REQ-0003"]), True, 1),
        (ans(["REQ-0003", "REQ-0009", "REQ-0100"]), True, 2),
        (ans(["REQ-0100"]), False, 0),
        (ans([]), False, 0),
        (ans(["REQ-0003"], abstained=True), False, 1),
    ],
)
def test_contains_any(given, correct, hits):
    result = score(item("contains_any", ["REQ-0003", "REQ-0009"]), given)
    assert (result["correct"], result["hits"]) == (correct, hits)


GOLD5 = ["EMP-001", "EMP-002", "EMP-003", "EMP-004", "EMP-005"]


@pytest.mark.parametrize(
    ("ids", "correct", "f1"),
    [
        (GOLD5, True, 1.0),
        (GOLD5[:4], True, 8 / 9),  # P 1.0, R 0.8
        ([*GOLD5[:4], "EMP-099"], True, 0.8),  # exactly on the 0.8 boundary: counts
        ([*GOLD5[:3], "EMP-098", "EMP-099"], False, 0.6),
        ([], False, 0.0),
    ],
)
def test_set_f1(ids, correct, f1):
    result = score(item("set_f1", GOLD5), ans(ids))
    assert result["correct"] is correct
    assert result["f1"] == pytest.approx(f1)


def test_set_f1_reports_precision_and_recall():
    result = score(item("set_f1", GOLD5), ans([*GOLD5[:3], "EMP-099"]))
    assert (result["precision"], result["recall"]) == (pytest.approx(0.75), pytest.approx(0.6))
    assert score(item("set_f1", GOLD5), ans(GOLD5, abstained=True))["correct"] is False


@pytest.mark.parametrize(
    ("given", "correct"),
    [
        (ans([], abstained=True), True),
        (ans(["RPT-0142"], abstained=True), True),  # pointing at a near candidate is allowed
        (ans(["EMP-081"], abstained=True), False),  # but no person may be the answer
        (ans(["EMP-081"]), False),  # answering at all is wrong
    ],
)
def test_abstain(given, correct):
    assert score(item("abstain", [], should_abstain=True), given)["correct"] is correct


def test_unknown_rule_is_an_error():
    with pytest.raises(ValueError):
        score(item("vibes", []), ans())


def test_the_broadcast_count_note_is_never_scored():
    # Q-F5-1c: min_mentioned_count is written down for later, not scored (D24).
    plain = item("contains_all", ["EMP-001", "EMP-005"], ["EMP-032"])
    noted = {**plain, "gold": {**plain["gold"], "min_mentioned_count": 52}}
    for answer in (
        ans(["EMP-001", "EMP-005"]),
        ans(["EMP-001"]),
        ans(["EMP-001", "EMP-005", "EMP-032"]),
    ):
        assert score(noted, answer) == score(plain, answer)
