"""Risk analysis engine for ChokePoint topologies."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import ClassVar

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field

from chokepoint.graph import GraphAnalyzer, GraphBuilder
from chokepoint.models import Edge, Node, NodeType, Relationship, Topology

MIN_SHARED_DEPENDENTS = 2
HUMAN_JOIN_PAIR_COUNT = 2


class RiskLevel(StrEnum):
    """Risk severity levels emitted by the analysis engine."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RiskCategory(StrEnum):
    """Infrastructure dependency categories used by risk rules."""

    DNS = "dns"
    IDENTITY = "identity"
    CDN = "cdn"
    SECRETS_MANAGER = "secrets_manager"
    MONITORING = "monitoring"
    NETWORKING = "networking"
    CI_CD = "ci_cd"
    EMAIL = "email"
    SINGLE_SERVICE_ARTICULATION = "single_service_articulation"


class DependencyChain(BaseModel):
    """Dependency chain from an impacted node to a risky dependency."""

    model_config = ConfigDict(frozen=True)

    source: str
    target: str
    path: tuple[str, ...]


class RiskFinding(BaseModel):
    """One risk finding in a ChokePoint risk report."""

    model_config = ConfigDict(frozen=True)

    node_id: str
    node_name: str
    provider: str
    category: RiskCategory
    risk_level: RiskLevel
    criticality: RiskLevel
    risk_score: int = Field(ge=0, le=100)
    blast_radius: int = Field(ge=0)
    impacted_nodes: tuple[str, ...]
    impacted_providers: tuple[str, ...]
    dependency_chain: tuple[DependencyChain, ...]
    explanation: str


class RiskReport(BaseModel):
    """Structured ChokePoint risk report."""

    model_config = ConfigDict(frozen=True)

    risk_score: int = Field(ge=0, le=100)
    finding_count: int = Field(ge=0)
    findings: tuple[RiskFinding, ...]

    def export_json(self) -> str:
        """Export the risk report as structured JSON.

        Returns:
            JSON representation of this report.
        """
        return self.model_dump_json(indent=2)


class RiskAnalyzer:
    """Analyze ChokePoint dependency risk from topologies or graphs."""

    CATEGORY_LEVELS: ClassVar[Mapping[RiskCategory, RiskLevel]] = {
        RiskCategory.DNS: RiskLevel.CRITICAL,
        RiskCategory.IDENTITY: RiskLevel.CRITICAL,
        RiskCategory.CDN: RiskLevel.CRITICAL,
        RiskCategory.SECRETS_MANAGER: RiskLevel.CRITICAL,
        RiskCategory.MONITORING: RiskLevel.HIGH,
        RiskCategory.NETWORKING: RiskLevel.HIGH,
        RiskCategory.CI_CD: RiskLevel.MEDIUM,
        RiskCategory.EMAIL: RiskLevel.MEDIUM,
        RiskCategory.SINGLE_SERVICE_ARTICULATION: RiskLevel.LOW,
    }
    BASE_SCORES: ClassVar[Mapping[RiskLevel, int]] = {
        RiskLevel.CRITICAL: 88,
        RiskLevel.HIGH: 70,
        RiskLevel.MEDIUM: 50,
        RiskLevel.LOW: 25,
    }

    def analyze(self, topology: Topology) -> RiskReport:
        """Analyze a topology and produce a structured risk report.

        Args:
            topology: Topology to analyze.

        Returns:
            Risk report.
        """
        graph = GraphBuilder().build(topology)
        return self.analyze_graph(graph)

    def analyze_graph(self, graph: nx.Graph) -> RiskReport:
        """Analyze a NetworkX graph produced from a topology.

        Args:
            graph: NetworkX graph with ChokePoint model attributes.

        Returns:
            Risk report.

        Raises:
            ValueError: If the graph is not a valid ChokePoint graph.
        """
        validation = GraphAnalyzer().validate(graph)
        if not validation.is_valid:
            message = "invalid ChokePoint graph: " + "; ".join(validation.issues)
            raise ValueError(message)

        articulation_points = tuple(sorted(nx.articulation_points(graph)))
        topology = _topology_from_graph(graph)
        dependency_index = _DependencyIndex(topology)
        findings: list[RiskFinding] = []
        emitted_nodes: set[str] = set()

        shared_category_nodes = self._shared_category_nodes(topology, dependency_index)
        for node_id, categories in shared_category_nodes.items():
            node = topology.nodes[node_id]
            for category in categories:
                finding = self._shared_finding(node, category, dependency_index)
                findings.append(finding)
                emitted_nodes.add(node.id)

        for node_id in articulation_points:
            if node_id in emitted_nodes:
                continue
            node = topology.nodes[node_id]
            impacted_services = dependency_index.impacted_services(node_id)
            if len(impacted_services) == 1:
                findings.append(self._articulation_finding(node, dependency_index))

        ordered_findings = tuple(
            sorted(
                findings,
                key=lambda finding: (
                    -finding.risk_score,
                    finding.risk_level.value,
                    finding.node_id,
                    finding.category.value,
                ),
            )
        )
        report_score = max(
            (finding.risk_score for finding in ordered_findings), default=0
        )
        return RiskReport(
            risk_score=report_score,
            finding_count=len(ordered_findings),
            findings=ordered_findings,
        )

    def _shared_category_nodes(
        self,
        topology: Topology,
        dependency_index: _DependencyIndex,
    ) -> dict[str, tuple[RiskCategory, ...]]:
        """Return nodes that match shared-risk categories."""
        category_nodes: dict[RiskCategory, list[str]] = defaultdict(list)
        for node in topology.nodes.values():
            categories = _classify_node(node)
            if not categories:
                continue
            if len(dependency_index.impacted_nodes(node.id)) < MIN_SHARED_DEPENDENTS:
                continue
            for category in categories:
                category_nodes[category].append(node.id)

        return {
            node_id: tuple(
                category
                for category, node_ids in category_nodes.items()
                if node_id in node_ids
            )
            for node_id in sorted(
                {
                    node_id
                    for node_ids in category_nodes.values()
                    for node_id in node_ids
                }
            )
        }

    def _shared_finding(
        self,
        node: Node,
        category: RiskCategory,
        dependency_index: _DependencyIndex,
    ) -> RiskFinding:
        """Build a finding for a shared dependency category."""
        impacted_nodes = dependency_index.impacted_nodes(node.id)
        impacted_providers = dependency_index.impacted_providers(node.id)
        chains = dependency_index.dependency_chains(node.id)
        risk_level = self.CATEGORY_LEVELS[category]
        score = _risk_score(risk_level, len(impacted_nodes), len(impacted_providers))

        return RiskFinding(
            node_id=node.id,
            node_name=node.name,
            provider=node.provider,
            category=category,
            risk_level=risk_level,
            criticality=risk_level,
            risk_score=score,
            blast_radius=len(impacted_nodes),
            impacted_nodes=impacted_nodes,
            impacted_providers=impacted_providers,
            dependency_chain=chains,
            explanation=_shared_explanation(
                node,
                category,
                impacted_nodes,
                impacted_providers,
            ),
        )

    def _articulation_finding(
        self,
        node: Node,
        dependency_index: _DependencyIndex,
    ) -> RiskFinding:
        """Build a low-risk articulation finding."""
        impacted_nodes = dependency_index.impacted_nodes(node.id)
        impacted_providers = dependency_index.impacted_providers(node.id)
        chains = dependency_index.dependency_chains(node.id)
        risk_level = RiskLevel.LOW
        score = _risk_score(risk_level, len(impacted_nodes), len(impacted_providers))
        return RiskFinding(
            node_id=node.id,
            node_name=node.name,
            provider=node.provider,
            category=RiskCategory.SINGLE_SERVICE_ARTICULATION,
            risk_level=risk_level,
            criticality=risk_level,
            risk_score=score,
            blast_radius=len(impacted_nodes),
            impacted_nodes=impacted_nodes,
            impacted_providers=impacted_providers,
            dependency_chain=chains,
            explanation=(
                f"{node.name} is an articulation point for a single service path."
            ),
        )


class _DependencyIndex:
    """Dependency traversal helpers for a topology."""

    def __init__(self, topology: Topology) -> None:
        self._topology = topology
        self._incoming: dict[str, list[str]] = defaultdict(list)
        self._outgoing: dict[str, list[str]] = defaultdict(list)
        for edge in topology.edges:
            if edge.relationship != Relationship.DEPENDS_ON:
                continue
            self._incoming[edge.target].append(edge.source)
            self._outgoing[edge.source].append(edge.target)

        for values in self._incoming.values():
            values.sort()
        for values in self._outgoing.values():
            values.sort()

    def impacted_nodes(self, node_id: str) -> tuple[str, ...]:
        """Return all nodes that directly or transitively depend on a node."""
        visited: set[str] = set()
        queue: deque[str] = deque(self._incoming[node_id])
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            queue.extend(self._incoming[current])

        return tuple(sorted(visited))

    def impacted_services(self, node_id: str) -> tuple[str, ...]:
        """Return impacted service nodes."""
        return tuple(
            node_id
            for node_id in self.impacted_nodes(node_id)
            if self._topology.nodes[node_id].node_type == NodeType.SERVICE
        )

    def impacted_providers(self, node_id: str) -> tuple[str, ...]:
        """Return impacted providers, excluding the dependency provider."""
        dependency_provider = self._topology.nodes[node_id].provider
        providers = {
            self._topology.nodes[impacted_node].provider
            for impacted_node in self.impacted_nodes(node_id)
            if self._topology.nodes[impacted_node].provider != dependency_provider
        }
        return tuple(sorted(providers))

    def dependency_chains(self, target: str) -> tuple[DependencyChain, ...]:
        """Return shortest dependency chains from impacted nodes to a target."""
        chains: list[DependencyChain] = []
        for source in self.impacted_nodes(target):
            path = self._shortest_dependency_path(source, target)
            if path:
                chains.append(DependencyChain(source=source, target=target, path=path))
        return tuple(sorted(chains, key=lambda chain: (len(chain.path), chain.path)))

    def _shortest_dependency_path(self, source: str, target: str) -> tuple[str, ...]:
        """Return the shortest source-to-target dependency path."""
        queue: deque[tuple[str, tuple[str, ...]]] = deque([(source, (source,))])
        visited: set[str] = set()
        while queue:
            current, path = queue.popleft()
            if current == target:
                return path
            if current in visited:
                continue
            visited.add(current)
            for next_node in self._outgoing[current]:
                queue.append((next_node, (*path, next_node)))
        return ()


def _topology_from_graph(graph: nx.Graph) -> Topology:
    """Reconstruct a topology from a ChokePoint NetworkX graph."""
    topology = Topology()
    for _, attributes in graph.nodes(data=True):
        node = attributes[GraphBuilder.NODE_ATTR]
        if not isinstance(node, Node):
            raise ValueError("graph contains a node without a ChokePoint Node model")
        topology.add_node(node)

    edge_keys: set[tuple[str, str, Relationship]] = set()
    for _, _, attributes in graph.edges(data=True):
        edges = attributes[GraphBuilder.EDGE_ATTR]
        if not isinstance(edges, tuple):
            raise ValueError("graph contains an edge without ChokePoint Edge models")
        for edge in edges:
            if not isinstance(edge, Edge):
                raise ValueError("graph contains a non-ChokePoint edge model")
            edge_key = (edge.source, edge.target, edge.relationship)
            if edge_key in edge_keys:
                continue
            topology.add_edge(edge)
            edge_keys.add(edge_key)
    return topology


def _classify_node(node: Node) -> tuple[RiskCategory, ...]:
    """Classify a node into risk categories."""
    text = " ".join(
        (
            node.id,
            node.name,
            node.provider,
            str(node.metadata.get("terraform_type", "")),
            str(node.metadata.get("category", "")),
        )
    ).lower()
    categories: list[RiskCategory] = []

    if node.node_type == NodeType.DNS or _contains_any(text, ("dns", "route53")):
        categories.append(RiskCategory.DNS)
    if node.node_type == NodeType.IDENTITY or _contains_any(
        text, ("iam", "identity", "okta", "auth0", "entra")
    ):
        categories.append(RiskCategory.IDENTITY)
    if _contains_any(text, ("cdn", "cloudfront", "cloudflare", "fastly", "akamai")):
        categories.append(RiskCategory.CDN)
    if node.node_type == NodeType.SECRET or _contains_any(
        text, ("secret", "secretsmanager", "keyvault", "vault")
    ):
        categories.append(RiskCategory.SECRETS_MANAGER)
    if _contains_any(text, ("monitoring", "datadog", "prometheus", "grafana")):
        categories.append(RiskCategory.MONITORING)
    if node.node_type == NodeType.NETWORK or _contains_any(
        text, ("vpc", "subnet", "network", "gateway", "security_group")
    ):
        categories.append(RiskCategory.NETWORKING)
    if _contains_any(text, ("ci", "cd", "cicd", "github-actions", "jenkins")):
        categories.append(RiskCategory.CI_CD)
    if _contains_any(text, ("email", "ses", "sendgrid", "mailgun")):
        categories.append(RiskCategory.EMAIL)

    return tuple(dict.fromkeys(categories))


def _risk_score(
    risk_level: RiskLevel,
    blast_radius: int,
    provider_count: int,
) -> int:
    """Calculate a bounded risk score."""
    base = RiskAnalyzer.BASE_SCORES[risk_level]
    score = base + min(blast_radius * 3, 9) + min(provider_count * 2, 6)
    return min(score, 100)


def _shared_explanation(
    node: Node,
    category: RiskCategory,
    impacted_nodes: tuple[str, ...],
    impacted_providers: tuple[str, ...],
) -> str:
    """Generate human-readable explanation text for a shared finding."""
    label = category.value.replace("_", " ").upper()
    if impacted_providers:
        providers = _human_join(
            tuple(provider.upper() for provider in impacted_providers)
        )
        return (
            f"{node.name} {label} is a shared dependency across {providers}, "
            f"with a blast radius of {len(impacted_nodes)} node(s)."
        )
    return f"{node.name} {label} is shared by {len(impacted_nodes)} dependent node(s)."


def _human_join(values: tuple[str, ...]) -> str:
    """Join values for human-readable explanation text."""
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == HUMAN_JOIN_PAIR_COUNT:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    """Return whether any needle appears in text."""
    return any(needle in text for needle in needles)
