"""Hybrid retrieval tests (spec §5.6, §5.7): RRF, filters, modes and the match signal."""

import numpy as np
import pytest

from metacompass.data.store import MetadataStore
from metacompass.retrieval.corpus import asset_documents, build_retrievers, request_documents
from metacompass.retrieval.embedders import HashEmbedder
from metacompass.retrieval.hybrid import HybridRetriever, RetrievalDoc, reciprocal_rank_fusion

# ---------------------------------------------------------------- RRF by hand


def test_rrf_matches_hand_computation():
    fused = reciprocal_rank_fusion([["A", "B", "C"], ["B", "D", "A"]], k=60)
    expected = {
        "A": 1 / 61 + 1 / 63,
        "B": 1 / 62 + 1 / 61,
        "C": 1 / 63,  # only in the first list: no contribution from the second
        "D": 1 / 62,
    }
    assert [doc for doc, _ in fused] == ["B", "A", "D", "C"]
    for doc, score in fused:
        assert score == pytest.approx(expected[doc])


def test_rrf_ties_break_by_id():
    fused = reciprocal_rank_fusion([["Z", "A"], ["A", "Z"]], k=60)
    assert [doc for doc, _ in fused] == ["A", "Z"]


def test_rrf_uses_k():
    (_, score_k1), *_ = reciprocal_rank_fusion([["A"]], k=1)
    assert score_k1 == pytest.approx(1 / 2)


# ---------------------------------------------------------------- a small corpus

DOCS = [
    RetrievalDoc("RPT-0001", "report", "RPT-0001 Service Retention Service Retention owners workshop",
                 "Service Retention. Owners who come back to the workshop.", "Aftersales", "active",
                 ("Service Retention",)),
    RetrievalDoc("RPT-0002", "report", "RPT-0002 Service Retention Legacy Service Retention",
                 "Service Retention Legacy. Old retention view.", "Aftersales", "deprecated",
                 ("Service Retention Legacy",)),
    RetrievalDoc("RPT-0003", "report", "RPT-0003 Parts Fill Rate Parts Fill Rate warehouse stock",
                 "Parts Fill Rate. Lines shipped complete from stock.", "Supply Chain", "active",
                 ("Parts Fill Rate",)),
    RetrievalDoc("TBL-001", "table", "TBL-001 fct_service_orders fct_service_orders workshop repair orders",
                 "fct_service_orders. Repair orders from the workshop.", "Data & Analytics", None,
                 ("fct_service_orders",)),
    RetrievalDoc("MET-001", "metric", "MET-001 Gross Margin % GM% GM% gross margin revenue cost",
                 "Gross Margin %. Revenue minus cost of sales. Tags: GM%", "Finance", None,
                 ("Gross Margin %", "GM%")),
]  # fmt: skip


@pytest.fixture(scope="module")
def retriever() -> HybridRetriever:
    return HybridRetriever(DOCS, HashEmbedder(dim=64), tau=0.45)


@pytest.mark.parametrize("mode", ["hybrid", "bm25", "dense"])
def test_every_mode_finds_the_obvious_document(retriever, mode):
    result = retriever.search("parts fill rate warehouse", mode=mode, top_k=3)
    assert result.hits[0].doc_id == "RPT-0003"
    assert [h.rank for h in result.hits] == list(range(1, len(result.hits) + 1))


def test_hybrid_ranks_follow_rrf_of_the_two_lists(retriever):
    query = "service retention workshop"
    bm25_ids = [h.doc_id for h in retriever.search(query, mode="bm25", top_k=5).hits]
    dense_ids = [h.doc_id for h in retriever.search(query, mode="dense", top_k=5).hits]
    fused = [doc for doc, _ in reciprocal_rank_fusion([bm25_ids, dense_ids], k=60)]
    hybrid_ids = [h.doc_id for h in retriever.search(query, mode="hybrid", top_k=5).hits]
    assert hybrid_ids == fused[:5]


def test_filters_are_applied_before_ranking():
    # With only 2 candidates per list, filtering after ranking would lose the metric.
    small = HybridRetriever(DOCS, HashEmbedder(dim=64), n_candidates=2, tau=0.45)
    result = small.search("service retention gross margin", kinds={"metric"})
    assert [h.doc_id for h in result.hits] == ["MET-001"]


def test_department_and_deprecated_filters(retriever):
    by_dept = retriever.search("service retention", department="Supply Chain", mode="bm25")
    assert all(h.doc_id == "RPT-0003" for h in by_dept.hits)
    active_only = retriever.search("service retention legacy", include_deprecated=False)
    assert "RPT-0002" not in [h.doc_id for h in active_only.hits]


def test_empty_corpus_after_filter_is_weak(retriever):
    result = retriever.search("service retention", kinds={"request"})
    assert result.hits == []
    assert result.signal.match_quality == "weak"
    assert result.signal.top_dense_cosine == 0.0


def test_exact_id_in_query_is_strong(retriever):
    signal = retriever.search("what is rpt-0003 about?").signal
    assert signal.exact_match is True
    assert signal.match_quality == "strong"


def test_exact_name_in_query_is_strong(retriever):
    signal = retriever.search("who owns fct_service_orders today").signal
    assert signal.exact_match is True
    assert retriever.search("which metric is GM%").signal.exact_match is True


def test_unknown_id_is_not_an_exact_match(retriever):
    assert retriever.search("RPT-9999").signal.exact_match is False


def test_dense_threshold_decides_without_exact_match():
    strict = HybridRetriever(DOCS, HashEmbedder(dim=64), tau=0.99)
    lenient = HybridRetriever(DOCS, HashEmbedder(dim=64), tau=0.01)
    query = "workshop owners come back"
    assert strict.search(query).signal.match_quality == "weak"
    assert lenient.search(query).signal.match_quality == "strong"
    assert strict.search(query).signal.exact_match is False


def test_signal_is_the_same_in_every_mode(retriever):
    signals = {
        retriever.search("repair orders", mode=m).signal for m in ("hybrid", "bm25", "dense")
    }
    assert len(signals) == 1


def test_search_is_deterministic(retriever):
    first = retriever.search("service", top_k=5)
    assert retriever.search("service", top_k=5) == first


def test_rejects_bad_arguments(retriever):
    with pytest.raises(ValueError):
        retriever.search("x", mode="fuzzy")
    with pytest.raises(ValueError):
        retriever.search("", mode="hybrid")
    with pytest.raises(ValueError):
        HybridRetriever(DOCS, HashEmbedder(dim=8), doc_vectors=np.zeros((2, 8)))


# ---------------------------------------------------------------- corpus built from the store


@pytest.fixture(scope="module")
def store(generated_dir) -> MetadataStore:
    return MetadataStore.from_dir(generated_dir)


def test_asset_corpus_covers_reports_tables_and_metrics(store):
    docs = asset_documents(store)
    kinds = [d.kind for d in docs]
    assert (kinds.count("report"), kinds.count("table"), kinds.count("metric")) == (250, 80, 40)
    assert len(request_documents(store)) == 300


def test_bm25_text_weights_names_and_dense_text_has_no_ids(store):
    docs = {d.doc_id: d for d in asset_documents(store)}
    report = store.report("RPT-0001")
    doc = docs["RPT-0001"]
    assert doc.bm25_text.startswith("RPT-0001 ")
    assert doc.bm25_text.count(report.name) >= 3
    assert "RPT-0001" not in doc.dense_text
    assert doc.dense_text.startswith(report.name + ". ")


def test_tables_and_metrics_are_filtered_by_owner_department(store):
    docs = {d.doc_id: d for d in asset_documents(store)}
    table = store.table("TBL-001")
    assert docs["TBL-001"].department == store.employee(table.owner_id).department


def test_metric_exact_names_keep_acronyms_but_not_generic_words(store):
    docs = {d.doc_id: d for d in asset_documents(store)}
    units_sold = docs["MET-001"]  # aliases: units | vehicle units | sales volume
    assert "Units Sold" in units_sold.exact_names
    assert "units" not in units_sold.exact_names
    assert "vehicle units" in units_sold.exact_names
    assert "AOV" in docs["MET-003"].exact_names


def test_build_retrievers_uses_the_cache(store, tmp_path):
    retrievers = build_retrievers(store, HashEmbedder(dim=32), cache_dir=tmp_path)
    assert set(retrievers) == {"assets", "requests"}
    assert len(list(tmp_path.glob("emb_hash32_*.npy"))) == 2
    hit = retrievers["assets"].search(store.table("TBL-069").name, top_k=1).hits[0]
    assert hit.doc_id == "TBL-069"
