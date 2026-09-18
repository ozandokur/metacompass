"""Shared rules of the question-set builders: paths, word overlap, and which reports are
noise (spec §5.8, §9.5).

Used by build_sets.py (retrieval benchmark set) and question_sets.py (dev and test sets),
so both apply the same leak checks.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "eval"
TEMPLATES = EVAL_DIR / "templates.json"
VOCAB_DIR = ROOT / "src" / "metacompass" / "data" / "vocab"

# The retrieval stop-word list (spec §5.3).
STOPWORDS = {
    "the", "a", "an", "of", "for", "to", "in", "on", "and",
    "or", "is", "are", "which", "what", "who", "by", "with",
}  # fmt: skip
# English function words, used on top of STOPWORDS when checking whether a paraphrase
# borrows the target's description: "how" or "as" in both texts is not leaked content.
FUNCTION_WORDS = STOPWORDS | {
    "about", "after", "all", "am", "any", "as", "at", "be", "been", "before", "being", "both",
    "but", "can", "could", "did", "do", "does", "each", "every", "from", "had", "has", "have",
    "he", "her", "here", "his", "how", "i", "if", "into", "it", "its", "just", "me", "my",
    "no", "not", "our", "ours", "out", "over", "own", "per", "she", "so", "some", "such",
    "than", "that", "their", "them", "then", "there", "these", "they", "this", "those",
    "through", "too", "until", "up", "us", "very", "was", "we", "were", "when", "where",
    "whether", "while", "why", "will", "would", "yet", "you", "your",
}  # fmt: skip
MAX_PARAPHRASE_OVERLAP = 0.30  # share of the target name's words (spec §9.5)
MAX_DESCRIPTION_OVERLAP = 0.20  # share of the query's content words (spec update 2026-09-18)


def load_templates() -> dict:
    return json.loads(TEMPLATES.read_text(encoding="utf-8"))


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - STOPWORDS


def norm(text: str) -> str:
    """Lower-case words joined by single spaces, padded, for whole-word substring checks."""
    return " " + " ".join(re.findall(r"[a-z0-9]+", text.lower())) + " "


def name_overlap(query: str, name: str) -> float:
    """Share of the name's content words that also appear in the query."""
    name_words = words(name)
    return len(name_words & words(query)) / len(name_words) if name_words else 0.0


def frame_words(templates: list[str]) -> set[str]:
    """Words every question from these templates shares, because the template supplies them."""
    found: set[str] = set()
    for template in templates:
        found |= words(re.sub(r"\{[a-z_]+\}", " ", template))
    return found


def content_overlap(query: str, text: str, frame: set[str]) -> float:
    """Share of the query's own content words that also appear in `text`.

    Stop words, function words and the template's fixed words are ignored: they are the same
    for every question, so they cannot point at one target. What is left is the paraphrase
    itself, which must not borrow the target's words, or BM25 gets the answer for free.
    """
    content = words(query) - frame - FUNCTION_WORDS
    return len(content & (words(text) - FUNCTION_WORDS)) / len(content) if content else 0.0


def noise_members(meta: dict) -> set[str]:
    """Reports in a designed near-duplicate or deprecated pair."""
    members = {rid for pair in meta["near_duplicate_pairs"] for rid in pair}
    return members | set(meta["deprecated_map"]) | set(meta["deprecated_map"].values())


def unique_combos(meta: dict) -> set[str]:
    """Reports that are the only one with their (subject, qualifier) combination.

    A paraphrase names a topic and a dimension. If two reports share both (a deprecated
    report and its replacement, a near duplicate and its base), the question has two right
    answers and a single-target gold measures nothing, so neither may be a paraphrase target.
    """
    subjects, qualifiers = meta["report_subjects"], meta["report_qualifiers"]
    counts: dict[tuple[str, str], int] = {}
    for rid in subjects:
        combo = (subjects[rid], qualifiers[rid])
        counts[combo] = counts.get(combo, 0) + 1
    return {rid for rid in subjects if counts[(subjects[rid], qualifiers[rid])] == 1}


def write_json(path: Path, payload: dict) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    path.write_bytes(text.encode("utf-8"))
