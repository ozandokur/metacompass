"""Tokenizer shared by BM25 indexing and querying (spec §5.3).

Lower-cases, keeps identifiers such as dim_customer, RPT-0142 and GM% whole, and also adds
their parts so a query can match either form. A small fixed stop-word list is removed.
There is deliberately no stemming (decision D06): "returns" and "returned" stay different.
"""

import re

STOPWORDS = frozenset(
    [
        "the", "a", "an", "of", "for", "to", "in", "on", "and",
        "or", "is", "are", "which", "what", "who", "by", "with",
    ]
)  # fmt: skip

# A token is a run of word characters, "-" and "%". "_" is already a word character.
_TOKEN = re.compile(r"[\w%-]+")
# Separators inside a compound token; "%" counts as one so "gm%" also yields "gm".
_PARTS = re.compile(r"[_%-]+")


def tokenize(text: str) -> list[str]:
    """Split text into BM25 tokens. Repeated words stay repeated (term frequency counts)."""
    tokens: list[str] = []
    for raw in _TOKEN.findall(text.lower()):
        token = raw.strip("_-")  # "-" between words or a leading "_" is not a token
        if not token:
            continue
        parts = [p for p in _PARTS.split(token) if p]
        if token != "%" and not parts:
            continue
        if token not in STOPWORDS:
            tokens.append(token)
        if len(parts) > 1 or (parts and parts[0] != token):
            tokens.extend(p for p in parts if p not in STOPWORDS)
    return tokens
