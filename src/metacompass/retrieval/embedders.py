"""Dense embedders and an on-disk embedding cache (spec §5.5).

Production uses a small sentence-transformers model. Tests use HashEmbedder: a
deterministic bag-of-hashed-tokens vector that needs no network and no model download
(decision D20). Every embedder returns L2-normalised float32 rows, so a dot product is
the cosine similarity.
"""

import hashlib
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from metacompass.retrieval.tokenize import tokenize

# Known output sizes, so `dim` is available without loading (and downloading) the model.
_KNOWN_DIMS = {"all-MiniLM-L6-v2": 384}


@runtime_checkable
class Embedder(Protocol):
    name: str
    dim: int

    def encode(self, texts: list[str]) -> np.ndarray:
        """Return a (len(texts), dim) float32 array of L2-normalised rows."""
        ...


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return np.divide(vectors, norms, out=np.zeros_like(vectors), where=norms > 0)


class HashEmbedder:
    """Feature hashing of tokens into `dim` buckets with a +/-1 sign per token.

    Texts that share tokens get similar vectors; it knows nothing about synonyms. That is
    fine for tests of plumbing and ranking logic, not for measuring retrieval quality.
    """

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim
        self.name = f"hash{dim}"

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in tokenize(text):
                # blake2b, not hash(): Python's string hash changes between processes.
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                bucket = int.from_bytes(digest[:4], "big") % self.dim
                vectors[row, bucket] += 1.0 if digest[4] & 1 else -1.0
        return _normalize(vectors)


class SentenceTransformerEmbedder:
    """Wraps a sentence-transformers model; the model is loaded on first use."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.name = model_name.rsplit("/", 1)[-1]
        self._model = None
        self.dim = _KNOWN_DIMS.get(self.name) or self._load().get_sentence_embedding_dimension()

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # heavy import, lazy

            self._model = SentenceTransformer(self.model_name, device="cpu")
        return self._model

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = self._load().encode(
            list(texts),
            batch_size=64,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        if vectors.shape[1] != self.dim:
            raise ValueError(f"{self.name} returned {vectors.shape[1]} dims, expected {self.dim}")
        return vectors.astype(np.float32)


def encode_with_cache(
    embedder: Embedder, texts: list[str], corpus: str, cache_dir: Path
) -> np.ndarray:
    """Encode documents once and reuse the vectors from data/cache/ on later runs.

    The file name holds a hash of the exact texts, so any change to the documents (or to
    the embedder) misses the cache instead of silently reusing stale vectors.
    """
    key = hashlib.sha256(
        "\n".join([embedder.name, str(embedder.dim), *texts]).encode("utf-8")
    ).hexdigest()[:16]
    path = Path(cache_dir) / f"emb_{embedder.name}_{corpus}_{key}.npy"
    if path.is_file():
        cached = np.load(path)
        if cached.shape == (len(texts), embedder.dim):
            return cached
    vectors = embedder.encode(texts)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.npy")
    np.save(tmp, vectors)
    tmp.replace(path)
    return vectors
