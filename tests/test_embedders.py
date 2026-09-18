"""Embedder tests (spec §5.5). The real model test is marked slow: it downloads the model."""

import numpy as np
import pytest

from metacompass.retrieval.embedders import (
    Embedder,
    HashEmbedder,
    SentenceTransformerEmbedder,
    encode_with_cache,
)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(a @ b)


def test_hash_embedder_shape_dtype_and_norm():
    emb = HashEmbedder(dim=64)
    vectors = emb.encode(["parts fill rate", "service retention by dealer"])
    assert vectors.shape == (2, 64)
    assert vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-6)
    assert isinstance(emb, Embedder)


def test_hash_embedder_is_deterministic_across_instances():
    text = ["gross margin by region"]
    assert np.array_equal(HashEmbedder(dim=64).encode(text), HashEmbedder(dim=64).encode(text))


def test_hash_embedder_shared_words_mean_higher_similarity():
    a, b, c = HashEmbedder(dim=64).encode(
        ["parts fill rate by warehouse", "fill rate of parts", "customer satisfaction survey"]
    )
    assert cosine(a, b) > cosine(a, c)


def test_hash_embedder_empty_text_gives_zero_vector():
    vector = HashEmbedder(dim=16).encode([""])[0]
    assert not vector.any()


class CountingEmbedder:
    """Wraps HashEmbedder and counts encode calls, to observe cache hits."""

    def __init__(self):
        self._inner = HashEmbedder(dim=8)
        self.name, self.dim, self.calls = "counting", 8, 0

    def encode(self, texts):
        self.calls += 1
        return self._inner.encode(texts)


def test_cache_writes_once_and_reloads(tmp_path):
    emb = CountingEmbedder()
    texts = ["alpha report", "beta table"]
    first = encode_with_cache(emb, texts, corpus="assets", cache_dir=tmp_path)
    second = encode_with_cache(emb, texts, corpus="assets", cache_dir=tmp_path)
    assert emb.calls == 1
    assert np.array_equal(first, second)
    files = sorted(p.name for p in tmp_path.iterdir())
    assert len(files) == 1
    assert files[0].startswith("emb_counting_assets_") and files[0].endswith(".npy")


def test_cache_key_changes_with_the_texts(tmp_path):
    emb = CountingEmbedder()
    encode_with_cache(emb, ["one"], corpus="assets", cache_dir=tmp_path)
    encode_with_cache(emb, ["one", "two"], corpus="assets", cache_dir=tmp_path)
    assert emb.calls == 2
    assert len(list(tmp_path.iterdir())) == 2


def test_sentence_transformer_name_is_filename_safe():
    emb = SentenceTransformerEmbedder("sentence-transformers/all-MiniLM-L6-v2")
    assert emb.name == "all-MiniLM-L6-v2"
    assert emb.dim == 384


@pytest.mark.slow
def test_real_model_encodes_normalized_vectors_with_meaning():
    emb = SentenceTransformerEmbedder("sentence-transformers/all-MiniLM-L6-v2")
    a, b, c = emb.encode(
        [
            "share of car owners who come back to our workshops for servicing",
            "service retention rate at dealerships",
            "warehouse parts stock valuation",
        ]
    )
    assert a.shape == (384,)
    assert np.isclose(np.linalg.norm(a), 1.0, atol=1e-5)
    assert cosine(a, b) > cosine(a, c)
