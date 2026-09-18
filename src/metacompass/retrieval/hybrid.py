"""Hybrid retrieval: BM25 and dense rankings fused with reciprocal rank fusion (spec §5.6).

Filters (record type, department, deprecated reports) become a corpus mask before any
ranking, so a filtered search still has a full candidate list. Every search also returns
a match signal (§5.7): "strong" when the query names an asset exactly or the closest dense
match clears the threshold tau, "weak" otherwise. The agent uses "weak" as evidence for
abstaining. The signal is computed the same way in every mode, so the retrieval-mode
ablations (A1, A2) change the ranking only, not the abstain evidence.
"""

import re
from dataclasses import dataclass
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict

from metacompass.config import RRF_CANDIDATES, RRF_K, TAU
from metacompass.data.schema import RECORD_ID_REGEX
from metacompass.retrieval.bm25 import BM25Index
from metacompass.retrieval.embedders import Embedder

RetrievalMode = Literal["hybrid", "bm25", "dense"]
MODES = ("hybrid", "bm25", "dense")


@dataclass(frozen=True)
class RetrievalDoc:
    doc_id: str
    kind: str  # report | table | metric | request
    bm25_text: str
    dense_text: str
    department: str | None = None
    status: str | None = None  # reports: active | deprecated
    exact_names: tuple[str, ...] = ()  # names that count as naming this document exactly


class MatchSignal(BaseModel):
    model_config = ConfigDict(frozen=True)

    match_quality: Literal["strong", "weak"]
    exact_match: bool  # the query contains a record ID or a full name from the corpus
    top_dense_cosine: float  # best cosine similarity within the filtered corpus


@dataclass(frozen=True)
class Hit:
    doc_id: str
    rank: int  # 1-based
    score: float  # RRF score, BM25 score or cosine, depending on the mode
    bm25_rank: int | None
    dense_rank: int | None


@dataclass(frozen=True)
class SearchResult:
    hits: list[Hit]
    signal: MatchSignal


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """RRF(d) = sum over rankings of 1 / (k + rank of d), ranks starting at 1.

    A document missing from a ranking gets nothing from it. Only ranks are used, so BM25's
    unbounded scores and cosines in [-1, 1] never have to be put on one scale (D05).
    Ties break by ascending document ID, which keeps results deterministic.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def _normalize(text: str) -> str:
    """Lower-case words joined by single spaces, padded so matches stay on word borders."""
    return " " + " ".join(re.findall(r"[a-z0-9]+", text.lower())) + " "


class HybridRetriever:
    def __init__(
        self,
        docs: list[RetrievalDoc],
        embedder: Embedder,
        doc_vectors: np.ndarray | None = None,
        *,
        rrf_k: int = RRF_K,
        n_candidates: int = RRF_CANDIDATES,
        tau: float = TAU,
    ) -> None:
        self.docs = list(docs)
        self.embedder = embedder
        self.rrf_k, self.n_candidates, self.tau = rrf_k, n_candidates, tau
        if doc_vectors is None:
            doc_vectors = embedder.encode([d.dense_text for d in self.docs])
        if doc_vectors.shape != (len(self.docs), embedder.dim):
            raise ValueError("doc_vectors must have one row of embedder.dim values per document")
        self.doc_vectors = doc_vectors
        self.bm25 = BM25Index([d.doc_id for d in self.docs], [d.bm25_text for d in self.docs])
        self._ids = {d.doc_id: i for i, d in enumerate(self.docs)}
        self._names = [
            [_normalize(name) for name in d.exact_names if _normalize(name).strip()]
            for d in self.docs
        ]

    def mask(
        self,
        kinds: set[str] | None = None,
        department: str | None = None,
        include_deprecated: bool = True,
    ) -> np.ndarray:
        return np.array(
            [
                (kinds is None or d.kind in kinds)
                and (department is None or d.department == department)
                and (include_deprecated or d.status != "deprecated")
                for d in self.docs
            ],
            dtype=bool,
        )

    def _exact_match(self, query: str, allowed: np.ndarray) -> bool:
        for found in RECORD_ID_REGEX.findall(query.upper()):
            index = self._ids.get(found)
            if index is not None and allowed[index]:
                return True
        padded = _normalize(query)
        return any(
            allowed[i] and any(name in padded for name in names)
            for i, names in enumerate(self._names)
        )

    def search(
        self,
        query: str,
        *,
        mode: RetrievalMode = "hybrid",
        top_k: int = 5,
        kinds: set[str] | None = None,
        department: str | None = None,
        include_deprecated: bool = True,
    ) -> SearchResult:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        if not query.strip():
            raise ValueError("query must not be empty")
        allowed = self.mask(kinds, department, include_deprecated)
        if not allowed.any():
            weak = MatchSignal(match_quality="weak", exact_match=False, top_dense_cosine=0.0)
            return SearchResult(hits=[], signal=weak)

        cosines = self.doc_vectors @ self.embedder.encode([query])[0]
        dense_order = sorted(
            (i for i in range(len(self.docs)) if allowed[i]),
            key=lambda i: (-float(cosines[i]), self.docs[i].doc_id),
        )
        dense_list = [self.docs[i].doc_id for i in dense_order[: self.n_candidates]]
        bm25_top = self.bm25.top(query, n=self.n_candidates, mask=allowed)
        bm25_list = [doc_id for doc_id, _ in bm25_top]
        bm25_scores = dict(bm25_top)

        if mode == "bm25":
            ranked = [(doc_id, bm25_scores[doc_id]) for doc_id in bm25_list]
        elif mode == "dense":
            ranked = [(doc_id, float(cosines[self._ids[doc_id]])) for doc_id in dense_list]
        else:
            ranked = reciprocal_rank_fusion([bm25_list, dense_list], k=self.rrf_k)

        bm25_rank = {doc_id: r for r, doc_id in enumerate(bm25_list, start=1)}
        dense_rank = {doc_id: r for r, doc_id in enumerate(dense_list, start=1)}
        hits = [
            Hit(doc_id, rank, score, bm25_rank.get(doc_id), dense_rank.get(doc_id))
            for rank, (doc_id, score) in enumerate(ranked[:top_k], start=1)
        ]

        top_cosine = float(cosines[dense_order[0]])
        exact = self._exact_match(query, allowed)
        quality = "strong" if exact or top_cosine >= self.tau else "weak"
        signal = MatchSignal(
            match_quality=quality, exact_match=exact, top_dense_cosine=round(top_cosine, 4)
        )
        return SearchResult(hits=hits, signal=signal)
