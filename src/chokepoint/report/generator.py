"""Multi-format report generation for ChokePoint."""

from __future__ import annotations

import html
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field
from rich.console import Console, ConsoleOptions, RenderResult
from rich.panel import Panel
from rich.table import Table

from chokepoint.graph import AnalysisReport, GraphAnalyzer, GraphBuilder
from chokepoint.models import Edge, Node, Topology
from chokepoint.report.risk import RiskAnalyzer, RiskFinding, RiskLevel, RiskReport

CRITICAL_SCORE_THRESHOLD = 80
HIGH_SCORE_THRESHOLD = 60
CRITICAL_TABLE_COLUMNS = 6
DEPENDENCY_TABLE_COLUMNS = 5


class DependencyTableRow(BaseModel):
    """Dependency table row for reports."""

    model_config = ConfigDict(frozen=True)

    source: str
    target: str
    relationship: str
    source_provider: str
    target_provider: str


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

    def to_html(self) -> str:
        """Render this report as standalone HTML.

        Returns:
            HTML report.
        """
        return _HtmlRenderer(self).render()

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

        return GeneratedReport(
            executive_summary=_executive_summary(risk_report, graph_report),
            risk_score=risk_report.risk_score,
            critical_dependencies=critical_dependencies,
            articulation_points=graph_report.articulation_points,
            bridge_edges=graph_report.bridges,
            recommendations=recommendations,
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


class _HtmlRenderer:
    """HTML renderer for generated reports."""

    def __init__(self, report: GeneratedReport) -> None:
        self._report = report

    def render(self) -> str:
        """Render standalone HTML."""
        critical_rows = "".join(
            _html_row(
                (
                    finding.risk_level.value,
                    finding.category.value,
                    finding.node_id,
                    str(finding.risk_score),
                    str(finding.blast_radius),
                    finding.explanation,
                )
            )
            for finding in self._report.critical_dependencies
        )
        dependency_rows = "".join(
            _html_row(
                (
                    row.source,
                    row.target,
                    row.relationship,
                    row.source_provider,
                    row.target_provider,
                )
            )
            for row in self._report.dependency_table
        )
        recommendations = "".join(
            f"<li>{html.escape(recommendation)}</li>"
            for recommendation in self._report.recommendations
        )
        articulation_points = "".join(
            f"<li>{html.escape(node_id)}</li>"
            for node_id in self._report.articulation_points
        )
        bridges = "".join(
            f"<li>{html.escape(source)} &rarr; {html.escape(target)}</li>"
            for source, target in self._report.bridge_edges
        )
        blast_radius = "".join(
            f"<li><code>{html.escape(node_id)}</code>: {radius}</li>"
            for node_id, radius in sorted(self._report.blast_radius.items())
        )
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html.escape(self._report.title)}</title>
  <style>
    body {{ font-family: Inter, Arial, sans-serif; margin: 2rem; color: #111827; }}
    h1, h2 {{ color: #111827; }}
    .score {{ font-size: 2rem; font-weight: 700; color: #b91c1c; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
    th, td {{ border: 1px solid #d1d5db; padding: 0.5rem; text-align: left; }}
    th {{ background: #f3f4f6; }}
    code {{ background: #f3f4f6; padding: 0.1rem 0.25rem; }}
  </style>
</head>
<body>
  <h1>{html.escape(self._report.title)}</h1>
  <h2>Executive Summary</h2>
  <p>{html.escape(self._report.executive_summary)}</p>
  <h2>Risk Score</h2>
  <p class="score">{self._report.risk_score}/100</p>
  <h2>Critical Dependencies</h2>
  <table>
    <thead>
      <tr>
        <th>Level</th><th>Category</th><th>Node</th><th>Score</th>
        <th>Blast Radius</th><th>Explanation</th>
      </tr>
    </thead>
    <tbody>{critical_rows or _empty_html_row(CRITICAL_TABLE_COLUMNS)}</tbody>
  </table>
  <h2>Articulation Points</h2>
  <ul>{articulation_points or "<li>None detected.</li>"}</ul>
  <h2>Bridge Edges</h2>
  <ul>{bridges or "<li>None detected.</li>"}</ul>
  <h2>Recommendations</h2>
  <ul>{recommendations}</ul>
  <h2>Dependency Table</h2>
  <table>
    <thead>
      <tr>
        <th>Source</th><th>Target</th><th>Relationship</th>
        <th>Source Provider</th><th>Target Provider</th>
      </tr>
    </thead>
    <tbody>{dependency_rows or _empty_html_row(DEPENDENCY_TABLE_COLUMNS)}</tbody>
  </table>
  <h2>Blast Radius</h2>
  <ul>{blast_radius or "<li>No blast radius detected.</li>"}</ul>
</body>
</html>
"""


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


def _dependency_row(edge: Edge, source: Node, target: Node) -> DependencyTableRow:
    """Build one dependency table row."""
    return DependencyTableRow(
        source=edge.source,
        target=edge.target,
        relationship=edge.relationship.value,
        source_provider=source.provider,
        target_provider=target.provider,
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
    table.add_column("Explanation")
    for finding in findings:
        table.add_row(
            finding.category.value,
            finding.node_id,
            str(finding.risk_score),
            str(finding.blast_radius),
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


def _critical_dependency_markdown(findings: tuple[RiskFinding, ...]) -> list[str]:
    """Render critical dependencies as Markdown."""
    if not findings:
        return ["No critical dependencies detected."]
    lines = [
        "| Level | Category | Node | Score | Blast Radius | Explanation |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    for finding in findings:
        lines.append(
            "| "
            f"{finding.risk_level.value} | "
            f"{finding.category.value} | "
            f"`{finding.node_id}` | "
            f"{finding.risk_score} | "
            f"{finding.blast_radius} | "
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


def _list_or_none(values: tuple[str, ...]) -> list[str]:
    """Render a Markdown list or empty state."""
    if not values:
        return ["None detected."]
    return [f"- `{value}`" for value in values]


def _html_row(values: tuple[str, ...]) -> str:
    """Render one HTML table row."""
    cells = "".join(f"<td>{html.escape(value)}</td>" for value in values)
    return f"<tr>{cells}</tr>"


def _empty_html_row(colspan: int) -> str:
    """Render an empty table row."""
    return f'<tr><td colspan="{colspan}">None detected.</td></tr>'


def _escape_markdown(value: str) -> str:
    """Escape markdown table separators."""
    return value.replace("|", "\\|")


def _score_style(score: int) -> str:
    """Return terminal style for risk score."""
    if score >= CRITICAL_SCORE_THRESHOLD:
        return "red"
    if score >= HIGH_SCORE_THRESHOLD:
        return "yellow"
    return "green"
