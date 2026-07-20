"""Multi-format report generation for ChokePoint."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field
from rich.console import Console, ConsoleOptions, RenderResult
from rich.panel import Panel
from rich.table import Table

from chokepoint.graph import AnalysisReport, GraphAnalyzer, GraphBuilder
from chokepoint.models import Edge, Node, NodeType, Relationship, Topology
from chokepoint.report.risk import (
    ConfidenceLevel,
    RiskAnalyzer,
    RiskCategory,
    RiskFinding,
    RiskLevel,
    RiskReport,
)

CRITICAL_SCORE_THRESHOLD = 80
HIGH_SCORE_THRESHOLD = 60
HUMAN_JOIN_PAIR_COUNT = 2
STRUCTURAL_CONFIDENCE_DEPENDENT_THRESHOLD = 2
SEVERITY_SORT_RANK: dict[RiskLevel | None, int] = {
    RiskLevel.CRITICAL: 4,
    RiskLevel.HIGH: 3,
    RiskLevel.MEDIUM: 2,
    RiskLevel.LOW: 1,
    None: 0,
}
CONFIDENCE_SORT_RANK: dict[ConfidenceLevel, int] = {
    ConfidenceLevel.HIGH: 3,
    ConfidenceLevel.MEDIUM: 2,
    ConfidenceLevel.LOW: 1,
}
CATEGORY_LABELS: dict[RiskCategory, str] = {
    RiskCategory.DNS: "DNS",
    RiskCategory.IDENTITY: "identity",
    RiskCategory.CDN: "CDN",
    RiskCategory.SECRETS_MANAGER: "secrets manager",
    RiskCategory.MONITORING: "monitoring",
    RiskCategory.NETWORKING: "networking",
    RiskCategory.CI_CD: "CI/CD",
    RiskCategory.EMAIL: "email",
    RiskCategory.SINGLE_SERVICE_ARTICULATION: "single-service articulation",
}
CATEGORY_SORT_RANK: dict[RiskCategory, int] = {
    category: index for index, category in enumerate(CATEGORY_LABELS)
}


class DependencyTableRow(BaseModel):
    """Dependency table row for reports."""

    model_config = ConfigDict(frozen=True)

    source: str
    target: str
    relationship: str
    source_provider: str
    target_provider: str


class DependencyGraphEdge(BaseModel):
    """Human-readable dependency graph edge for reports."""

    model_config = ConfigDict(frozen=True)

    source: str
    source_name: str
    target: str
    target_name: str
    relationship: str


class SinglePointOfFailure(BaseModel):
    """Dependency or graph structure that concentrates failure impact."""

    model_config = ConfigDict(frozen=True)

    node_id: str
    name: str
    provider: str
    node_type: NodeType
    severity: RiskLevel | None
    category: str
    confidence: ConfidenceLevel
    confidence_reason: str
    blast_radius: int = Field(ge=0)
    impacted_nodes: tuple[str, ...]
    why_it_matters: str


class GeneratedReport(BaseModel):
    """Structured security report generated from a topology."""

    model_config = ConfigDict(frozen=True)

    title: str = "ChokePoint Security Report"
    executive_summary: str
    risk_score: int = Field(ge=0, le=100)
    critical_dependencies: tuple[RiskFinding, ...]
    articulation_points: tuple[str, ...]
    bridge_edges: tuple[tuple[str, str], ...]
    recommendations: tuple[str, ...]
    dependency_graph: tuple[DependencyGraphEdge, ...]
    single_points_of_failure: tuple[SinglePointOfFailure, ...]
    dependency_table: tuple[DependencyTableRow, ...]
    blast_radius: dict[str, int]
    risk_report: RiskReport
    graph_report: AnalysisReport

    def to_json(self) -> str:
        """Render this report as structured JSON.

        Returns:
            JSON representation suitable for automation.
        """
        return self.model_dump_json(indent=2)

    def to_markdown(self) -> str:
        """Render this report as GitHub-flavored Markdown.

        Returns:
            Markdown report.
        """
        return _MarkdownRenderer(self).render()

    def to_terminal(self) -> TerminalReport:
        """Render this report as a Rich terminal object.

        Returns:
            Rich renderable terminal report.
        """
        return TerminalReport(self)


class SecurityReportGenerator:
    """Generate security reports from ChokePoint topologies."""

    def generate(self, topology: Topology) -> GeneratedReport:
        """Generate a report from a topology.

        Args:
            topology: Topology to report on.

        Returns:
            Generated security report.
        """
        graph = GraphBuilder().build(topology)
        graph_report = GraphAnalyzer().analyze(graph)
        risk_report = RiskAnalyzer().analyze(topology)
        dependency_rows = _dependency_rows(topology)
        dependency_graph = _dependency_graph_edges(topology)
        critical_dependencies = tuple(
            finding
            for finding in risk_report.findings
            if finding.risk_level == RiskLevel.CRITICAL
        )
        recommendations = _recommendations(
            risk_report=risk_report,
            graph_report=graph_report,
        )
        blast_radius = {
            finding.node_id: finding.blast_radius for finding in risk_report.findings
        }
        single_points = _single_points_of_failure(
            topology=topology,
            risk_report=risk_report,
            graph_report=graph_report,
        )

        return GeneratedReport(
            executive_summary=_executive_summary(risk_report, graph_report),
            risk_score=risk_report.risk_score,
            critical_dependencies=critical_dependencies,
            articulation_points=graph_report.articulation_points,
            bridge_edges=graph_report.bridges,
            recommendations=recommendations,
            dependency_graph=dependency_graph,
            single_points_of_failure=single_points,
            dependency_table=dependency_rows,
            blast_radius=blast_radius,
            risk_report=risk_report,
            graph_report=graph_report,
        )


class TerminalReport:
    """Rich renderable terminal report."""

    def __init__(self, report: GeneratedReport) -> None:
        """Create a terminal report.

        Args:
            report: Generated report to render.
        """
        self._report = report

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        """Render report sections to a Rich console."""
        del console, options
        yield Panel(
            self._report.executive_summary,
            title=self._report.title,
            subtitle=f"Risk Score: {self._report.risk_score}",
            border_style=_score_style(self._report.risk_score),
        )
        yield _critical_dependencies_table(self._report.critical_dependencies)
        yield _graph_findings_table(
            self._report.articulation_points,
            self._report.bridge_edges,
        )
        yield _dependency_graph_table(self._report.dependency_graph)
        yield _single_points_table(self._report.single_points_of_failure)
        yield _recommendations_table(self._report.recommendations)
        yield _dependency_table(self._report.dependency_table)


class _MarkdownRenderer:
    """Markdown renderer for generated reports."""

    def __init__(self, report: GeneratedReport) -> None:
        self._report = report

    def render(self) -> str:
        """Render Markdown."""
        lines = [
            f"# {self._report.title}",
            "",
            "## Executive Summary",
            "",
            self._report.executive_summary,
            "",
            "## Risk Score",
            "",
            f"**{self._report.risk_score}/100**",
            "",
            "## Dependency Graph",
            "",
            *_dependency_graph_markdown(self._report),
            "",
            "## Hidden Single Points of Failure",
            "",
            *_single_points_markdown(self._report.single_points_of_failure),
            "",
            "## Critical Dependencies",
            "",
            *_critical_dependency_markdown(self._report.critical_dependencies),
            "",
            "## Articulation Points",
            "",
            *_list_or_none(self._report.articulation_points),
            "",
            "## Bridge Edges",
            "",
            *_bridge_markdown(self._report.bridge_edges),
            "",
            "## Recommendations",
            "",
            *_list_or_none(self._report.recommendations),
            "",
            "## Dependency Table",
            "",
            *_dependency_table_markdown(self._report.dependency_table),
            "",
            "## Blast Radius",
            "",
            *_blast_radius_markdown(self._report.blast_radius),
            "",
        ]
        return "\n".join(lines)


def generate_security_report(topology: Topology) -> GeneratedReport:
    """Generate a security report from a topology.

    Args:
        topology: Topology to report on.

    Returns:
        Generated report.
    """
    return SecurityReportGenerator().generate(topology)


def _executive_summary(
    risk_report: RiskReport,
    graph_report: AnalysisReport,
) -> str:
    """Create executive summary text."""
    critical_count = sum(
        1
        for finding in risk_report.findings
        if finding.risk_level == RiskLevel.CRITICAL
    )
    return (
        f"ChokePoint analyzed {graph_report.node_count} nodes and "
        f"{graph_report.edge_count} dependency edges. The current risk score is "
        f"{risk_report.risk_score}/100 with {risk_report.finding_count} finding(s), "
        f"including {critical_count} critical dependency finding(s), "
        f"{len(graph_report.articulation_points)} articulation point(s), and "
        f"{len(graph_report.bridges)} bridge edge(s)."
    )


def _dependency_rows(topology: Topology) -> tuple[DependencyTableRow, ...]:
    """Build dependency table rows."""
    rows: list[DependencyTableRow] = []
    for edge in sorted(
        topology.edges,
        key=lambda item: (item.source, item.target, item.relationship.value),
    ):
        source = topology.nodes[edge.source]
        target = topology.nodes[edge.target]
        rows.append(_dependency_row(edge, source, target))
    return tuple(rows)


def _dependency_graph_edges(topology: Topology) -> tuple[DependencyGraphEdge, ...]:
    """Build human-readable dependency graph edges."""
    edges: list[DependencyGraphEdge] = []
    for edge in sorted(
        topology.edges,
        key=lambda item: (item.source, item.target, item.relationship.value),
    ):
        source = topology.nodes[edge.source]
        target = topology.nodes[edge.target]
        edges.append(
            DependencyGraphEdge(
                source=edge.source,
                source_name=source.name,
                target=edge.target,
                target_name=target.name,
                relationship=edge.relationship.value,
            )
        )
    return tuple(edges)


def _dependency_row(edge: Edge, source: Node, target: Node) -> DependencyTableRow:
    """Build one dependency table row."""
    return DependencyTableRow(
        source=edge.source,
        target=edge.target,
        relationship=edge.relationship.value,
        source_provider=source.provider,
        target_provider=target.provider,
    )


def _single_points_of_failure(
    *,
    topology: Topology,
    risk_report: RiskReport,
    graph_report: AnalysisReport,
) -> tuple[SinglePointOfFailure, ...]:
    """Build single-point-of-failure explanations."""
    points: list[SinglePointOfFailure] = []
    seen: set[str] = set()

    for node_id, findings in _risk_findings_by_node(risk_report.findings).items():
        node = topology.nodes[node_id]
        points.append(_risk_single_point(node, findings))
        seen.add(node.id)

    for node_id in graph_report.articulation_points:
        if node_id in seen:
            continue
        node = topology.nodes[node_id]
        neighbors = topology.neighbors(node_id, direction="both")
        impacted_nodes = tuple(sorted(neighbor.id for neighbor in neighbors))
        confidence, confidence_reason = _structural_confidence(topology, node_id)
        points.append(
            SinglePointOfFailure(
                node_id=node.id,
                name=node.name,
                provider=node.provider,
                node_type=node.node_type,
                severity=None,
                category="structural_articulation",
                confidence=confidence,
                confidence_reason=confidence_reason,
                blast_radius=len(impacted_nodes),
                impacted_nodes=impacted_nodes,
                why_it_matters=(
                    f"{node.name} is a structural cut point. If it fails or is "
                    "removed, it can disconnect adjacent dependency paths: "
                    f"{_impacted_text(impacted_nodes)}."
                ),
            )
        )

    return tuple(
        sorted(
            points,
            key=lambda point: (
                -_severity_rank(point.severity),
                -point.blast_radius,
                point.node_id,
            ),
        )
    )


def _risk_findings_by_node(
    findings: tuple[RiskFinding, ...],
) -> dict[str, tuple[RiskFinding, ...]]:
    """Group risk findings by node id in deterministic order."""
    grouped: dict[str, list[RiskFinding]] = {}
    for finding in findings:
        grouped.setdefault(finding.node_id, []).append(finding)
    return {node_id: tuple(grouped[node_id]) for node_id in sorted(grouped)}


def _risk_single_point(
    node: Node,
    findings: tuple[RiskFinding, ...],
) -> SinglePointOfFailure:
    """Build a single-point explanation from a risk finding."""
    severity = max((finding.risk_level for finding in findings), key=_severity_rank)
    confidence = max(
        (finding.confidence for finding in findings),
        key=_confidence_rank,
    )
    confidence_reason = _confidence_reason(findings, confidence)
    categories = tuple(
        sorted(
            {finding.category for finding in findings},
            key=lambda item: CATEGORY_SORT_RANK[item],
        )
    )
    impacted_nodes = tuple(
        sorted(
            {
                impacted_node
                for finding in findings
                for impacted_node in finding.impacted_nodes
            }
        )
    )
    impacted_providers = tuple(
        sorted(
            {
                provider
                for finding in findings
                for provider in finding.impacted_providers
            }
        )
    )
    category_text = _category_text(categories)
    provider_text = _provider_text(impacted_providers)
    why_it_matters = _risk_single_point_explanation(
        node=node,
        categories=categories,
        impacted_nodes=impacted_nodes,
        category_text=category_text,
        provider_text=provider_text,
    )

    return SinglePointOfFailure(
        node_id=node.id,
        name=node.name,
        provider=node.provider,
        node_type=node.node_type,
        severity=severity,
        category=", ".join(category.value for category in categories),
        confidence=confidence,
        confidence_reason=confidence_reason,
        blast_radius=len(impacted_nodes),
        impacted_nodes=impacted_nodes,
        why_it_matters=why_it_matters,
    )


def _risk_single_point_explanation(
    *,
    node: Node,
    categories: tuple[RiskCategory, ...],
    impacted_nodes: tuple[str, ...],
    category_text: str,
    provider_text: str,
) -> str:
    """Explain why a risk finding creates a single point of failure."""
    category_impacts = " ".join(
        dict.fromkeys(_category_impact(category) for category in categories)
    )
    impacted_text = _impacted_text(impacted_nodes)

    if categories == (RiskCategory.SINGLE_SERVICE_ARTICULATION,):
        path_text = (
            "that dependency path"
            if len(impacted_nodes) == 1
            else "those dependency paths"
        )
        return (
            f"{node.name} is an articulation point on the dependency path for "
            f"{impacted_text}. If it fails, {path_text} can be disconnected. "
            f"{category_impacts}"
        )

    return (
        f"{node.name} is a shared {category_text} dependency{provider_text}. "
        f"If it fails, {impacted_text} may be affected. {category_impacts}"
    )


def _structural_confidence(
    topology: Topology,
    node_id: str,
) -> tuple[ConfidenceLevel, str]:
    """Return confidence for a structural articulation-only finding."""
    direct_dependents = {
        edge.source
        for edge in topology.edges
        if edge.target == node_id and edge.relationship == Relationship.DEPENDS_ON
    }
    if len(direct_dependents) >= STRUCTURAL_CONFIDENCE_DEPENDENT_THRESHOLD:
        return (
            ConfidenceLevel.MEDIUM,
            "Based on graph articulation structure plus multiple explicit "
            "depends_on edges; verify runtime impact with service owners.",
        )
    return (
        ConfidenceLevel.LOW,
        "Based only on graph articulation structure; verify runtime impact with "
        "service owners.",
    )


def _recommendations(
    *,
    risk_report: RiskReport,
    graph_report: AnalysisReport,
) -> tuple[str, ...]:
    """Generate actionable recommendations."""
    recommendations: list[str] = []
    has_critical_finding = any(
        finding.risk_level == RiskLevel.CRITICAL for finding in risk_report.findings
    )
    if has_critical_finding:
        recommendations.append(
            "Add redundant providers or failover paths for critical shared "
            "dependencies."
        )
    if graph_report.articulation_points:
        recommendations.append(
            "Reduce single-node choke points by introducing alternate dependency paths."
        )
    if graph_report.bridges:
        recommendations.append(
            "Review bridge edges and add backup connectivity for high-impact links."
        )
    if risk_report.findings:
        recommendations.append(
            "Track each finding as a GitHub Security issue with an owner and "
            "remediation date."
        )
    if not recommendations:
        recommendations.append(
            "No immediate choke-point risks were detected; continue monitoring "
            "topology drift."
        )
    return tuple(recommendations)


def _critical_dependencies_table(findings: Iterable[RiskFinding]) -> Table:
    """Build terminal critical dependencies table."""
    table = Table(title="Critical Dependencies")
    table.add_column("Category")
    table.add_column("Node")
    table.add_column("Score", justify="right")
    table.add_column("Blast Radius", justify="right")
    table.add_column("Confidence")
    table.add_column("Explanation")
    for finding in findings:
        table.add_row(
            finding.category.value,
            finding.node_id,
            str(finding.risk_score),
            str(finding.blast_radius),
            finding.confidence.value,
            finding.explanation,
        )
    return table


def _graph_findings_table(
    articulation_points: tuple[str, ...],
    bridge_edges: tuple[tuple[str, str], ...],
) -> Table:
    """Build terminal graph findings table."""
    table = Table(title="Graph Choke Points")
    table.add_column("Type")
    table.add_column("Value")
    for node_id in articulation_points:
        table.add_row("Articulation Point", node_id)
    for source, target in bridge_edges:
        table.add_row("Bridge Edge", f"{source} -> {target}")
    return table


def _dependency_graph_table(edges: tuple[DependencyGraphEdge, ...]) -> Table:
    """Build terminal dependency graph table."""
    table = Table(title="Dependency Graph")
    table.add_column("Source")
    table.add_column("Depends On")
    table.add_column("Relationship")
    if not edges:
        table.add_row("None", "None", "No dependencies declared")
        return table
    for edge in edges:
        table.add_row(edge.source, edge.target, edge.relationship)
    return table


def _single_points_table(points: tuple[SinglePointOfFailure, ...]) -> Table:
    """Build terminal single-points-of-failure table."""
    table = Table(title="Hidden Single Points of Failure")
    table.add_column("Node")
    table.add_column("Severity")
    table.add_column("Category")
    table.add_column("Blast Radius", justify="right")
    table.add_column("Confidence")
    table.add_column("Why It Matters")
    if not points:
        table.add_row(
            "None",
            "none",
            "none",
            "0",
            "none",
            "No single points detected.",
        )
        return table
    for point in points:
        table.add_row(
            point.node_id,
            point.severity.value if point.severity else "structural",
            _point_category_text(point.category),
            str(point.blast_radius),
            point.confidence.value,
            point.why_it_matters,
        )
    return table


def _recommendations_table(recommendations: tuple[str, ...]) -> Table:
    """Build terminal recommendations table."""
    table = Table(title="Recommendations")
    table.add_column("Recommendation")
    for recommendation in recommendations:
        table.add_row(recommendation)
    return table


def _dependency_table(rows: tuple[DependencyTableRow, ...]) -> Table:
    """Build terminal dependency table."""
    table = Table(title="Dependency Table")
    table.add_column("Source")
    table.add_column("Target")
    table.add_column("Relationship")
    table.add_column("Source Provider")
    table.add_column("Target Provider")
    for row in rows:
        table.add_row(
            row.source,
            row.target,
            row.relationship,
            row.source_provider,
            row.target_provider,
        )
    return table


def _dependency_graph_markdown(report: GeneratedReport) -> list[str]:
    """Render dependency graph as Markdown with Mermaid."""
    return [
        "Arrows mean `source depends on target`.",
        "",
        "```mermaid",
        *_mermaid_graph(report).splitlines(),
        "```",
    ]


def _single_points_markdown(points: tuple[SinglePointOfFailure, ...]) -> list[str]:
    """Render single points of failure as explanatory Markdown."""
    if not points:
        return ["No hidden single points of failure detected."]
    lines: list[str] = []
    for point in points:
        lines.append(
            f"- **{_escape_markdown(point.name)}** (`{point.node_id}`) - "
            f"{_point_summary(point)}, blast radius `{point.blast_radius}`. "
            f"Confidence: `{point.confidence.value}`. "
            f"Why it matters: {_escape_markdown(point.why_it_matters)}"
        )
    return lines


def _critical_dependency_markdown(findings: tuple[RiskFinding, ...]) -> list[str]:
    """Render critical dependencies as Markdown."""
    if not findings:
        return ["No critical dependencies detected."]
    lines = [
        "| Level | Category | Node | Score | Blast Radius | Confidence | Explanation |",
        "| --- | --- | --- | ---: | ---: | --- | --- |",
    ]
    for finding in findings:
        lines.append(
            "| "
            f"{finding.risk_level.value} | "
            f"{finding.category.value} | "
            f"`{finding.node_id}` | "
            f"{finding.risk_score} | "
            f"{finding.blast_radius} | "
            f"{finding.confidence.value} | "
            f"{_escape_markdown(finding.explanation)} |"
        )
    return lines


def _dependency_table_markdown(rows: tuple[DependencyTableRow, ...]) -> list[str]:
    """Render dependency table as Markdown."""
    if not rows:
        return ["No dependencies declared."]
    lines = [
        "| Source | Target | Relationship | Source Provider | Target Provider |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            f"`{row.source}` | `{row.target}` | `{row.relationship}` | "
            f"`{row.source_provider}` | `{row.target_provider}` |"
        )
    return lines


def _bridge_markdown(bridges: tuple[tuple[str, str], ...]) -> list[str]:
    """Render bridges as Markdown."""
    if not bridges:
        return ["No bridge edges detected."]
    return [f"- `{source}` -> `{target}`" for source, target in bridges]


def _blast_radius_markdown(blast_radius: dict[str, int]) -> list[str]:
    """Render blast radius as Markdown."""
    if not blast_radius:
        return ["No blast radius detected."]
    return [
        f"- `{node_id}`: `{radius}`" for node_id, radius in sorted(blast_radius.items())
    ]


def _mermaid_graph(report: GeneratedReport) -> str:
    """Render a Mermaid dependency graph with SPOF labels."""
    if not report.dependency_graph:
        return 'flowchart LR\n  empty["No dependencies declared"]'

    single_points = {point.node_id: point for point in report.single_points_of_failure}
    nodes: dict[str, str] = {}
    for edge in report.dependency_graph:
        nodes[edge.source] = edge.source_name
        nodes[edge.target] = edge.target_name

    lines = ["flowchart LR"]
    for node_id, name in sorted(nodes.items()):
        point = single_points.get(node_id)
        label = name
        if point is not None:
            label = f"{name}\\nSPOF: {_point_summary(point)}"
        lines.append(f'  {_mermaid_id(node_id)}["{_escape_mermaid_label(label)}"]')

    for edge in report.dependency_graph:
        lines.append(
            "  "
            f"{_mermaid_id(edge.source)} -->|{edge.relationship}| "
            f"{_mermaid_id(edge.target)}"
        )
    return "\n".join(lines)


def _list_or_none(values: tuple[str, ...]) -> list[str]:
    """Render a Markdown list or empty state."""
    if not values:
        return ["None detected."]
    return [f"- `{value}`" for value in values]


def _escape_markdown(value: str) -> str:
    """Escape markdown table separators."""
    return value.replace("|", "\\|")


def _mermaid_id(value: str) -> str:
    """Return a stable Mermaid node id."""
    return "n_" + "".join(
        character if character.isalnum() else "_" for character in value
    )


def _escape_mermaid_label(value: str) -> str:
    """Escape Mermaid label text."""
    return value.replace('"', '\\"')


def _point_summary(point: SinglePointOfFailure) -> str:
    """Return a compact human label for a single point."""
    category = _point_category_text(point.category)
    if point.severity is None:
        return category
    return f"{point.severity.value} {category}"


def _point_category_text(value: str) -> str:
    """Return a human-readable label for a point category string."""
    labels: list[str] = []
    for raw_category in (part.strip() for part in value.split(",")):
        try:
            category = RiskCategory(raw_category)
        except ValueError:
            labels.append(raw_category.replace("_", " "))
        else:
            labels.append(CATEGORY_LABELS[category])
    return ", ".join(labels)


def _impacted_text(values: tuple[str, ...]) -> str:
    """Return impacted node wording for explanations."""
    return _human_text_list(values) or "no directly identified nodes"


def _human_text_list(values: tuple[str, ...]) -> str:
    """Join plain text values for human-readable explanations."""
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == HUMAN_JOIN_PAIR_COUNT:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def _category_text(categories: tuple[RiskCategory, ...]) -> str:
    """Return a human-readable category list."""
    return _human_text_list(tuple(CATEGORY_LABELS[category] for category in categories))


def _provider_text(providers: tuple[str, ...]) -> str:
    """Return provider context for an explanation."""
    if not providers:
        return ""
    return (
        f" across {_human_text_list(tuple(provider.upper() for provider in providers))}"
    )


def _category_impact(category: RiskCategory) -> str:
    """Explain why a risk category matters operationally."""
    impacts = {
        RiskCategory.DNS: (
            "DNS failures can make healthy services unreachable to users and "
            "other systems."
        ),
        RiskCategory.IDENTITY: (
            "Identity failures can block authentication, authorization, and "
            "service-to-service access."
        ),
        RiskCategory.CDN: (
            "CDN failures can make edge delivery unavailable even when origins "
            "are healthy."
        ),
        RiskCategory.SECRETS_MANAGER: (
            "Secrets failures can prevent applications from starting, rotating "
            "credentials, or connecting to dependencies."
        ),
        RiskCategory.MONITORING: (
            "Monitoring failures can hide incidents and delay recovery."
        ),
        RiskCategory.NETWORKING: (
            "Networking failures can disconnect otherwise healthy services."
        ),
        RiskCategory.CI_CD: (
            "CI/CD failures can block deploys, rollbacks, and urgent fixes."
        ),
        RiskCategory.EMAIL: (
            "Email dependency failures can break notifications, verification, "
            "and customer communication."
        ),
        RiskCategory.SINGLE_SERVICE_ARTICULATION: (
            "A structural articulation point can disconnect an end-to-end "
            "dependency path."
        ),
    }
    return impacts[category]


def _severity_rank(severity: RiskLevel | None) -> int:
    """Return sort rank for severity."""
    return SEVERITY_SORT_RANK[severity]


def _confidence_rank(confidence: ConfidenceLevel) -> int:
    """Return sort rank for confidence."""
    return CONFIDENCE_SORT_RANK[confidence]


def _confidence_reason(
    findings: tuple[RiskFinding, ...],
    confidence: ConfidenceLevel,
) -> str:
    """Return a representative confidence reason."""
    reasons = tuple(
        dict.fromkeys(
            finding.confidence_reason
            for finding in findings
            if finding.confidence == confidence
        )
    )
    return reasons[0] if reasons else "Confidence is based on available graph evidence."


def _score_style(score: int) -> str:
    """Return terminal style for risk score."""
    if score >= CRITICAL_SCORE_THRESHOLD:
        return "red"
    if score >= HIGH_SCORE_THRESHOLD:
        return "yellow"
    return "green"
