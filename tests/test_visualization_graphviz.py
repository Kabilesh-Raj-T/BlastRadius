"""Unit tests for Graphviz visualization."""

from pathlib import Path

import pytest

from chokepoint.models import Edge, Node, NodeType, Relationship, Topology
from chokepoint.visualization import (
    GraphvizArtifact,
    GraphvizRenderError,
    GraphvizVisualizer,
    VisualizationFormat,
    VisualizationLayout,
)

LARGE_GRAPH_NODE_COUNT = 60


def make_node(
    node_id: str,
    *,
    provider: str,
    node_type: NodeType,
    name: str | None = None,
) -> Node:
    return Node(
        id=node_id,
        name=name or node_id,
        provider=provider,
        node_type=node_type,
    )


def make_visual_topology() -> Topology:
    topology = Topology()
    topology.add_node(
        make_node("aws", provider="aws", node_type=NodeType.EXTERNAL, name="AWS")
    )
    topology.add_node(
        make_node(
            "frontend",
            provider="internal",
            node_type=NodeType.SERVICE,
            name="Frontend",
        )
    )
    topology.add_node(
        make_node(
            "api",
            provider="internal",
            node_type=NodeType.SERVICE,
            name="API",
        )
    )
    topology.add_node(
        make_node(
            "database",
            provider="aws",
            node_type=NodeType.DATABASE,
            name="Database",
        )
    )
    topology.add_edge(
        Edge(source="frontend", target="api", relationship=Relationship.DEPENDS_ON)
    )
    topology.add_edge(
        Edge(source="api", target="database", relationship=Relationship.DEPENDS_ON)
    )
    topology.add_edge(
        Edge(source="database", target="aws", relationship=Relationship.DEPENDS_ON)
    )
    return topology


def test_export_dot_contains_nodes_edges_and_legend() -> None:
    dot = GraphvizVisualizer().export_dot(make_visual_topology())

    assert dot.startswith("graph ChokePoint")
    assert "ChokePoint Infrastructure Dependency Graph" in dot
    assert '"frontend" -- "api"' in dot
    assert "Legend" in dot
    assert "Articulation Points" in dot
    assert "Bridges" in dot
    assert "Cloud Providers" in dot
    assert "Applications" in dot
    assert "Infrastructure" in dot


def test_dot_colors_articulation_points_and_bridges() -> None:
    dot = GraphvizVisualizer().export_dot(make_visual_topology())

    assert 'fillcolor="#d62728"' in dot
    assert 'color="#ff7f0e"' in dot
    assert 'penwidth="2.5"' in dot


def test_dot_colors_cloud_applications_and_infrastructure() -> None:
    dot = GraphvizVisualizer().export_dot(make_visual_topology())

    assert '"aws"' in dot
    assert 'fillcolor="#1f77b4"' in dot
    assert 'fillcolor="#2ca02c"' in dot
    assert 'fillcolor="#7f7f7f"' in dot


def test_cluster_layout_groups_nodes_by_provider() -> None:
    dot = GraphvizVisualizer().export_dot(
        make_visual_topology(),
        layout=VisualizationLayout.CLUSTER,
    )

    assert 'subgraph "cluster_aws"' in dot
    assert 'subgraph "cluster_internal"' in dot
    assert 'clusterrank="local"' in dot


def test_radial_layout_uses_twopi_graph_attributes() -> None:
    dot = GraphvizVisualizer().export_dot(
        make_visual_topology(),
        layout=VisualizationLayout.RADIAL,
    )

    assert 'layout="twopi"' in dot
    assert 'rankdir="TB"' in dot


def test_large_graph_dot_generation_is_deterministic() -> None:
    topology = Topology()
    previous = ""
    for index in range(LARGE_GRAPH_NODE_COUNT):
        node_id = f"service-{index:02d}"
        topology.add_node(
            make_node(node_id, provider="internal", node_type=NodeType.SERVICE)
        )
        if previous:
            topology.add_edge(
                Edge(
                    source=previous,
                    target=node_id,
                    relationship=Relationship.DEPENDS_ON,
                )
            )
        previous = node_id

    visualizer = GraphvizVisualizer()
    first = visualizer.export_dot(topology)
    second = visualizer.export_dot(topology)

    assert first == second
    assert first.count("service-") > LARGE_GRAPH_NODE_COUNT
    assert 'overlap="false"' in first
    assert 'concentrate="true"' in first


def test_write_dot_file(tmp_path: Path) -> None:
    path = tmp_path / "topology.dot"

    written = GraphvizVisualizer().write(make_visual_topology(), path)

    assert written == path
    assert path.read_text(encoding="utf-8").startswith("graph ChokePoint")


def test_write_rejects_unknown_suffix(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported visualization file suffix"):
        GraphvizVisualizer().write(make_visual_topology(), tmp_path / "topology.txt")


def test_render_svg_reports_missing_graphviz_executable() -> None:
    visualizer = GraphvizVisualizer(dot_executable="missing-chokepoint-dot")

    with pytest.raises(GraphvizRenderError, match="was not found"):
        visualizer.render_svg(make_visual_topology())


def test_graphviz_artifact_text_decodes_svg_payload() -> None:
    artifact = GraphvizArtifact(
        format=VisualizationFormat.SVG,
        content=b"<svg></svg>",
    )

    assert artifact.text == "<svg></svg>"


def test_visualization_format_values() -> None:
    assert VisualizationFormat.DOT.value == "dot"
    assert VisualizationFormat.SVG.value == "svg"
    assert VisualizationFormat.PNG.value == "png"
