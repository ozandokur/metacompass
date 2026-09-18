"""Deterministic scoring of one agent answer against its question's gold (spec §9.6).

Only `answer_ids` and `abstained` are scored, never the answer text (D11); there is no
LLM judge. Each question names its rule:
  contains_all  not abstained, every gold ID given, no forbidden ID given
  contains_any  not abstained, at least one gold ID given (reported: hits)
  set_f1        not abstained, F1(answer_ids, gold) >= 0.8 (reported: precision, recall, F1)
  abstain       abstained, and no person (EMP) given as the answer
"""

F1_THRESHOLD = 0.8


def score(item: dict, answer: dict) -> dict:
    """{"correct": bool, ...rule-specific details} for one answer to one question."""
    rule, gold = item["scoring"], item["gold"]
    given = set(answer["answer_ids"])
    expected = set(gold["answer_ids"])
    abstained = bool(answer["abstained"])

    if rule == "contains_all":
        forbidden_hit = given & set(gold["forbidden_ids"])
        correct = not abstained and expected <= given and not forbidden_hit
        return {"correct": correct, "forbidden_hit": sorted(forbidden_hit)}

    if rule == "contains_any":
        hits = len(given & expected)
        return {"correct": not abstained and hits > 0, "hits": hits}

    if rule == "set_f1":
        true_positives = len(given & expected)
        precision = true_positives / len(given) if given else 0.0
        recall = true_positives / len(expected) if expected else 0.0
        # 2·tp / (|given| + |gold|) equals 2PR / (P + R) and keeps the 0.8 boundary exact.
        f1 = 2 * true_positives / (len(given) + len(expected)) if given or expected else 0.0
        correct = not abstained and f1 >= F1_THRESHOLD
        return {"correct": correct, "precision": precision, "recall": recall, "f1": f1}

    if rule == "abstain":
        people = sorted(i for i in given if i.startswith("EMP-"))
        return {"correct": abstained and not people, "people_given": people}

    raise ValueError(f"unknown scoring rule {rule!r}")
