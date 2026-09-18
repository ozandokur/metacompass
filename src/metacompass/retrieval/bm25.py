"""Lexical retrieval: an Okapi BM25 index over tokenized documents (spec §5.4).

Scores are only used to rank; they are unbounded and not comparable across queries,
which is why the hybrid retriever fuses ranks (RRF) rather than scores.
"""

import numpy as np
from rank_bm25 import BM25Okapi

from metacompass.retrieval.tokenize import tokenize


class BM25Index:
    def __init__(self, doc_ids: list[str], texts: list[str], k1: float = 1.5, b: float = 0.75):
        if len(doc_ids) != len(texts):
            raise ValueError("doc_ids and texts must have the same length")
        self.doc_ids = list(doc_ids)
        self._bm25 = BM25Okapi([tokenize(text) for text in texts], k1=k1, b=b)

    def scores(self, query: str) -> np.ndarray:
        """One score per document, in doc_ids order."""
        tokens = tokenize(query)
        if not tokens:
            return np.zeros(len(self.doc_ids))
        return np.asarray(self._bm25.get_scores(tokens), dtype=float)

    def matches(self, query: str) -> np.ndarray:
        """True for documents that contain at least one query token."""
        tokens = set(tokenize(query))
        return np.array([bool(tokens & freqs.keys()) for freqs in self._bm25.doc_freqs])

    def top(self, query: str, n: int, mask: np.ndarray | None = None) -> list[tuple[str, float]]:
        """Best n documents that share a word with the query; ties by ascending ID.

        A lexical retriever should not vote for a document that shares no word with the
        query. The test is term overlap, not score > 0: Okapi idf is negative (or floored)
        for terms found in more than half of the documents, such as the "rpt" part of every
        report ID, so a genuine match can score zero or below.
        """
        scores = self.scores(query)
        candidates = self.matches(query)
        if mask is not None:
            candidates &= mask
        ranked = sorted(
            (
                (doc_id, float(score))
                for doc_id, score, ok in zip(self.doc_ids, scores, candidates, strict=True)
                if ok
            ),
            key=lambda item: (-item[1], item[0]),
        )
        return ranked[:n]
