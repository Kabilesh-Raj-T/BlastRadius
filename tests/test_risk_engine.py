"""Unit tests for the ChokePoint risk analysis engine."""

import json

from chokepoint.graph import GraphBuilder
from chokepoint.models import Edge, Node, NodeType, Relationship, Topology
from chokepoint.report import RiskAnalyzer, RiskCategory, RiskLevel, RiskReport

SHARED_BLAST_RADIUS = 2
TRANSITIVE_BLAST_RADIUS = 3
CRITICAL_SCORE_FLOOR = 90


def node(
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


def topology_with_shared_dependency(
    dependency: Node,
    *,
    first_provider: str = "aws",
    second_provider: str = "azure",
) -> Topology:
    topology = Topology()
    topology.add_node(
        node(
            "aws-service",
            provider=first_provider,
            node_type=NodeType.SERVICE,
            name="AWS service",
        )
    )
    topology.add_node(
        node(
            "azure-service",
            provider=second_provider,
            node_type=NodeType.SERVICE,
            name="Azure service",
        )
    )
    topology.add_node(dependency)
    topology.add_edge(
        Edge(
            source="aws-service",
            target=dependency.id,
            relationship=Relationship.DEPENDS_ON,
        )
    )
    topology.add_edge(
        Edge(
            source="azure-service",
            target=dependency.id,
            relationship=Relationship.DEPENDS_ON,
        )
    )
    return topology


def finding_by_category(
    report: RiskReport,
    category: RiskCategory,
):
    return next(finding for finding in report.findings if finding.category is category)


def first_finding(topology: Topology) -> tuple[RiskReport, object]:
    report = RiskAnalyzer().analyze(topology)
    return report, report.findings[0]


def test_critical_shared_dns_report_contains_blast_radius_and_explanation() -> None:
    topology = topology_with_shared_dependency(
        node(
            "cloudflare",
            provider="cloudflare",
            node_type=NodeType.DNS,
            name="Cloudflare DNS",
        )
    )

    report = RiskAnalyzer().analyze(topology)
    finding = finding_by_category(report, RiskCategory.DNS)

    assert report.risk_score == finding.risk_score
    assert report.finding_count == SHARED_BLAST_RADIUS
    assert finding.category is RiskCategory.DNS
    assert finding.risk_level is RiskLevel.CRITICAL
    assert finding.criticality is RiskLevel.CRITICAL
    assert finding.risk_score >= CRITICAL_SCORE_FLOOR
    assert finding.blast_radius == SHARED_BLAST_RADIUS
    assert finding.impacted_nodes == ("aws-service", "azure-service")
    assert finding.impacted_providers == ("aws", "azure")
    assert "Cloudflare DNS" in finding.explanation
    assert "AWS and AZURE" in finding.explanation


def test_shared_identity_and_secrets_manager_are_critical() -> None:
    topology = Topology()
    topology.add_node(node("api", provider="aws", node_type=NodeType.SERVICE))
    topology.add_node(node("worker", provider="azure", node_type=NodeType.SERVICE))
    topology.add_node(node("okta", provider="okta", node_type=NodeType.IDENTITY))
    topology.add_node(
        node("vault", provider="hashicorp", node_type=NodeType.SECRET, name="Vault")
    )
    for dependency in ("okta", "vault"):
        topology.add_edge(
            Edge(
                source="api",
                target=dependency,
                relationship=Relationship.DEPENDS_ON,
            )
        )
        topology.add_edge(
            Edge(
                source="worker",
                target=dependency,
                relationship=Relationship.DEPENDS_ON,
            )
        )

    report = RiskAnalyzer().analyze(topology)
    categories = {finding.category for finding in report.findings}

    assert RiskCategory.IDENTITY in categories
    assert RiskCategory.SECRETS_MANAGER in categories
    assert all(
        finding.risk_level is RiskLevel.CRITICAL
        for finding in report.findings
        if finding.category in {RiskCategory.IDENTITY, RiskCategory.SECRETS_MANAGER}
    )


def test_shared_cdn_is_critical() -> None:
    topology = topology_with_shared_dependency(
        node(
            "cloudfront",
            provider="aws",
            node_type=NodeType.EXTERNAL,
            name="CloudFront CDN",
        )
    )

    report = RiskAnalyzer().analyze(topology)

    assert report.findings[0].category is RiskCategory.CDN
    assert report.findings[0].risk_level is RiskLevel.CRITICAL


def test_shared_monitoring_and_networking_are_high_risk() -> None:
    topology = Topology()
    for service_id, provider in (("api", "aws"), ("worker", "azure")):
        topology.add_node(
            node(service_id, provider=provider, node_type=NodeType.SERVICE)
        )
    topology.add_node(
        node(
            "datadog",
            provider="datadog",
            node_type=NodeType.EXTERNAL,
            name="Datadog Monitoring",
        )
    )
    topology.add_node(node("shared-vpc", provider="aws", node_type=NodeType.NETWORK))
    for dependency in ("datadog", "shared-vpc"):
        for source in ("api", "worker"):
            topology.add_edge(
                Edge(
                    source=source,
                    target=dependency,
                    relationship=Relationship.DEPENDS_ON,
                )
            )

    report = RiskAnalyzer().analyze(topology)
    levels = {finding.category: finding.risk_level for finding in report.findings}

    assert levels[RiskCategory.MONITORING] is RiskLevel.HIGH
    assert levels[RiskCategory.NETWORKING] is RiskLevel.HIGH


def test_shared_ci_cd_and_email_are_medium_risk() -> None:
    topology = Topology()
    for service_id, provider in (("api", "aws"), ("worker", "azure")):
        topology.add_node(
            node(service_id, provider=provider, node_type=NodeType.SERVICE)
        )
    topology.add_node(
        node(
            "github-actions",
            provider="github",
            node_type=NodeType.EXTERNAL,
            name="GitHub Actions CI/CD",
        )
    )
    topology.add_node(
        node(
            "sendgrid",
            provider="sendgrid",
            node_type=NodeType.EXTERNAL,
            name="SendGrid Email",
        )
    )
    for dependency in ("github-actions", "sendgrid"):
        for source in ("api", "worker"):
            topology.add_edge(
                Edge(
                    source=source,
                    target=dependency,
                    relationship=Relationship.DEPENDS_ON,
                )
            )

    report = RiskAnalyzer().analyze(topology)
    levels = {finding.category: finding.risk_level for finding in report.findings}

    assert levels[RiskCategory.CI_CD] is RiskLevel.MEDIUM
    assert levels[RiskCategory.EMAIL] is RiskLevel.MEDIUM


def test_low_single_service_articulation_is_reported() -> None:
    topology = Topology()
    topology.add_node(node("frontend", provider="aws", node_type=NodeType.SERVICE))
    topology.add_node(node("adapter", provider="aws", node_type=NodeType.EXTERNAL))
    topology.add_node(node("legacy", provider="aws", node_type=NodeType.EXTERNAL))
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
            target="legacy",
            relationship=Relationship.DEPENDS_ON,
        )
    )

    report = RiskAnalyzer().analyze(topology)

    assert report.findings[0].category is RiskCategory.SINGLE_SERVICE_ARTICULATION
    assert report.findings[0].risk_level is RiskLevel.LOW
    assert report.findings[0].blast_radius == 1
    assert report.findings[0].impacted_nodes == ("frontend",)
    assert report.findings[0].dependency_chain[0].path == ("frontend", "adapter")


def test_dependency_chain_tracks_transitive_dependency_path() -> None:
    topology = Topology()
    topology.add_node(node("frontend", provider="aws", node_type=NodeType.SERVICE))
    topology.add_node(node("api", provider="aws", node_type=NodeType.SERVICE))
    topology.add_node(node("cloudflare", provider="cloudflare", node_type=NodeType.DNS))
    topology.add_node(node("worker", provider="azure", node_type=NodeType.SERVICE))
    topology.add_edge(
        Edge(source="frontend", target="api", relationship=Relationship.DEPENDS_ON)
    )
    topology.add_edge(
        Edge(source="api", target="cloudflare", relationship=Relationship.DEPENDS_ON)
    )
    topology.add_edge(
        Edge(source="worker", target="cloudflare", relationship=Relationship.DEPENDS_ON)
    )

    report = RiskAnalyzer().analyze(topology)
    dns_finding = next(
        finding for finding in report.findings if finding.category is RiskCategory.DNS
    )

    assert dns_finding.blast_radius == TRANSITIVE_BLAST_RADIUS
    assert ("frontend", "api", "cloudflare") in {
        chain.path for chain in dns_finding.dependency_chain
    }


def test_analyze_graph_accepts_networkx_graph_input() -> None:
    topology = topology_with_shared_dependency(
        node("route53", provider="aws", node_type=NodeType.DNS, name="Route53")
    )
    graph = GraphBuilder().build(topology)

    report = RiskAnalyzer().analyze_graph(graph)

    assert report.finding_count >= 1
    assert report.findings[0].category is RiskCategory.DNS


def test_report_exports_structured_json() -> None:
    topology = topology_with_shared_dependency(
        node("route53", provider="aws", node_type=NodeType.DNS, name="Route53")
    )

    exported = RiskAnalyzer().analyze(topology).export_json()
    payload = json.loads(exported)

    assert payload["finding_count"] >= 1
    assert payload["findings"][0]["risk_level"] == "critical"
    assert "dependency_chain" in payload["findings"][0]


def test_no_findings_returns_zero_score() -> None:
    topology = Topology()
    topology.add_node(node("standalone", provider="aws", node_type=NodeType.SERVICE))

    report = RiskAnalyzer().analyze(topology)

    assert report.risk_score == 0
    assert report.finding_count == 0
    assert report.findings == ()
