"""Lineage graph tests (spec §6.3). Expected sets are worked out by hand from the mini fixture."""

import shutil

import networkx as nx
import pytest

from metacompass.data.store import MetadataStore
from metacompass.graph import all_descendants, build_lineage_graph, neighbors_bfs


@pytest.fixture(scope="module")
def mini_graph(mini_dir) -> nx.DiGraph:
    return build_lineage_graph(MetadataStore.from_dir(mini_dir))


def test_nodes_and_attributes(mini_graph):
    assert mini_graph.number_of_nodes() == 8 + 8 + 3
    assert mini_graph.nodes["TBL-004"] == {
        "type": "table", "name": "int_sales_by_dealer", "layer": "intermediate", "status": None,
    }  # fmt: skip
    assert mini_graph.nodes["RPT-0004"]["status"] == "deprecated"
    assert mini_graph.nodes["MET-003"]["type"] == "metric"


def test_edges_point_downstream(mini_graph):
    assert mini_graph.has_edge("TBL-001", "TBL-003")  # parent -> child
    assert mini_graph.has_edge("TBL-005", "RPT-0001")  # table -> report
    assert mini_graph.has_edge("TBL-006", "MET-002")  # table -> metric
    assert not mini_graph.has_edge("RPT-0001", "TBL-005")


def test_upstream_of_a_report_with_distances(mini_graph):
    assert neighbors_bfs(mini_graph, "RPT-0001", "upstream", depth=6) == [
        ("TBL-005", 1), ("TBL-006", 1),
        ("TBL-003", 2), ("TBL-004", 2),
        ("TBL-001", 3), ("TBL-002", 3),
    ]  # fmt: skip


def test_depth_one_is_direct_neighbours_only(mini_graph):
    assert neighbors_bfs(mini_graph, "RPT-0001", "upstream", depth=1) == [
        ("TBL-005", 1),
        ("TBL-006", 1),
    ]


def test_downstream_of_a_staging_table(mini_graph):
    assert neighbors_bfs(mini_graph, "TBL-001", "downstream", depth=2) == [
        ("TBL-003", 1), ("TBL-007", 1),
        ("MET-003", 2), ("RPT-0003", 2), ("RPT-0008", 2), ("TBL-004", 2), ("TBL-005", 2),
    ]  # fmt: skip


def test_distance_is_the_shortest_path(mini_graph):
    # TBL-005 is two steps from TBL-001 via TBL-003 and three via TBL-004; BFS keeps two.
    distances = dict(neighbors_bfs(mini_graph, "TBL-001", "downstream", depth=6))
    assert distances["TBL-005"] == 2
    assert distances["TBL-006"] == 3
    assert distances["RPT-0004"] == 4


def test_a_report_has_nothing_downstream(mini_graph):
    assert neighbors_bfs(mini_graph, "RPT-0001", "downstream", depth=6) == []


def test_unused_table_has_no_neighbours(mini_graph):
    assert neighbors_bfs(mini_graph, "TBL-008", "downstream", depth=3) == []


def test_all_descendants(mini_graph):
    assert all_descendants(mini_graph, "TBL-004") == {
        "TBL-005", "TBL-006",
        "RPT-0001", "RPT-0002", "RPT-0004", "RPT-0005", "RPT-0006", "RPT-0007",
        "MET-001", "MET-002",
    }  # fmt: skip


@pytest.mark.parametrize("depth", [0, 7, -1])
def test_depth_outside_one_to_six_is_rejected(mini_graph, depth):
    with pytest.raises(ValueError):
        neighbors_bfs(mini_graph, "TBL-001", "downstream", depth=depth)


def test_bad_direction_and_unknown_node(mini_graph):
    with pytest.raises(ValueError):
        neighbors_bfs(mini_graph, "TBL-001", "sideways", depth=1)
    with pytest.raises(KeyError):
        neighbors_bfs(mini_graph, "TBL-999", "downstream", depth=1)
    with pytest.raises(KeyError):
        all_descendants(mini_graph, "TBL-999")


def test_cycle_is_rejected(mini_dir, tmp_path):
    cyclic = tmp_path / "cyclic"
    shutil.copytree(mini_dir, cyclic)
    with open(cyclic / "raw" / "table_table_edges.csv", "a", encoding="utf-8") as handle:
        handle.write("TBL-005,TBL-003,join\n")  # closes 003 -> 005 -> 003
    with pytest.raises(ValueError, match="cycle"):
        build_lineage_graph(MetadataStore.from_dir(cyclic))


def test_every_metric_in_the_real_data_reads_a_mart_table(generated_dir):
    graph = build_lineage_graph(MetadataStore.from_dir(generated_dir))
    metrics = [n for n, attrs in graph.nodes(data=True) if attrs["type"] == "metric"]
    assert len(metrics) == 40
    for metric in metrics:
        upstream = [n for n, _ in neighbors_bfs(graph, metric, "upstream", depth=6)]
        assert any(graph.nodes[n].get("layer") == "mart" for n in upstream), metric
