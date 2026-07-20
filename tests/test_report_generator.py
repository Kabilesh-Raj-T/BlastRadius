"""Report generator tests for ChokePoint."""

from __future__ import annotations

import io
import json

from rich.console import Console

from chokepoint.models import Edge, Node, NodeType, Relationship, Topology
from chokepoint.report import GeneratedReport, generate_security_report

EXPECTED_DEPENDENCY_ROWS = 2
EXPECTED_NODE_COUNT = 3
EXPECTED_RISK_SCORE = 98
SECURITY_REPORT_RECOMMENDATION = (
    "No immediate choke-point risks were detected; continue monitoring topology drift."
)


def test_generate_security_report_returns_structured_report() -> None:
    topology = shared_dns_topology()

    report = generate_security_report(topology)

    assert isinstance(report, GeneratedReport)
    assert report.title == "ChokePoint Security Report"
    assert report.risk_score == EXPECTED_RISK_SCORE
    assert report.critical_dependencies
    assert report.dependency_nodes[0].node_id == "aws-api"
    assert report.dependency_graph[0].source == "aws-api"
    assert len(report.single_points_of_failure) == 1
    assert report.single_points_of_failure[0].node_id == "cloudflare"
    assert report.single_points_of_failure[0].category == "dns, cdn"
    assert report.single_points_of_failure[0].confidence.value == "high"
    assert "shared DNS and CDN dependency" in (
        report.single_points_of_failure[0].why_it_matters
    )
    assert report.articulation_points == ("cloudflare",)
    assert report.bridge_edges
    assert len(report.dependency_table) == EXPECTED_DEPENDENCY_ROWS
    assert report.blast_radius["cloudflare"] == EXPECTED_DEPENDENCY_ROWS


def test_report_json_contains_nested_security_context() -> None:
    report = generate_security_report(shared_dns_topology())

    payload = json.loads(report.to_json())

    assert payload["executive_summary"].startswith("ChokePoint analyzed")
    assert payload["risk_report"]["finding_count"] >= 1
    assert payload["graph_report"]["node_count"] == EXPECTED_NODE_COUNT
    assert payload["dependency_nodes"][0]["node_id"] == "aws-api"
    assert payload["dependency_graph"][0]["target"] == "cloudflare"
    assert payload["single_points_of_failure"][0]["why_it_matters"]
    assert payload["single_points_of_failure"][0]["confidence"] == "high"
    assert payload["single_points_of_failure"][0]["confidence_reason"]
    assert payload["dependency_table"][0]["relationship"] == "depends_on"
    assert payload["critical_dependencies"][0]["dependency_chain"]
    assert payload["critical_dependencies"][0]["confidence"] == "high"


def test_report_markdown_is_github_security_report_friendly() -> None:
    report = generate_security_report(shared_dns_topology())

    markdown = report.to_markdown()

    assert markdown.startswith("# ChokePoint Security Report")
    assert "## Executive Summary" in markdown
    assert "## Risk Score" in markdown
    assert "## Dependency Graph" in markdown
    assert "```mermaid" in markdown
    assert "SPOF: critical DNS" in markdown
    assert "## Hidden Single Points of Failure" in markdown
    assert "Confidence: `high`" in markdown
    assert "Why it matters:" in markdown
    assert "## Critical Dependencies" in markdown
    assert "## Articulation Points" in markdown
    assert "## Bridge Edges" in markdown
    assert "## Recommendations" in markdown
    assert "## Dependency Table" in markdown
    assert "## Blast Radius" in markdown
    assert (
        "| Level | Category | Node | Score | Blast Radius | Confidence | Explanation |"
        in markdown
    )


def test_report_markdown_dependency_graph_includes_isolated_nodes() -> None:
    topology = shared_dns_topology()
    topology.add_node(
        Node(
            id="unused-region",
            name="Unused Region",
            provider="aws",
            node_type=NodeType.EXTERNAL,
        )
    )

    markdown = generate_security_report(topology).to_markdown()

    assert 'n_unused_region["Unused Region"]' in markdown


def test_terminal_report_renders_expected_sections() -> None:
    report = generate_security_report(shared_dns_topology())
    stream = io.StringIO()
    console = Console(file=stream, width=120, force_terminal=False)

    console.print(report.to_terminal())

    output = stream.getvalue()
    assert "ChokePoint Security Report" in output
    assert "Critical Dependencies" in output
    assert "Dependency Graph" in output
    assert "Hidden Single Points of Failure" in output
    assert "Confidence" in output
    assert "Graph Choke Points" in output
    assert "Recommendations" in output
    assert "Dependency Table" in output


def test_report_empty_states_are_explicit() -> None:
    topology = Topology()
    topology.add_node(
        Node(
            id="frontend",
            name="Frontend",
            provider="aws",
            node_type=NodeType.SERVICE,
        )
    )

    report = generate_security_report(topology)
    markdown = report.to_markdown()
    stream = io.StringIO()
    console = Console(file=stream, width=120, force_terminal=False)

    console.print(report.to_terminal())
    terminal = stream.getvalue()

    assert report.risk_score == 0
    assert report.recommendations == (SECURITY_REPORT_RECOMMENDATION,)
    assert report.single_points_of_failure == ()
    assert "No critical dependencies detected." in markdown
    assert "No hidden single points of failure detected." in markdown
    assert "No dependencies declared." in markdown
    assert "No dependencies declared" in terminal
    assert "No single points detected" in terminal


def test_structural_single_point_explains_articulation_without_risk_rule() -> None:
    topology = Topology()
    topology.add_node(
        Node(
            id="public-service",
            name="Public Service",
            provider="kubernetes",
            node_type=NodeType.LOAD_BALANCER,
        )
    )
    topology.add_node(
        Node(
            id="internal-service",
            name="Internal Service",
            provider="kubernetes",
            node_type=NodeType.LOAD_BALANCER,
        )
    )
    topology.add_node(
        Node(
            id="statefulset",
            name="CockroachDB StatefulSet",
            provider="kubernetes",
            node_type=NodeType.SERVICE,
        )
    )
    topology.add_edge(
        Edge(
            source="public-service",
            target="statefulset",
            relationship=Relationship.ROUTES_TO,
        )
    )
    topology.add_edge(
        Edge(
            source="internal-service",
            target="statefulset",
            relationship=Relationship.ROUTES_TO,
        )
    )

    report = generate_security_report(topology)

    assert report.risk_score == 0
    assert report.single_points_of_failure[0].node_id == "statefulset"
    assert report.single_points_of_failure[0].severity is None
    assert report.single_points_of_failure[0].confidence.value == "low"
    assert "structural cut point" in report.single_points_of_failure[0].why_it_matters


def test_structural_single_point_confidence_uses_explicit_dependencies() -> None:
    topology = Topology()
    topology.add_node(
        Node(
            id="api",
            name="API",
            provider="application",
            node_type=NodeType.SERVICE,
        )
    )
    for service_id in ("frontend", "worker"):
        topology.add_node(
            Node(
                id=service_id,
                name=service_id,
                provider="application",
                node_type=NodeType.SERVICE,
            )
        )
        topology.add_edge(
            Edge(
                source=service_id,
                target="api",
                relationship=Relationship.DEPENDS_ON,
            )
        )

    report = generate_security_report(topology)

    point = report.single_points_of_failure[0]
    assert point.node_id == "api"
    assert point.confidence.value == "medium"
    assert "multiple explicit depends_on edges" in point.confidence_reason


def shared_dns_topology() -> Topology:
    topology = Topology()
    topology.add_node(
        Node(
            id="cloudflare",
            name="Cloudflare",
            provider="cloudflare",
            node_type=NodeType.DNS,
        )
    )
    topology.add_node(
        Node(
            id="aws-api",
            name="AWS API",
            provider="aws",
            node_type=NodeType.SERVICE,
        )
    )
    topology.add_node(
        Node(
            id="azure-api",
            name="Azure API",
            provider="azure",
            node_type=NodeType.SERVICE,
        )
    )
    topology.add_edge(
        Edge(
            source="aws-api",
            target="cloudflare",
            relationship=Relationship.DEPENDS_ON,
        )
    )
    topology.add_edge(
        Edge(
            source="azure-api",
            target="cloudflare",
            relationship=Relationship.DEPENDS_ON,
        )
    )
    return topology
