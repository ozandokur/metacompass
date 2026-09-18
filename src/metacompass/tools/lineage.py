"""trace_lineage: where an asset's data comes from, or what depends on it (spec §7.5).

Breadth-first over the lineage graph up to `depth` steps. `truncated` tells the agent
that there is more than it sees: nodes further than `depth`, or a list cut at 100 nodes or
at the output size limit.
"""

import networkx as nx

from metacompass.config import output_char_cap
from metacompass.data.store import InvalidRecordTypeError, record_type
from metacompass.graph import neighbors_bfs
from metacompass.tools.schemas import (
    LineageNode,
    ToolContext,
    ToolError,
    TraceLineageInput,
    TraceLineageOutput,
    fit_to_limit,
    parse_args,
)

MAX_NODES = 100


def trace_lineage(
    ctx: ToolContext, node_id: str, direction: str, depth: int = 3
) -> TraceLineageOutput:
    args = parse_args(TraceLineageInput, node_id=node_id, direction=direction, depth=depth)
    try:
        kind = record_type(args.node_id)
    except InvalidRecordTypeError:
        kind = None
    if kind not in ("table", "report", "metric"):
        raise ToolError("INVALID_ARGUMENT", f"{args.node_id} is not a table, report or metric ID")
    g = ctx.graph
    if args.node_id not in g:
        raise ToolError("NOT_FOUND", f"{args.node_id} does not exist")

    within = neighbors_bfs(g, args.node_id, args.direction, args.depth)
    reachable = (
        nx.ancestors(g, args.node_id)
        if args.direction == "upstream"
        else nx.descendants(g, args.node_id)
    )
    nodes = [
        LineageNode(
            id=node,
            type=g.nodes[node]["type"],
            name=g.nodes[node]["name"],
            layer=g.nodes[node]["layer"],
            status=g.nodes[node]["status"],
            distance=distance,
        )  # fmt: skip
        for node, distance in within[:MAX_NODES]
    ]
    output = TraceLineageOutput(
        root_id=args.node_id,
        direction=args.direction,
        depth=args.depth,
        nodes=nodes,
        truncated=len(reachable) > len(nodes),  # beyond the depth, or cut at MAX_NODES
    )
    return fit_to_limit(output, ["nodes"], output_char_cap("trace_lineage"))
