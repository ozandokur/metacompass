"""Builds the two retrieval corpora from the metadata store (spec §5.1, §5.2).

`assets` holds reports, tables and metrics for search_assets; `requests` holds analysis
requests for find_similar_past_work. BM25 text weights important fields by repeating them;
dense text is a short readable sentence without record IDs.
"""

import re
from pathlib import Path

from metacompass.data.store import MetadataStore
from metacompass.retrieval.embedders import Embedder, encode_with_cache
from metacompass.retrieval.hybrid import HybridRetriever, RetrievalDoc

# An alias counts as an exact name only if it cannot be an everyday word: an acronym
# ("AOV", "GM%") or several words ("gross margin"). "units" or "turns" alone are not names.
_ACRONYM = re.compile(r"^[A-Z0-9%&]{2,}$")


def _is_distinctive(alias: str) -> bool:
    return bool(_ACRONYM.match(alias)) or len(re.findall(r"[a-z0-9]+", alias.lower())) >= 2


def _join(*parts: str) -> str:
    return " ".join(part for part in parts if part)


def _sentence(*parts: str) -> str:
    return " ".join(part.strip().rstrip(".") + "." for part in parts if part.strip())


def asset_documents(store: MetadataStore) -> list[RetrievalDoc]:
    docs: list[RetrievalDoc] = []
    for r in store.reports.values():
        tags = store.report_tags(r)
        docs.append(
            RetrievalDoc(
                doc_id=r.report_id,
                kind="report",
                bm25_text=_join(
                    r.report_id,
                    *[r.name] * 3,
                    *[" ".join(tags)] * 2,
                    r.workspace,
                    r.department,
                    r.description,
                ),
                dense_text=_sentence(r.name, r.description, "Tags: " + ", ".join(tags)),
                department=r.department,
                status=r.status,
                exact_names=(r.name,),
            )
        )
    for t in store.tables.values():
        columns = " ".join(c["name"] for c in store.table_columns(t))
        docs.append(
            RetrievalDoc(
                doc_id=t.table_id,
                kind="table",
                bm25_text=_join(
                    t.table_id,
                    *[t.name] * 3,
                    t.layer,
                    t.schema_name,
                    t.source_system,
                    columns,
                    t.description,
                ),
                dense_text=_sentence(t.name, t.description),
                department=store.employee(t.owner_id).department,
                exact_names=(t.name,),
            )
        )
    for m in store.metrics.values():
        aliases = store.metric_aliases(m)
        docs.append(
            RetrievalDoc(
                doc_id=m.metric_id,
                kind="metric",
                bm25_text=_join(
                    m.metric_id,
                    *[m.name] * 3,
                    *[" ".join(aliases)] * 3,
                    m.business_definition,
                    m.formula or "",
                ),
                dense_text=_sentence(m.name, m.business_definition, "Tags: " + ", ".join(aliases)),
                department=store.employee(m.owner_id).department,
                exact_names=(m.name, *[a for a in aliases if _is_distinctive(a)]),
            )
        )
    return sorted(docs, key=lambda d: d.doc_id)


def request_documents(store: MetadataStore) -> list[RetrievalDoc]:
    return [
        RetrievalDoc(
            doc_id=q.request_id,
            kind="request",
            bm25_text=_join(q.request_id, q.title, q.title, q.description),
            dense_text=_sentence(q.title, q.description),
            department=q.department,
            status=q.status,
        )
        for q in sorted(store.requests.values(), key=lambda q: q.request_id)
    ]


def build_retrievers(
    store: MetadataStore, embedder: Embedder, cache_dir: Path, tau: float | None = None
) -> dict[str, HybridRetriever]:
    """Both retrievers, with document embeddings read from / written to cache_dir."""
    retrievers = {}
    for corpus, docs in (
        ("assets", asset_documents(store)),
        ("requests", request_documents(store)),
    ):
        vectors = encode_with_cache(embedder, [d.dense_text for d in docs], corpus, cache_dir)
        extra = {} if tau is None else {"tau": tau}
        retrievers[corpus] = HybridRetriever(docs, embedder, vectors, **extra)
    return retrievers
