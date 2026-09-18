"""Final answer parsing and the grounding check (spec §8.3, §8.5)."""

import json

from metacompass.agent.answer import (
    UNVERIFIED,
    FinalAnswer,
    abstained_answer,
    enforce_grounding,
    parse_final,
)

GOOD = {
    "answer": "RPT-0142 is owned by EMP-081.",
    "answer_ids": ["EMP-081"],
    "evidence_ids": ["RPT-0142"],
    "abstained": False,
}


def answer(**fields) -> FinalAnswer:
    return FinalAnswer(**{**GOOD, **fields})


# ---------------------------------------------------------------------- parse_final


def test_parse_plain_json():
    assert parse_final(json.dumps(GOOD)) == FinalAnswer(**GOOD)


def test_parse_json_in_a_code_fence_or_with_words_around_it():
    fenced = "```json\n" + json.dumps(GOOD) + "\n```"
    wrapped = "Here is my answer:\n" + json.dumps(GOOD) + "\nThanks."
    assert parse_final(fenced) == FinalAnswer(**GOOD)
    assert parse_final(wrapped) == FinalAnswer(**GOOD)


def test_parse_rejects_anything_that_is_not_a_complete_answer():
    missing = {k: v for k, v in GOOD.items() if k != "abstained"}
    wrong_type = {**GOOD, "answer_ids": "EMP-081"}
    for text in [
        None,
        "",
        "EMP-081 owns it.",
        "{not json}",
        json.dumps([GOOD]),
        json.dumps(missing),
        json.dumps(wrong_type),
    ]:
        assert parse_final(text) is None, text


def test_parse_tidies_ids():
    messy = {**GOOD, "answer_ids": [" EMP-081", "EMP-081 "], "evidence_ids": ["RPT-0142", ""]}
    parsed = parse_final(json.dumps(messy))
    assert parsed.answer_ids == ["EMP-081"]
    assert parsed.evidence_ids == ["RPT-0142"]


def test_abstained_answer():
    out = abstained_answer("I could not find that report.")
    assert (out.abstained, out.answer_ids, out.evidence_ids) == (True, [], [])
    assert out.answer == "I could not find that report."


# ---------------------------------------------------------------------- enforce_grounding


def test_grounded_answer_is_left_alone():
    out, stripped = enforce_grounding(answer(), {"EMP-081", "RPT-0142"})
    assert (out, stripped) == (answer(), [])


def test_unseen_ids_are_removed_from_lists_and_text():
    given = answer(
        answer="RPT-0142 is owned by EMP-081; ask EMP-999 too.",
        answer_ids=["EMP-081", "EMP-999"],
    )
    out, stripped = enforce_grounding(given, {"EMP-081", "RPT-0142"})
    assert stripped == ["EMP-999"]
    assert out.answer_ids == ["EMP-081"]
    assert out.answer == f"RPT-0142 is owned by EMP-081; ask {UNVERIFIED} too."
    assert out.abstained is False  # a verified answer is still there


def test_answer_with_no_verified_ids_left_becomes_an_abstention():
    given = answer(answer="EMP-999 owns it.", answer_ids=["EMP-999"], evidence_ids=["RPT-0142"])
    out, stripped = enforce_grounding(given, {"RPT-0142"})
    assert stripped == ["EMP-999"]
    assert out.answer_ids == []
    assert out.abstained is True
    assert out.answer.startswith(f"{UNVERIFIED} owns it.")
    assert "could not verify" in out.answer


def test_unseen_evidence_ids_are_removed_without_abstaining():
    out, stripped = enforce_grounding(
        answer(evidence_ids=["RPT-0142", "TBL-999"]), {"EMP-081", "RPT-0142"}
    )
    assert stripped == ["TBL-999"]
    assert out.evidence_ids == ["RPT-0142"]
    assert out.abstained is False


def test_an_invented_id_only_in_the_text_is_caught_too():
    # Not in the spec's lists, but an invented ID must not reach the user either way (D12).
    given = answer(answer="EMP-081 owns it, see also RPT-0777.")
    out, stripped = enforce_grounding(given, {"EMP-081", "RPT-0142"})
    assert stripped == ["RPT-0777"]
    assert out.answer == f"EMP-081 owns it, see also {UNVERIFIED}."


def test_an_abstention_without_answer_ids_stays_as_it_is():
    given = abstained_answer("Salaries are not in the metadata.")
    assert enforce_grounding(given, set()) == (given, [])
