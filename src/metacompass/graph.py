"""Lineage graph: tables, reports and metrics as one directed acyclic graph (spec §6).

Edges follow the data: parent table -> child table, table -> report, table -> metric.
"Upstream" therefore means predecessors and "downstream" successors. BFS visits
neighbours in ID order and returns (node, shortest distance) pairs sorted by distance,
then ID, so every traversal is deterministic.
"""

from collections import deque
from typing import Literal

import networkx as nx

from metacompass.data.store import MetadataStore

Direction = Literal["upstream", "downstream"]
MIN_DEPTH, MAX_DEPTH = 1, 6


def build_lineage_graph(store: MetadataStore) -> nx.DiGraph:
    g = nx.DiGraph()
    for t in store.tables.values():
        g.add_node(t.table_id, type="table", name=t.name, layer=t.layer, status=None)
    for r in store.reports.values():
        g.add_node(r.report_id, type="report", name=r.name, layer=None, status=r.status)
    for m in store.metrics.values():
        g.add_node(m.metric_id, type="metric", name=m.name, layer=None, status=None)
    g.add_edges_from((e.parent_table_id, e.child_table_id) for e in store.table_table_edges)
    g.add_edges_from((e.table_id, e.report_id) for e in store.report_table_edges)
    for m in store.metrics.values():
        g.add_edges_from((tid, m.metric_id) for tid in store.metric_source_table_ids(m))
    if not nx.is_directed_acyclic_graph(g):
        cycle = nx.find_cycle(g)
        raise ValueError(f"lineage graph has a cycle: {cycle}")
    return g


def neighbors_bfs(
    g: nx.DiGraph, node_id: str, direction: Direction, depth: int
) -> list[tuple[str, int]]:
    """Nodes within `depth` steps in one direction, with their shortest distance; root excluded."""
    if direction not in ("upstream", "downstream"):
        raise ValueError(f"direction must be 'upstream' or 'downstream', got {direction!r}")
    if not MIN_DEPTH <= depth <= MAX_DEPTH:
        raise ValueError(f"depth must be between {MIN_DEPTH} and {MAX_DEPTH}, got {depth}")
    if node_id not in g:
        raise KeyError(node_id)
    step = g.predecessors if direction == "upstream" else g.successors
    distance = {node_id: 0}
    queue = deque([node_id])
    while queue:
        current = queue.popleft()
        if distance[current] == depth:
            continue
        for neighbour in sorted(step(current)):
            if neighbour not in distance:
                distance[neighbour] = distance[current] + 1
                queue.append(neighbour)
    del distance[node_id]
    return sorted(distance.items(), key=lambda item: (item[1], item[0]))


def all_descendants(g: nx.DiGraph, node_id: str) -> set[str]:
    """Everything downstream of a node, at any distance."""
    if node_id not in g:
        raise KeyError(node_id)
    return set(nx.descendants(g, node_id))
