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
    assert payload["dependency_table"][0]["relationship"] == "depends_on"
    assert payload["critical_dependencies"][0]["dependency_chain"]


def test_report_markdown_is_github_security_report_friendly() -> None:
    report = generate_security_report(shared_dns_topology())

    markdown = report.to_markdown()

    assert markdown.startswith("# ChokePoint Security Report")
    assert "## Executive Summary" in markdown
    assert "## Risk Score" in markdown
    assert "## Critical Dependencies" in markdown
    assert "## Articulation Points" in markdown
    assert "## Bridge Edges" in markdown
    assert "## Recommendations" in markdown
    assert "## Dependency Table" in markdown
    assert "## Blast Radius" in markdown
    assert (
        "| Level | Category | Node | Score | Blast Radius | Explanation |" in markdown
    )


def test_report_html_is_standalone_and_escaped() -> None:
    topology = Topology()
    topology.add_node(
        Node(
            id="cloudflare",
            name="Cloudflare <DNS>",
            provider="cloudflare",
            node_type=NodeType.DNS,
        )
    )
    topology.add_node(
        Node(
            id="frontend",
            name="Frontend",
            provider="aws",
            node_type=NodeType.SERVICE,
        )
    )
    topology.add_node(
        Node(
            id="api",
            name="API",
            provider="azure",
            node_type=NodeType.SERVICE,
        )
    )
    topology.add_edge(
        Edge(
            source="frontend",
            target="cloudflare",
            relationship=Relationship.DEPENDS_ON,
        )
    )
    topology.add_edge(
        Edge(
            source="api",
            target="cloudflare",
            relationship=Relationship.DEPENDS_ON,
        )
    )

    html = generate_security_report(topology).to_html()

    assert html.startswith("<!doctype html>")
    assert "<h2>Executive Summary</h2>" in html
    assert "Cloudflare &lt;DNS&gt;" in html
    assert "<table>" in html
    assert "<h2>Blast Radius</h2>" in html


def test_terminal_report_renders_expected_sections() -> None:
    report = generate_security_report(shared_dns_topology())
    stream = io.StringIO()
    console = Console(file=stream, width=120, force_terminal=False)

    console.print(report.to_terminal())

    output = stream.getvalue()
    assert "ChokePoint Security Report" in output
    assert "Critical Dependencies" in output
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
    html = report.to_html()

    assert report.risk_score == 0
    assert report.recommendations == (SECURITY_REPORT_RECOMMENDATION,)
    assert "No critical dependencies detected." in markdown
    assert "No dependencies declared." in markdown
    assert "None detected." in html


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
