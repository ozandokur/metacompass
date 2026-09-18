"""The agent's final answer: its schema, parsing, and the grounding check (spec §8.3, §8.5).

The model ends with a JSON object. Scoring reads only `answer_ids` and `abstained`
(decision D11), so the answer must parse exactly. The grounding check then removes every
record ID that no tool returned in this conversation: an invented ID must never reach the
user, whatever the agent configuration (decision D12).
"""

import json
import re

from pydantic import BaseModel, ValidationError, field_validator

from metacompass.data.schema import RECORD_ID_REGEX

UNVERIFIED = "[unverified]"
UNVERIFIED_NOTE = (
    " (I could not verify the records behind this answer in the tool results, so I am not "
    "giving one.)"
)
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class FinalAnswer(BaseModel):
    answer: str  # short English text for the user
    answer_ids: list[str]  # the entities that ARE the answer
    evidence_ids: list[str]  # other records consulted
    abstained: bool  # True if the requested information is not verifiably in the data

    @field_validator("answer_ids", "evidence_ids")
    @classmethod
    def _tidy(cls, ids: list[str]) -> list[str]:
        cleaned = (i.strip() for i in ids)
        return list(dict.fromkeys(i for i in cleaned if i))


def parse_final(text: str | None) -> FinalAnswer | None:
    """The answer in the model's final message, or None if there is no valid one.

    Tolerates a code fence or a sentence around the JSON object, because models add them
    even when told not to; anything else is a parse failure for the loop to handle.
    """
    if not text or not text.strip():
        return None
    body = text.strip()
    fenced = _FENCE.match(body)
    if fenced:
        body = fenced.group(1)
    candidates = [body]
    start, end = body.find("{"), body.rfind("}")
    if 0 <= start < end:
        candidates.append(body[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            return None
        try:
            return FinalAnswer.model_validate(data)
        except ValidationError:
            return None
    return None


def abstained_answer(message: str) -> FinalAnswer:
    return FinalAnswer(answer=message, answer_ids=[], evidence_ids=[], abstained=True)


def enforce_grounding(answer: FinalAnswer, seen_ids: set[str]) -> tuple[FinalAnswer, list[str]]:
    """Remove every record ID the tools never returned; returns (answer, removed IDs).

    Unseen IDs leave answer_ids and evidence_ids and become [unverified] in the text. The
    text is checked on its own too (the spec only names the lists): an ID the model wrote
    only in the prose is just as invented. If that leaves no answer IDs at all, the answer
    turns into an abstention.
    """
    text_ids = RECORD_ID_REGEX.findall(answer.answer)
    mentioned = [*answer.answer_ids, *answer.evidence_ids, *text_ids]
    stripped = list(dict.fromkeys(i for i in mentioned if i not in seen_ids))
    if not stripped:
        return answer, []

    removed = set(stripped)
    text = RECORD_ID_REGEX.sub(
        lambda m: UNVERIFIED if m.group(0) in removed else m.group(0), answer.answer
    )
    answer_ids = [i for i in answer.answer_ids if i not in removed]
    evidence_ids = [i for i in answer.evidence_ids if i not in removed]
    abstained = answer.abstained
    if answer.answer_ids and not answer_ids and not abstained:
        abstained = True
        text += UNVERIFIED_NOTE
    grounded = FinalAnswer(
        answer=text, answer_ids=answer_ids, evidence_ids=evidence_ids, abstained=abstained
    )
    return grounded, stripped
