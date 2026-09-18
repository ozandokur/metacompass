"""search_assets: find reports, tables and metrics by name or description (spec §7.2).

A thin layer over the hybrid retriever of the `assets` corpus: it validates the arguments,
turns filters into the retriever's corpus mask, and returns short hit cards plus the match
signal the agent uses as abstain evidence.
"""

from metacompass.config import output_char_cap
from metacompass.data.store import record_type
from metacompass.retrieval.hybrid import Hit
from metacompass.tools.schemas import (
    AssetHit,
    SearchAssetsInput,
    SearchAssetsOutput,
    ToolContext,
    fit_to_limit,
    parse_args,
)

SNIPPET_CHARS = 160


def snippet(text: str) -> str:
    return text if len(text) <= SNIPPET_CHARS else text[: SNIPPET_CHARS - 3] + "..."


def _card(ctx: ToolContext, hit: Hit) -> AssetHit:
    store, kind = ctx.store, record_type(hit.doc_id)
    if kind == "report":
        r = store.report(hit.doc_id)
        return AssetHit(
            id=r.report_id, type="report", name=r.name, department=r.department,
            status=r.status, replaced_by_report_id=r.replaced_by_report_id,
            snippet=snippet(r.description), rank=hit.rank,
        )  # fmt: skip
    if kind == "table":
        t = store.table(hit.doc_id)
        return AssetHit(
            id=t.table_id, type="table", name=t.name,
            department=store.employee(t.owner_id).department, status=None,
            replaced_by_report_id=None, snippet=snippet(t.description), rank=hit.rank,
        )  # fmt: skip
    m = store.metric(hit.doc_id)
    return AssetHit(
        id=m.metric_id, type="metric", name=m.name,
        department=store.employee(m.owner_id).department, status=None,
        replaced_by_report_id=None, snippet=snippet(m.business_definition), rank=hit.rank,
    )  # fmt: skip


def search_assets(
    ctx: ToolContext,
    query: str,
    asset_type: str = "any",
    department: str | None = None,
    include_deprecated: bool = True,
    top_k: int = 5,
) -> SearchAssetsOutput:
    args = parse_args(
        SearchAssetsInput,
        query=query,
        asset_type=asset_type,
        department=department,
        include_deprecated=include_deprecated,
        top_k=top_k,
    )
    result = ctx.retrievers["assets"].search(
        args.query,
        mode=ctx.retrieval_mode,
        top_k=args.top_k,
        kinds=None if args.asset_type == "any" else {args.asset_type},
        department=args.department,
        include_deprecated=args.include_deprecated,
    )
    output = SearchAssetsOutput(
        query=args.query, hits=[_card(ctx, hit) for hit in result.hits], signal=result.signal
    )
    return fit_to_limit(output, ["hits"], output_char_cap("search_assets"))
