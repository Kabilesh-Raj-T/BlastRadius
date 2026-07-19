"""Core graph data model for ChokePoint."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
type Metadata = dict[str, JsonValue]
type NeighborDirection = Literal["incoming", "outgoing", "both"]


class NodeType(StrEnum):
    """Supported infrastructure node categories."""

    SERVICE = "service"
    DATABASE = "database"
    DNS = "dns"
    CACHE = "cache"
    QUEUE = "queue"
    LOAD_BALANCER = "load_balancer"
    STORAGE = "storage"
    NETWORK = "network"
    COMPUTE = "compute"
    IDENTITY = "identity"
    SECRET = "secret"
    EXTERNAL = "external"


class Relationship(StrEnum):
    """Directed relationship categories between infrastructure nodes."""

    DEPENDS_ON = "depends_on"
    CONNECTS_TO = "connects_to"
    CONTAINS = "contains"
    HOSTS = "hosts"
    ROUTES_TO = "routes_to"
    READS_FROM = "reads_from"
    WRITES_TO = "writes_to"
    PUBLISHES_TO = "publishes_to"
    SUBSCRIBES_TO = "subscribes_to"
    AUTHENTICATES_WITH = "authenticates_with"
    REPLICATES_TO = "replicates_to"


class Node(BaseModel):
    """Infrastructure entity represented as a graph node."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    node_type: NodeType
    metadata: Metadata = Field(default_factory=dict)


class Edge(BaseModel):
    """Directed relationship between two nodes in a topology."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    relationship: Relationship
    metadata: Metadata = Field(default_factory=dict)


class Topology(BaseModel):
    """Mutable aggregate for a validated infrastructure dependency graph."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    nodes: dict[str, Node] = Field(default_factory=dict)
    edges: list[Edge] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_topology(self) -> Self:
        """Validate internal graph references and unique edge identities.

        Returns:
            The validated topology instance.

        Raises:
            ValueError: If node keys, edge endpoints, or edge identities are invalid.
        """
        for node_id, node in self.nodes.items():
            if node.id != node_id:
                message = f"node key {node_id!r} does not match node id {node.id!r}"
                raise ValueError(message)

        edge_keys: set[tuple[str, str, Relationship]] = set()
        for edge in self.edges:
            self._validate_edge_endpoints(edge)
            edge_key = self._edge_key(edge)
            if edge_key in edge_keys:
                message = (
                    "duplicate edge for "
                    f"{edge.source!r}, {edge.target!r}, {edge.relationship.value!r}"
                )
                raise ValueError(message)
            edge_keys.add(edge_key)

        return self

    def add_node(self, node: Node) -> Node:
        """Add a node to the topology.

        Args:
            node: Node to add.

        Returns:
            The added node.

        Raises:
            ValueError: If a node with the same id already exists.
        """
        if node.id in self.nodes:
            message = f"node {node.id!r} already exists"
            raise ValueError(message)

        self.nodes[node.id] = node
        return node

    def add_edge(self, edge: Edge) -> Edge:
        """Add an edge to the topology.

        Args:
            edge: Edge to add.

        Returns:
            The added edge.

        Raises:
            ValueError: If endpoints are missing or the edge already exists.
        """
        self._validate_edge_endpoints(edge)
        edge_key = self._edge_key(edge)
        if any(self._edge_key(existing) == edge_key for existing in self.edges):
            message = (
                "edge already exists for "
                f"{edge.source!r}, {edge.target!r}, {edge.relationship.value!r}"
            )
            raise ValueError(message)

        self.edges.append(edge)
        return edge

    def remove_node(self, node_id: str) -> Node:
        """Remove a node and all incident edges.

        Args:
            node_id: Identifier of the node to remove.

        Returns:
            The removed node.

        Raises:
            KeyError: If the node does not exist.
        """
        if node_id not in self.nodes:
            message = f"node {node_id!r} does not exist"
            raise KeyError(message)

        node = self.nodes.pop(node_id)
        self.edges = [
            edge for edge in self.edges if node_id not in (edge.source, edge.target)
        ]
        return node

    def remove_edge(self, source: str, target: str, relationship: Relationship) -> Edge:
        """Remove an edge by its directed relationship identity.

        Args:
            source: Source node id.
            target: Target node id.
            relationship: Relationship category.

        Returns:
            The removed edge.

        Raises:
            KeyError: If the edge does not exist.
        """
        edge_key = (source, target, relationship)
        for index, edge in enumerate(self.edges):
            if self._edge_key(edge) == edge_key:
                return self.edges.pop(index)

        message = (
            f"edge does not exist for {source!r}, "
            f"{target!r}, {relationship.value!r}"
        )
        raise KeyError(message)

    def neighbors(
        self,
        node_id: str,
        *,
        direction: NeighborDirection = "outgoing",
        relationship: Relationship | None = None,
    ) -> tuple[Node, ...]:
        """Return adjacent nodes for a node.

        Args:
            node_id: Node id to inspect.
            direction: Edge direction to follow.
            relationship: Optional relationship category filter.

        Returns:
            Adjacent nodes in edge insertion order, without duplicates.

        Raises:
            KeyError: If the node does not exist.
            ValueError: If the direction is invalid.
        """
        self._validate_node_exists(node_id)
        if direction not in {"incoming", "outgoing", "both"}:
            message = f"invalid neighbor direction: {direction!r}"
            raise ValueError(message)

        neighbor_ids: list[str] = []

        for edge in self.edges:
            if relationship is not None and edge.relationship != relationship:
                continue

            if direction in {"outgoing", "both"} and edge.source == node_id:
                neighbor_ids.append(edge.target)
            if direction in {"incoming", "both"} and edge.target == node_id:
                neighbor_ids.append(edge.source)

        return tuple(self.nodes[id_] for id_ in dict.fromkeys(neighbor_ids))

    def find(
        self,
        *,
        node_id: str | None = None,
        name: str | None = None,
        provider: str | None = None,
        node_type: NodeType | None = None,
    ) -> tuple[Node, ...]:
        """Find nodes matching all provided criteria.

        Args:
            node_id: Optional exact node id.
            name: Optional exact node name.
            provider: Optional exact provider name.
            node_type: Optional node category.

        Returns:
            Matching nodes in insertion order.

        Raises:
            ValueError: If no search criteria are provided.
        """
        criteria = (node_id, name, provider, node_type)
        if all(value is None for value in criteria):
            message = "at least one search criterion is required"
            raise ValueError(message)

        return tuple(
            node
            for node in self.nodes.values()
            if (node_id is None or node.id == node_id)
            and (name is None or node.name == name)
            and (provider is None or node.provider == provider)
            and (node_type is None or node.node_type == node_type)
        )

    def export_json(self) -> str:
        """Export the topology to a JSON string.

        Returns:
            JSON representation of the topology.
        """
        return self.model_dump_json(indent=2)

    @classmethod
    def import_json(cls, payload: str) -> Self:
        """Import a topology from a JSON string.

        Args:
            payload: JSON representation produced by `export_json`.

        Returns:
            Validated topology instance.
        """
        return cls.model_validate_json(payload)

    def _validate_node_exists(self, node_id: str) -> None:
        """Validate that a node id exists in the topology."""
        if node_id not in self.nodes:
            message = f"node {node_id!r} does not exist"
            raise KeyError(message)

    def _validate_edge_endpoints(self, edge: Edge) -> None:
        """Validate that an edge references existing endpoint nodes."""
        missing_nodes = [
            node_id
            for node_id in (edge.source, edge.target)
            if node_id not in self.nodes
        ]
        if missing_nodes:
            message = f"edge references missing node ids: {missing_nodes}"
            raise ValueError(message)

    @staticmethod
    def _edge_key(edge: Edge) -> tuple[str, str, Relationship]:
        """Return the identity key for a directed edge."""
        return edge.source, edge.target, edge.relationship
