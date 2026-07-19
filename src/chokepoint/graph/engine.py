"""NetworkX graph construction and analysis for ChokePoint."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar, TypeGuard

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field

from chokepoint.models import Edge, Node, Relationship, Topology
from chokepoint.models.topology import Metadata


class GraphValidationReport(BaseModel):
    """Validation result for a NetworkX graph produced by ChokePoint."""

    model_config = ConfigDict(frozen=True)

    is_valid: bool
    issues: tuple[str, ...] = ()


class AlgorithmComplexity(BaseModel):
    """Algorithmic complexity profile for graph analysis operations."""

    model_config = ConfigDict(frozen=True)

    algorithm: str
    time_complexity: str
    space_complexity: str
    notes: str


class AnalysisReport(BaseModel):
    """Graph analysis result for an infrastructure topology."""

    model_config = ConfigDict(frozen=True)

    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    is_connected: bool
    connected_components: tuple[tuple[str, ...], ...]
    articulation_points: tuple[str, ...]
    bridges: tuple[tuple[str, str], ...]
    betweenness_centrality: dict[str, float]
    degree_centrality: dict[str, float]
    cycles: tuple[tuple[str, ...], ...]
    validation: GraphValidationReport


class GraphBuilder:
    """Build undirected NetworkX graphs from ChokePoint topologies."""

    NODE_ATTR: ClassVar[str] = "node"
    EDGE_ATTR: ClassVar[str] = "topology_edges"
    RELATIONSHIPS_ATTR: ClassVar[str] = "relationships"
    EDGE_METADATA_ATTR: ClassVar[str] = "edge_metadata"

    def build(self, topology: Topology) -> nx.Graph:
        """Build a NetworkX graph from a topology.

        Args:
            topology: Validated topology to convert.

        Returns:
            Undirected NetworkX graph with ChokePoint model attributes.

        Raises:
            ValueError: If the topology has invalid in-place mutations.
        """
        validated_topology = Topology.model_validate(topology.model_dump())

        graph = nx.Graph()
        graph.graph["source"] = "chokepoint.topology"

        for node in validated_topology.nodes.values():
            graph.add_node(
                node.id,
                node=node,
                name=node.name,
                provider=node.provider,
                node_type=node.node_type,
                metadata=dict(node.metadata),
            )

        for edge in validated_topology.edges:
            self._add_edge(graph, edge)

        return graph

    def _add_edge(self, graph: nx.Graph, edge: Edge) -> None:
        """Add a topology edge while preserving collapsed edge metadata."""
        if graph.has_edge(edge.source, edge.target):
            attributes = graph.edges[edge.source, edge.target]
            topology_edges = _edge_tuple_attribute(attributes, self.EDGE_ATTR)
            relationships = _relationship_tuple_attribute(
                attributes, self.RELATIONSHIPS_ATTR
            )
            edge_metadata = _metadata_tuple_attribute(
                attributes, self.EDGE_METADATA_ATTR
            )

            attributes[self.EDGE_ATTR] = (*topology_edges, edge)
            attributes[self.RELATIONSHIPS_ATTR] = (*relationships, edge.relationship)
            attributes[self.EDGE_METADATA_ATTR] = (*edge_metadata, dict(edge.metadata))
            return

        graph.add_edge(
            edge.source,
            edge.target,
            topology_edges=(edge,),
            relationships=(edge.relationship,),
            edge_metadata=(dict(edge.metadata),),
        )


class GraphAnalyzer:
    """Analyze ChokePoint NetworkX dependency graphs."""

    _COMPLEXITY_PROFILE: ClassVar[tuple[AlgorithmComplexity, ...]] = (
        AlgorithmComplexity(
            algorithm="graph_build",
            time_complexity="O(V + E)",
            space_complexity="O(V + E)",
            notes="Adds every topology node and edge once.",
        ),
        AlgorithmComplexity(
            algorithm="graph_validation",
            time_complexity="O(V + E + R)",
            space_complexity="O(V + E)",
            notes="Validates graph attributes and preserved topology edge records.",
        ),
        AlgorithmComplexity(
            algorithm="connected_components",
            time_complexity="O(V + E)",
            space_complexity="O(V)",
            notes="Uses depth-first or breadth-first traversal over the graph.",
        ),
        AlgorithmComplexity(
            algorithm="articulation_points",
            time_complexity="O(V + E)",
            space_complexity="O(V)",
            notes="Uses low-link depth-first search.",
        ),
        AlgorithmComplexity(
            algorithm="bridges",
            time_complexity="O(V + E)",
            space_complexity="O(V)",
            notes="Uses low-link depth-first search.",
        ),
        AlgorithmComplexity(
            algorithm="betweenness_centrality",
            time_complexity="O(V * E)",
            space_complexity="O(V + E)",
            notes="Uses unweighted Brandes centrality.",
        ),
        AlgorithmComplexity(
            algorithm="degree_centrality",
            time_complexity="O(V + E)",
            space_complexity="O(V)",
            notes="Normalizes degree by the maximum possible degree.",
        ),
        AlgorithmComplexity(
            algorithm="cycle_detection",
            time_complexity="O(V + E)",
            space_complexity="O(V + C)",
            notes="Computes a cycle basis; C is the number of cycles returned.",
        ),
    )

    def analyze(self, graph: nx.Graph) -> AnalysisReport:
        """Analyze a validated ChokePoint graph.

        Args:
            graph: NetworkX graph produced by `GraphBuilder`.

        Returns:
            Immutable analysis report.

        Raises:
            ValueError: If graph validation fails.
        """
        validation = self.validate(graph)
        if not validation.is_valid:
            message = "invalid ChokePoint graph: " + "; ".join(validation.issues)
            raise ValueError(message)

        connected_components = _connected_components(graph)
        cycles = _cycles(graph)

        return AnalysisReport(
            node_count=graph.number_of_nodes(),
            edge_count=graph.number_of_edges(),
            is_connected=(
                len(connected_components) == 1 if graph.number_of_nodes() else False
            ),
            connected_components=connected_components,
            articulation_points=tuple(sorted(nx.articulation_points(graph))),
            bridges=_bridges(graph),
            betweenness_centrality=_centrality(nx.betweenness_centrality(graph)),
            degree_centrality=_centrality(nx.degree_centrality(graph)),
            cycles=cycles,
            validation=validation,
        )

    def validate(self, graph: nx.Graph) -> GraphValidationReport:
        """Validate that a NetworkX graph matches ChokePoint expectations.

        Args:
            graph: Graph to validate.

        Returns:
            Validation report containing every detected issue.
        """
        issues: list[str] = []

        if graph.is_directed():
            issues.append("graph must be undirected")
        if graph.is_multigraph():
            issues.append("graph must not be a multigraph")

        self._validate_nodes(graph, issues)
        self._validate_edges(graph, issues)

        return GraphValidationReport(is_valid=not issues, issues=tuple(issues))

    def complexity_profile(self) -> tuple[AlgorithmComplexity, ...]:
        """Return algorithmic complexity benchmarks for the graph engine.

        Returns:
            Complexity profile entries for construction, validation, and analysis.
        """
        return self._COMPLEXITY_PROFILE

    def _validate_nodes(self, graph: nx.Graph, issues: list[str]) -> None:
        """Validate ChokePoint node attributes."""
        for node_id, attributes in graph.nodes(data=True):
            if not isinstance(node_id, str) or not node_id:
                issues.append(f"node id must be a non-empty string: {node_id!r}")
                continue

            node = attributes.get(GraphBuilder.NODE_ATTR)
            if not isinstance(node, Node):
                issues.append(f"node {node_id!r} is missing a Node model")
                continue

            if node.id != node_id:
                issues.append(
                    f"node {node_id!r} has mismatched Node model id {node.id!r}"
                )

    def _validate_edges(self, graph: nx.Graph, issues: list[str]) -> None:
        """Validate ChokePoint edge attributes."""
        for source, target, attributes in graph.edges(data=True):
            if source == target:
                issues.append(f"self-loop edge is not supported: {source!r}")

            topology_edges = attributes.get(GraphBuilder.EDGE_ATTR)
            if not _is_edge_tuple(topology_edges):
                issues.append(f"edge {source!r}-{target!r} is missing Edge models")
                continue

            relationships = attributes.get(GraphBuilder.RELATIONSHIPS_ATTR)
            if not _is_relationship_tuple(relationships):
                issues.append(f"edge {source!r}-{target!r} is missing relationships")
                continue

            if len(topology_edges) != len(relationships):
                issues.append(
                    f"edge {source!r}-{target!r} has mismatched edge attributes"
                )

            edge_metadata = attributes.get(GraphBuilder.EDGE_METADATA_ATTR)
            if not _is_metadata_tuple(edge_metadata):
                issues.append(f"edge {source!r}-{target!r} is missing edge metadata")
            elif len(topology_edges) != len(edge_metadata):
                issues.append(
                    f"edge {source!r}-{target!r} has mismatched edge metadata"
                )

            endpoint_ids = {source, target}
            for edge in topology_edges:
                if {edge.source, edge.target} != endpoint_ids:
                    issues.append(
                        f"edge {source!r}-{target!r} contains mismatched topology edge"
                    )

            if tuple(edge.relationship for edge in topology_edges) != relationships:
                issues.append(
                    f"edge {source!r}-{target!r} has inconsistent relationships"
                )


def _connected_components(graph: nx.Graph) -> tuple[tuple[str, ...], ...]:
    """Return connected components in deterministic order."""
    components = [
        tuple(sorted(component)) for component in nx.connected_components(graph)
    ]
    return tuple(
        sorted(components, key=lambda component: (component[0], len(component)))
    )


def _bridges(graph: nx.Graph) -> tuple[tuple[str, str], ...]:
    """Return bridges with deterministic undirected endpoint ordering."""
    bridges = [tuple(sorted((source, target))) for source, target in nx.bridges(graph)]
    return tuple(sorted(bridges))


def _cycles(graph: nx.Graph) -> tuple[tuple[str, ...], ...]:
    """Return a deterministic undirected cycle basis."""
    cycles = [_canonical_cycle(cycle) for cycle in nx.cycle_basis(graph)]
    return tuple(sorted(cycles, key=lambda cycle: (len(cycle), cycle)))


def _canonical_cycle(cycle: list[str]) -> tuple[str, ...]:
    """Rotate and orient a cycle into deterministic lexical order."""
    if not cycle:
        return ()

    cycle_tuple = tuple(cycle)
    rotations = _cycle_rotations(cycle_tuple)
    reversed_rotations = _cycle_rotations(tuple(reversed(cycle_tuple)))
    return min((*rotations, *reversed_rotations))


def _cycle_rotations(cycle: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    """Return every rotation of a cycle."""
    return tuple(cycle[index:] + cycle[:index] for index in range(len(cycle)))


def _centrality(values: Mapping[object, float]) -> dict[str, float]:
    """Convert NetworkX centrality mappings to string-keyed dictionaries."""
    return {
        str(node_id): score
        for node_id, score in sorted(values.items(), key=lambda item: str(item[0]))
    }


def _edge_tuple_attribute(
    attributes: Mapping[str, object],
    name: str,
) -> tuple[Edge, ...]:
    """Return a tuple of edge models produced by this builder."""
    value = attributes[name]
    if not _is_edge_tuple(value):
        message = f"invalid graph edge attribute {name!r}"
        raise TypeError(message)
    return value


def _relationship_tuple_attribute(
    attributes: Mapping[str, object],
    name: str,
) -> tuple[Relationship, ...]:
    """Return a tuple of relationships produced by this builder."""
    value = attributes[name]
    if not _is_relationship_tuple(value):
        message = f"invalid graph edge attribute {name!r}"
        raise TypeError(message)
    return value


def _metadata_tuple_attribute(
    attributes: Mapping[str, object],
    name: str,
) -> tuple[Metadata, ...]:
    """Return a tuple of metadata mappings produced by this builder."""
    value = attributes[name]
    if not _is_metadata_tuple(value):
        message = f"invalid graph edge attribute {name!r}"
        raise TypeError(message)
    return value


def _is_edge_tuple(value: object) -> TypeGuard[tuple[Edge, ...]]:
    """Return whether a value is a non-empty tuple of topology edges."""
    return (
        isinstance(value, tuple)
        and bool(value)
        and all(isinstance(item, Edge) for item in value)
    )


def _is_relationship_tuple(value: object) -> TypeGuard[tuple[Relationship, ...]]:
    """Return whether a value is a non-empty tuple of relationships."""
    return (
        isinstance(value, tuple)
        and bool(value)
        and all(isinstance(item, Relationship) for item in value)
    )


def _is_metadata_tuple(value: object) -> TypeGuard[tuple[Metadata, ...]]:
    """Return whether a value is a non-empty tuple of metadata mappings."""
    return (
        isinstance(value, tuple)
        and bool(value)
        and all(isinstance(item, dict) for item in value)
    )
