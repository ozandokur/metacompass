"""find_similar_past_work: earlier analysis requests about the same thing (spec §7.6).

Searches the `requests` corpus with the hybrid retriever. Requests about one topic are
worded differently on purpose (noise N6), so this is where dense retrieval matters most.
Each hit carries its status, result report and duplicate link, so the agent can say
"this was done, here is the report" or "this was asked before and never finished".
"""

from metacompass.config import output_char_cap
from metacompass.tools.schemas import (
    FindSimilarPastWorkInput,
    PastWorkHit,
    PastWorkOutput,
    ToolContext,
    fit_to_limit,
    parse_args,
)


def find_similar_past_work(
    ctx: ToolContext, description: str, department: str | None = None, top_k: int = 5
) -> PastWorkOutput:
    args = parse_args(
        FindSimilarPastWorkInput, description=description, department=department, top_k=top_k
    )
    result = ctx.retrievers["requests"].search(
        args.description, mode=ctx.retrieval_mode, top_k=args.top_k, department=args.department
    )
    hits = []
    for hit in result.hits:
        q = ctx.store.request(hit.doc_id)
        hits.append(
            PastWorkHit(
                request_id=q.request_id,
                title=q.title,
                status=q.status,
                created_date=q.created_date.isoformat(),
                closed_date=q.closed_date.isoformat() if q.closed_date else None,
                resulting_report_id=q.resulting_report_id,
                duplicate_of_request_id=q.duplicate_of_request_id,
                rank=hit.rank,
            )
        )
    output = PastWorkOutput(hits=hits, signal=result.signal)
    return fit_to_limit(output, ["hits"], output_char_cap("find_similar_past_work"))
