"""Advanced capability tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from chokepoint.graph import diff_topologies
from chokepoint.models import Edge, Node, NodeType, Relationship, Topology
from chokepoint.report import (
    RiskHistoryStore,
    export_csv,
    export_mermaid,
    export_openapi,
    export_risk_history_json,
    export_sarif,
    generate_security_report,
    load_risk_history,
)
from chokepoint.utils import PluginRegistry
from chokepoint.visualization import render_interactive_html

EXPECTED_HISTORY_SNAPSHOTS = 2


def test_topology_diff_detects_added_removed_and_changed_entities() -> None:
    before = basic_topology()
    after = basic_topology()
    after.nodes["api"] = Node(
        id="api",
        name="api-v2",
        provider="aws",
        node_type=NodeType.SERVICE,
    )
    after.add_node(
        Node(id="identity", name="Okta", provider="okta", node_type=NodeType.IDENTITY)
    )
    after.add_edge(
        Edge(
            source="api",
            target="identity",
            relationship=Relationship.AUTHENTICATES_WITH,
        )
    )

    diff = diff_topologies(before, after)

    assert diff.has_changes
    assert diff.changed_nodes[0][0].name == "api"
    assert diff.changed_nodes[0][1].name == "api-v2"
    assert [node.id for node in diff.added_nodes] == ["identity"]
    assert [edge.target for edge in diff.added_edges] == ["identity"]


def test_exporters_emit_sarif_openapi_csv_and_mermaid() -> None:
    topology = shared_dns_topology()
    report = generate_security_report(topology)

    sarif = json.loads(export_sarif(report))
    openapi = json.loads(export_openapi())
    csv_payload = export_csv(topology)
    mermaid = export_mermaid(topology)

    assert sarif["version"] == "2.1.0"
    assert sarif["runs"][0]["results"]
    assert openapi["openapi"] == "3.1.0"
    assert "source,target,relationship" in csv_payload
    assert "flowchart LR" in mermaid
    assert "api -->|depends_on| dns" not in mermaid
    assert "n_api -->|depends_on| n_dns" in mermaid


def test_sarif_export_maps_medium_and_low_findings() -> None:
    medium_report = generate_security_report(shared_email_topology())
    low_report = generate_security_report(single_service_articulation_topology())

    medium_sarif = json.loads(export_sarif(medium_report))
    low_sarif = json.loads(export_sarif(low_report))

    assert medium_sarif["runs"][0]["results"][0]["level"] == "warning"
    assert low_sarif["runs"][0]["results"][0]["level"] == "note"


def test_risk_history_tracks_snapshots_and_trend(tmp_path: Path) -> None:
    path = tmp_path / "risk.ndjson"
    store = RiskHistoryStore(path)
    low_report = generate_security_report(basic_topology()).risk_report
    high_report = generate_security_report(shared_dns_topology()).risk_report

    store.append(
        low_report,
        label="main",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )
    store.append(
        high_report,
        label="main",
        timestamp=datetime(2026, 1, 2, tzinfo=UTC),
    )

    trend = store.trend()
    exported = json.loads(export_risk_history_json(path))

    assert trend.snapshot_count == EXPECTED_HISTORY_SNAPSHOTS
    assert trend.direction == "worse"
    assert exported[0]["label"] == "main"


def test_risk_history_empty_and_improving_trends(tmp_path: Path) -> None:
    path = tmp_path / "risk.ndjson"
    store = RiskHistoryStore(path)

    assert load_risk_history(path) == ()
    assert store.trend().direction == "flat"

    high_report = generate_security_report(shared_dns_topology()).risk_report
    low_report = generate_security_report(basic_topology()).risk_report
    store.append(high_report)
    store.append(low_report)

    assert store.trend().direction == "better"


def test_plugin_registry_applies_plugins_in_name_order() -> None:
    registry = PluginRegistry(
        (
            AddNodePlugin("b-plugin", "b"),
            AddNodePlugin("a-plugin", "a"),
        )
    )

    topology = registry.apply(Topology())

    assert registry.names() == ("a-plugin", "b-plugin")
    assert tuple(topology.nodes) == ("a", "b")


def test_plugin_registry_rejects_invalid_plugins() -> None:
    registry = PluginRegistry()

    try:
        registry.register(AddNodePlugin("", "node"))
    except ValueError as error:
        assert "plugin name" in str(error)
    else:
        raise AssertionError("expected ValueError")

    registry.register(AddNodePlugin("plugin", "node"))
    try:
        registry.register(AddNodePlugin("plugin", "other"))
    except ValueError as error:
        assert "already registered" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_interactive_html_graph_supports_search_and_filtering() -> None:
    html = render_interactive_html(shared_dns_topology())

    assert html.startswith("<!doctype html>")
    assert "Search graph" in html
    assert "Filter provider" in html
    assert "graph-data" in html
    assert "cloudflare" in html


def test_interactive_html_graph_safely_embeds_topology_values() -> None:
    topology = Topology()
    topology.add_node(
        Node(
            id="api<script>",
            name='API </script><img src=x onerror="alert(1)">',
            provider="aws&edge",
            node_type=NodeType.SERVICE,
        )
    )

    html = render_interactive_html(topology)

    assert "</script><img" not in html
    assert "\\u003c/script\\u003e" in html
    assert "\\u0026" in html
    assert "textContent = node.id" in html


@dataclass(frozen=True)
class AddNodePlugin:
    """Test plugin that adds one node."""

    name: str
    node_id: str

    def transform(self, topology: Topology) -> Topology:
        """Add this plugin's node to the topology."""
        topology.add_node(
            Node(
                id=self.node_id,
                name=self.node_id,
                provider="plugin",
                node_type=NodeType.EXTERNAL,
            )
        )
        return topology


def basic_topology() -> Topology:
    topology = Topology()
    topology.add_node(
        Node(id="api", name="api", provider="aws", node_type=NodeType.SERVICE)
    )
    topology.add_node(
        Node(id="dns", name="dns", provider="cloudflare", node_type=NodeType.DNS)
    )
    topology.add_edge(
        Edge(source="api", target="dns", relationship=Relationship.DEPENDS_ON)
    )
    return topology


def shared_dns_topology() -> Topology:
    topology = basic_topology()
    topology.add_node(
        Node(
            id="worker",
            name="worker",
            provider="azure",
            node_type=NodeType.SERVICE,
        )
    )
    topology.add_edge(
        Edge(source="worker", target="dns", relationship=Relationship.DEPENDS_ON)
    )
    return topology


def shared_email_topology() -> Topology:
    topology = Topology()
    topology.add_node(
        Node(
            id="sendgrid",
            name="SendGrid",
            provider="sendgrid",
            node_type=NodeType.EXTERNAL,
            metadata={"category": "email"},
        )
    )
    for node_id in ("api", "worker"):
        topology.add_node(
            Node(
                id=node_id,
                name=node_id,
                provider="aws",
                node_type=NodeType.SERVICE,
            )
        )
        topology.add_edge(
            Edge(
                source=node_id,
                target="sendgrid",
                relationship=Relationship.DEPENDS_ON,
            )
        )
    return topology


def single_service_articulation_topology() -> Topology:
    topology = Topology()
    for node_id in ("frontend", "adapter", "database"):
        topology.add_node(
            Node(
                id=node_id,
                name=node_id,
                provider="internal",
                node_type=(
                    NodeType.DATABASE if node_id == "database" else NodeType.SERVICE
                ),
            )
        )
    topology.add_edge(
        Edge(
            source="frontend",
            target="adapter",
            relationship=Relationship.DEPENDS_ON,
        )
    )
    topology.add_edge(
        Edge(
            source="adapter",
            target="database",
            relationship=Relationship.DEPENDS_ON,
        )
    )
    return topology
