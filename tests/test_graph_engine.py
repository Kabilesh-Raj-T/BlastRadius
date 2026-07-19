"""Unit tests for the ChokePoint graph engine."""

import networkx as nx
import pytest

from chokepoint.graph import GraphAnalyzer, GraphBuilder
from chokepoint.models import Edge, Node, NodeType, Relationship, Topology


def node(node_id: str, node_type: NodeType = NodeType.SERVICE) -> Node:
    return Node(
        id=node_id,
        name=node_id.upper(),
        provider="test",
        node_type=node_type,
    )


def topology_from_edges(
    node_ids: tuple[str, ...],
    edge_ids: tuple[tuple[str, str], ...],
) -> Topology:
    topology = Topology()
    for node_id in node_ids:
        topology.add_node(node(node_id))
    for source, target in edge_ids:
        topology.add_edge(
            Edge(
                source=source,
                target=target,
                relationship=Relationship.DEPENDS_ON,
            )
        )
    return topology


def test_builder_converts_topology_to_networkx_graph_with_attributes() -> None:
    topology = topology_from_edges(("api", "db"), (("api", "db"),))

    graph = GraphBuilder().build(topology)

    assert isinstance(graph, nx.Graph)
    assert not graph.is_directed()
    assert graph.number_of_nodes() == len(topology.nodes)
    assert graph.number_of_edges() == 1
    assert graph.nodes["api"]["node"] == topology.nodes["api"]
    assert graph.nodes["api"]["node_type"] is NodeType.SERVICE
    assert graph.edges["api", "db"]["topology_edges"] == (topology.edges[0],)
    assert graph.edges["api", "db"]["relationships"] == (Relationship.DEPENDS_ON,)


def test_builder_collapses_parallel_edges() -> None:
    topology = Topology()
    topology.add_node(node("api"))
    topology.add_node(node("db", NodeType.DATABASE))
    topology.add_edge(
        Edge(source="api", target="db", relationship=Relationship.READS_FROM)
    )
    topology.add_edge(
        Edge(source="db", target="api", relationship=Relationship.WRITES_TO)
    )

    graph = GraphBuilder().build(topology)

    assert graph.number_of_edges() == 1
    assert graph.edges["api", "db"]["topology_edges"] == tuple(topology.edges)
    assert graph.edges["api", "db"]["relationships"] == (
        Relationship.READS_FROM,
        Relationship.WRITES_TO,
    )


def test_analyzer_finds_choke_points_and_bridges_in_path_graph() -> None:
    topology = topology_from_edges(
        ("a", "b", "c", "d"),
        (("a", "b"), ("b", "c"), ("c", "d")),
    )
    report = GraphAnalyzer().analyze(GraphBuilder().build(topology))

    assert report.is_connected is True
    assert report.connected_components == (("a", "b", "c", "d"),)
    assert report.articulation_points == ("b", "c")
    assert report.bridges == (("a", "b"), ("b", "c"), ("c", "d"))
    assert report.cycles == ()
    assert report.degree_centrality == {
        "a": pytest.approx(1 / 3),
        "b": pytest.approx(2 / 3),
        "c": pytest.approx(2 / 3),
        "d": pytest.approx(1 / 3),
    }
    assert report.betweenness_centrality["b"] == pytest.approx(2 / 3)
    assert report.betweenness_centrality["c"] == pytest.approx(2 / 3)


def test_analyzer_detects_cycle_graph_without_bridges() -> None:
    topology = topology_from_edges(
        ("a", "b", "c", "d"),
        (("a", "b"), ("b", "c"), ("c", "d"), ("d", "a")),
    )
    report = GraphAnalyzer().analyze(GraphBuilder().build(topology))

    assert report.is_connected is True
    assert report.articulation_points == ()
    assert report.bridges == ()
    assert report.cycles == (("a", "b", "c", "d"),)


def test_analyzer_reports_disconnected_components() -> None:
    topology = topology_from_edges(
        ("a", "b", "c", "d", "e"),
        (("a", "b"), ("b", "c"), ("d", "e")),
    )
    report = GraphAnalyzer().analyze(GraphBuilder().build(topology))

    assert report.is_connected is False
    assert report.connected_components == (("a", "b", "c"), ("d", "e"))
    assert report.articulation_points == ("b",)
    assert report.bridges == (("a", "b"), ("b", "c"), ("d", "e"))


def test_analyzer_handles_empty_graph() -> None:
    report = GraphAnalyzer().analyze(GraphBuilder().build(Topology()))

    assert report.node_count == 0
    assert report.edge_count == 0
    assert report.is_connected is False
    assert report.connected_components == ()
    assert report.articulation_points == ()
    assert report.bridges == ()
    assert report.betweenness_centrality == {}
    assert report.degree_centrality == {}
    assert report.cycles == ()


def test_validate_reports_invalid_graph_shape() -> None:
    graph = nx.DiGraph()
    graph.add_node("api")
    graph.add_edge("api", "db")

    validation = GraphAnalyzer().validate(graph)

    assert validation.is_valid is False
    assert "graph must be undirected" in validation.issues
    assert "node 'api' is missing a Node model" in validation.issues
    assert "edge 'api'-'db' is missing Edge models" in validation.issues


def test_analyze_rejects_invalid_graph() -> None:
    graph = nx.Graph()
    graph.add_node("api")

    with pytest.raises(ValueError, match="invalid ChokePoint graph"):
        GraphAnalyzer().analyze(graph)


def test_validate_detects_mismatched_preserved_edge_attributes() -> None:
    graph = nx.Graph()
    graph.add_node("api", node=node("api"))
    graph.add_node("db", node=node("db"))
    graph.add_edge(
        "api",
        "db",
        topology_edges=(
            Edge(source="api", target="cache", relationship=Relationship.DEPENDS_ON),
        ),
        relationships=(Relationship.READS_FROM,),
    )

    validation = GraphAnalyzer().validate(graph)

    assert validation.is_valid is False
    assert "edge 'api'-'db' contains mismatched topology edge" in validation.issues
    assert "edge 'api'-'db' has inconsistent relationships" in validation.issues


def test_validate_detects_missing_edge_metadata() -> None:
    graph = nx.Graph()
    graph.add_node("api", node=node("api"))
    graph.add_node("db", node=node("db"))
    graph.add_edge(
        "api",
        "db",
        topology_edges=(
            Edge(source="api", target="db", relationship=Relationship.DEPENDS_ON),
        ),
        relationships=(Relationship.DEPENDS_ON,),
    )

    validation = GraphAnalyzer().validate(graph)

    assert validation.is_valid is False
    assert "edge 'api'-'db' is missing edge metadata" in validation.issues


def test_validate_detects_node_model_shape_issues() -> None:
    graph = nx.Graph()
    graph.add_node("", node=node("api"))
    graph.add_node("db", node=node("other"))

    validation = GraphAnalyzer().validate(graph)

    assert validation.is_valid is False
    assert "node id must be a non-empty string" in validation.issues[0]
    assert "node 'db' has mismatched Node model id 'other'" in validation.issues


def test_validate_detects_self_loop_and_relationship_shape_issues() -> None:
    graph = nx.Graph()
    graph.add_node("api", node=node("api"))
    graph.add_edge(
        "api",
        "api",
        topology_edges=(
            Edge(source="api", target="api", relationship=Relationship.DEPENDS_ON),
        ),
        relationships=("depends_on",),
        edge_metadata=({},),
    )

    validation = GraphAnalyzer().validate(graph)

    assert validation.is_valid is False
    assert "self-loop edge is not supported: 'api'" in validation.issues
    assert "edge 'api'-'api' is missing relationships" in validation.issues


def test_validate_detects_edge_attribute_length_mismatches() -> None:
    graph = nx.Graph()
    graph.add_node("api", node=node("api"))
    graph.add_node("db", node=node("db"))
    graph.add_edge(
        "api",
        "db",
        topology_edges=(
            Edge(source="api", target="db", relationship=Relationship.DEPENDS_ON),
            Edge(source="db", target="api", relationship=Relationship.READS_FROM),
        ),
        relationships=(Relationship.DEPENDS_ON,),
        edge_metadata=({},),
    )

    validation = GraphAnalyzer().validate(graph)

    assert validation.is_valid is False
    assert "edge 'api'-'db' has mismatched edge attributes" in validation.issues
    assert "edge 'api'-'db' has mismatched edge metadata" in validation.issues


def test_complexity_profile_documents_expected_algorithms() -> None:
    profile = GraphAnalyzer().complexity_profile()

    assert {entry.algorithm for entry in profile} == {
        "graph_build",
        "graph_validation",
        "connected_components",
        "articulation_points",
        "bridges",
        "betweenness_centrality",
        "degree_centrality",
        "cycle_detection",
    }
    assert all(entry.time_complexity.startswith("O(") for entry in profile)
    assert all(entry.space_complexity.startswith("O(") for entry in profile)
