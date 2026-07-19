"""Graphviz visualization for ChokePoint topologies."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from chokepoint.graph import GraphAnalyzer, GraphBuilder
from chokepoint.models import Node, NodeType, Topology


class VisualizationLayout(StrEnum):
    """Supported Graphviz layout strategies."""

    HIERARCHICAL = "hierarchical"
    CLUSTER = "cluster"
    RADIAL = "radial"


class VisualizationFormat(StrEnum):
    """Supported Graphviz output formats."""

    DOT = "dot"
    SVG = "svg"
    PNG = "png"


class GraphvizRenderError(RuntimeError):
    """Raised when Graphviz cannot render a requested artifact."""


class GraphvizArtifact(BaseModel):
    """Rendered Graphviz artifact."""

    model_config = ConfigDict(frozen=True)

    format: VisualizationFormat
    content: bytes

    @property
    def text(self) -> str:
        """Return artifact content decoded as UTF-8 text.

        Returns:
            Decoded artifact content.
        """
        return self.content.decode("utf-8")


class GraphvizVisualizer:
    """Generate Graphviz DOT, SVG, and PNG visualizations."""

    ARTICULATION_COLOR: ClassVar[str] = "#d62728"
    BRIDGE_COLOR: ClassVar[str] = "#ff7f0e"
    CLOUD_COLOR: ClassVar[str] = "#1f77b4"
    APPLICATION_COLOR: ClassVar[str] = "#2ca02c"
    INFRASTRUCTURE_COLOR: ClassVar[str] = "#7f7f7f"
    DEFAULT_EDGE_COLOR: ClassVar[str] = "#9ca3af"
    BACKGROUND_COLOR: ClassVar[str] = "#ffffff"
    CLOUD_PROVIDERS: ClassVar[frozenset[str]] = frozenset(
        {"aws", "azure", "gcp", "google", "cloud", "cloudflare"}
    )

    def __init__(self, dot_executable: str = "dot") -> None:
        """Create a Graphviz visualizer.

        Args:
            dot_executable: Graphviz executable used for SVG and PNG rendering.
        """
        self._dot_executable = dot_executable

    def export_dot(
        self,
        topology: Topology,
        *,
        layout: VisualizationLayout = VisualizationLayout.HIERARCHICAL,
    ) -> str:
        """Generate Graphviz DOT for a topology.

        Args:
            topology: Topology to visualize.
            layout: Graphviz layout strategy.

        Returns:
            DOT graph definition.
        """
        context = _VisualizationContext.from_topology(topology)
        writer = _DotWriter(layout=layout, context=context)
        return writer.write()

    def render_svg(
        self,
        topology: Topology,
        *,
        layout: VisualizationLayout = VisualizationLayout.HIERARCHICAL,
    ) -> GraphvizArtifact:
        """Render a topology as SVG.

        Args:
            topology: Topology to visualize.
            layout: Graphviz layout strategy.

        Returns:
            SVG artifact.
        """
        return self._render(topology, VisualizationFormat.SVG, layout=layout)

    def render_png(
        self,
        topology: Topology,
        *,
        layout: VisualizationLayout = VisualizationLayout.HIERARCHICAL,
    ) -> GraphvizArtifact:
        """Render a topology as PNG.

        Args:
            topology: Topology to visualize.
            layout: Graphviz layout strategy.

        Returns:
            PNG artifact.
        """
        return self._render(topology, VisualizationFormat.PNG, layout=layout)

    def write(
        self,
        topology: Topology,
        path: str | Path,
        *,
        layout: VisualizationLayout = VisualizationLayout.HIERARCHICAL,
        output_format: VisualizationFormat | None = None,
    ) -> Path:
        """Write a visualization artifact to disk.

        Args:
            topology: Topology to visualize.
            path: Destination path.
            layout: Graphviz layout strategy.
            output_format: Optional explicit output format.

        Returns:
            Written path.
        """
        destination = Path(path)
        chosen_format = output_format or _format_from_suffix(destination)
        if chosen_format == VisualizationFormat.DOT:
            destination.write_text(
                self.export_dot(topology, layout=layout),
                encoding="utf-8",
            )
            return destination

        artifact = self._render(topology, chosen_format, layout=layout)
        destination.write_bytes(artifact.content)
        return destination

    def _render(
        self,
        topology: Topology,
        output_format: VisualizationFormat,
        *,
        layout: VisualizationLayout,
    ) -> GraphvizArtifact:
        """Render a topology using Graphviz."""
        dot_source = self.export_dot(topology, layout=layout)
        executable = shutil.which(self._dot_executable)
        if executable is None:
            message = (
                f"Graphviz executable {self._dot_executable!r} was not found. "
                "Install Graphviz or use export_dot() to generate DOT."
            )
            raise GraphvizRenderError(message)

        command = [
            executable,
            f"-K{_engine_for_layout(layout)}",
            f"-T{output_format.value}",
        ]
        try:
            completed = subprocess.run(
                command,
                input=dot_source.encode("utf-8"),
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError as error:
            message = error.stderr.decode("utf-8", errors="replace").strip()
            raise GraphvizRenderError(
                message or "Graphviz failed to render visualization"
            ) from error

        return GraphvizArtifact(format=output_format, content=completed.stdout)


class _VisualizationContext(BaseModel):
    """Graph-derived styling context for DOT generation."""

    model_config = ConfigDict(frozen=True)

    topology: Topology
    articulation_points: frozenset[str]
    bridges: frozenset[tuple[str, str]]

    @classmethod
    def from_topology(cls, topology: Topology) -> _VisualizationContext:
        """Build visualization context from topology graph analysis."""
        graph = GraphBuilder().build(topology)
        analysis = GraphAnalyzer().analyze(graph)
        bridges = frozenset(
            _bridge_key(source, target) for source, target in analysis.bridges
        )
        return cls(
            topology=topology,
            articulation_points=frozenset(analysis.articulation_points),
            bridges=bridges,
        )


class _DotWriter:
    """Deterministic DOT writer for ChokePoint topologies."""

    def __init__(
        self,
        *,
        layout: VisualizationLayout,
        context: _VisualizationContext,
    ) -> None:
        self._layout = layout
        self._context = context

    def write(self) -> str:
        """Write DOT source."""
        lines = [
            "graph ChokePoint {",
            *_indent(self._graph_attributes()),
            "",
        ]
        if self._layout == VisualizationLayout.CLUSTER:
            lines.extend(self._cluster_nodes())
        else:
            lines.extend(self._flat_nodes())

        lines.extend(self._edges())
        lines.extend(self._legend())
        lines.append("}")
        return "\n".join(lines) + "\n"

    def _graph_attributes(self) -> list[str]:
        """Return graph-level DOT attributes."""
        attributes = {
            "bgcolor": GraphvizVisualizer.BACKGROUND_COLOR,
            "compound": "true",
            "concentrate": "true",
            "fontname": "Inter, Arial, sans-serif",
            "label": "ChokePoint Infrastructure Dependency Graph",
            "labelloc": "t",
            "nodesep": "0.45",
            "overlap": "false",
            "pad": "0.35",
            "rankdir": "LR",
            "ranksep": "0.7",
            "splines": "spline",
        }
        if self._layout == VisualizationLayout.RADIAL:
            attributes.update({"layout": "twopi", "rankdir": "TB", "root": "root"})
        elif self._layout == VisualizationLayout.CLUSTER:
            attributes.update({"clusterrank": "local"})
        else:
            attributes.update({"layout": "dot"})

        return [f"{key}={_quote(value)};" for key, value in attributes.items()]

    def _flat_nodes(self) -> list[str]:
        """Return node lines without clusters."""
        return [
            f"  {_node_id(node.id)} {_attributes(self._node_attributes(node))};"
            for node in self._sorted_nodes()
        ]

    def _cluster_nodes(self) -> list[str]:
        """Return node lines grouped by provider clusters."""
        lines: list[str] = []
        provider_nodes: dict[str, list[Node]] = {}
        for node in self._sorted_nodes():
            provider_nodes.setdefault(node.provider, []).append(node)

        for provider, nodes in sorted(provider_nodes.items()):
            cluster_name = f"cluster_{_safe_identifier(provider)}"
            lines.extend(
                [
                    f"  subgraph {_node_id(cluster_name)} {{",
                    f"    label={_quote(provider.upper())};",
                    '    color="#d1d5db";',
                    '    style="rounded";',
                ]
            )
            for node in nodes:
                attributes = _attributes(self._node_attributes(node))
                lines.append(f"    {_node_id(node.id)} {attributes};")
            lines.append("  }")
            lines.append("")
        return lines

    def _edges(self) -> list[str]:
        """Return edge lines."""
        lines: list[str] = []
        for edge in sorted(
            self._context.topology.edges,
            key=lambda item: (item.source, item.target, item.relationship.value),
        ):
            color = (
                GraphvizVisualizer.BRIDGE_COLOR
                if _bridge_key(edge.source, edge.target) in self._context.bridges
                else GraphvizVisualizer.DEFAULT_EDGE_COLOR
            )
            penwidth = "2.5" if color == GraphvizVisualizer.BRIDGE_COLOR else "1.2"
            attributes = {
                "color": color,
                "fontname": "Inter, Arial, sans-serif",
                "fontsize": "10",
                "label": edge.relationship.value,
                "penwidth": penwidth,
            }
            lines.append(
                f"  {_node_id(edge.source)} -- {_node_id(edge.target)} "
                f"{_attributes(attributes)};"
            )
        if lines:
            lines.append("")
        return lines

    def _legend(self) -> list[str]:
        """Return DOT legend cluster."""
        legend_items = (
            ("Articulation Points", GraphvizVisualizer.ARTICULATION_COLOR),
            ("Bridges", GraphvizVisualizer.BRIDGE_COLOR),
            ("Cloud Providers", GraphvizVisualizer.CLOUD_COLOR),
            ("Applications", GraphvizVisualizer.APPLICATION_COLOR),
            ("Infrastructure", GraphvizVisualizer.INFRASTRUCTURE_COLOR),
        )
        lines = [
            "  subgraph cluster_legend {",
            '    label="Legend";',
            '    color="#d1d5db";',
            '    style="rounded";',
        ]
        previous_id = ""
        for index, (label, color) in enumerate(legend_items):
            legend_id = f"legend_{index}"
            lines.append(
                f"    {_node_id(legend_id)} "
                f"{_attributes(_legend_attributes(label, color))};"
            )
            if previous_id:
                lines.append(
                    f"    {_node_id(previous_id)} -- {_node_id(legend_id)} "
                    '[style="invis"];'
                )
            previous_id = legend_id
        lines.extend(["  }", ""])
        return lines

    def _node_attributes(self, node: Node) -> Mapping[str, str]:
        """Return DOT attributes for a node."""
        fillcolor = self._node_color(node)
        border_color = (
            GraphvizVisualizer.ARTICULATION_COLOR
            if node.id in self._context.articulation_points
            else "#374151"
        )
        return {
            "color": border_color,
            "fillcolor": fillcolor,
            "fontcolor": "#111827",
            "fontname": "Inter, Arial, sans-serif",
            "fontsize": "11",
            "label": f"{node.name}\\n{node.node_type.value}\\n{node.provider}",
            "penwidth": (
                "3.0" if node.id in self._context.articulation_points else "1.2"
            ),
            "shape": "box",
            "style": "rounded,filled",
        }

    def _node_color(self, node: Node) -> str:
        """Return fill color for a node."""
        if node.id in self._context.articulation_points:
            return GraphvizVisualizer.ARTICULATION_COLOR
        if _is_cloud_provider(node):
            return GraphvizVisualizer.CLOUD_COLOR
        if node.node_type == NodeType.SERVICE:
            return GraphvizVisualizer.APPLICATION_COLOR
        return GraphvizVisualizer.INFRASTRUCTURE_COLOR

    def _sorted_nodes(self) -> list[Node]:
        """Return nodes in deterministic order."""
        return sorted(self._context.topology.nodes.values(), key=lambda node: node.id)


def _legend_attributes(label: str, color: str) -> Mapping[str, str]:
    """Return legend node attributes."""
    return {
        "fillcolor": color,
        "fontcolor": "#111827",
        "fontname": "Inter, Arial, sans-serif",
        "fontsize": "10",
        "label": label,
        "shape": "box",
        "style": "rounded,filled",
    }


def _format_from_suffix(path: Path) -> VisualizationFormat:
    """Infer output format from a file suffix."""
    suffix = path.suffix.lower().lstrip(".")
    try:
        return VisualizationFormat(suffix)
    except ValueError as error:
        message = f"unsupported visualization file suffix: {path.suffix!r}"
        raise ValueError(message) from error


def _engine_for_layout(layout: VisualizationLayout) -> str:
    """Return Graphviz engine for a layout."""
    if layout == VisualizationLayout.RADIAL:
        return "twopi"
    return "dot"


def _bridge_key(source: str, target: str) -> tuple[str, str]:
    """Return deterministic bridge key."""
    left, right = sorted((source, target))
    return left, right


def _is_cloud_provider(node: Node) -> bool:
    """Return whether a node represents a cloud or edge provider."""
    provider = node.provider.lower()
    node_id = node.id.lower()
    return node.node_type == NodeType.EXTERNAL and (
        provider in GraphvizVisualizer.CLOUD_PROVIDERS
        or node_id in GraphvizVisualizer.CLOUD_PROVIDERS
    )


def _attributes(attributes: Mapping[str, str]) -> str:
    """Format DOT attributes."""
    body = ", ".join(
        f"{key}={_quote(value)}" for key, value in sorted(attributes.items())
    )
    return f"[{body}]"


def _quote(value: str) -> str:
    """Quote and escape DOT values."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _node_id(value: str) -> str:
    """Return a quoted DOT node identifier."""
    return _quote(value)


def _safe_identifier(value: str) -> str:
    """Return a simple identifier fragment for cluster ids."""
    return "".join(character if character.isalnum() else "_" for character in value)


def _indent(lines: Iterable[str]) -> list[str]:
    """Indent DOT lines."""
    return [f"  {line}" for line in lines]
