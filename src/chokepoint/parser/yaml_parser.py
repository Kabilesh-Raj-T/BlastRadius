"""YAML topology parser for ChokePoint."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, cast

import yaml
from pydantic import ValidationError

from chokepoint.models import Edge, Node, NodeType, Relationship, Topology
from chokepoint.models.topology import JsonValue, Metadata


class TopologyParseError(ValueError):
    """Raised when a YAML topology document cannot be parsed."""

    def __init__(self, message: str, *, source: str | None = None) -> None:
        """Create a parser error.

        Args:
            message: Human-readable parse failure.
            source: Optional source path or label.
        """
        self.message = message
        self.source = source
        detail = f"{source}: {message}" if source else message
        super().__init__(detail)


@dataclass(frozen=True)
class SectionSpec:
    """Schema metadata for a supported YAML section."""

    node_type: NodeType
    default_provider: str
    simple_provider_from_id: bool = False


@dataclass(frozen=True)
class PendingEdge:
    """Relationship edge discovered before all nodes are known."""

    source: str
    target: str
    relationship: Relationship
    path: str


@dataclass(frozen=True)
class ResourceSpec:
    """Normalized resource declaration from a YAML section."""

    node_id: str
    path: str
    name: str | None
    provider: str
    metadata: Metadata
    edges: tuple[PendingEdge, ...]


class YamlTopologyParser:
    """Parse ChokePoint YAML topology documents into `Topology` objects."""

    SECTIONS: ClassVar[dict[str, SectionSpec]] = {
        "clouds": SectionSpec(NodeType.EXTERNAL, "cloud", simple_provider_from_id=True),
        "dns": SectionSpec(NodeType.DNS, "dns", simple_provider_from_id=True),
        "identity": SectionSpec(
            NodeType.IDENTITY,
            "identity",
            simple_provider_from_id=True,
        ),
        "services": SectionSpec(NodeType.SERVICE, "application"),
        "service": SectionSpec(NodeType.SERVICE, "application"),
        "databases": SectionSpec(NodeType.DATABASE, "application"),
        "database": SectionSpec(NodeType.DATABASE, "application"),
        "caches": SectionSpec(NodeType.CACHE, "application"),
        "cache": SectionSpec(NodeType.CACHE, "application"),
        "queues": SectionSpec(NodeType.QUEUE, "application"),
        "queue": SectionSpec(NodeType.QUEUE, "application"),
        "storage": SectionSpec(NodeType.STORAGE, "application"),
        "networks": SectionSpec(NodeType.NETWORK, "network"),
        "network": SectionSpec(NodeType.NETWORK, "network"),
        "compute": SectionSpec(NodeType.COMPUTE, "compute"),
        "secrets": SectionSpec(NodeType.SECRET, "secret"),
        "secret": SectionSpec(NodeType.SECRET, "secret"),
        "external": SectionSpec(
            NodeType.EXTERNAL,
            "external",
            simple_provider_from_id=True,
        ),
    }

    RELATIONSHIP_FIELDS: ClassVar[dict[str, Relationship]] = {
        relationship.value: relationship for relationship in Relationship
    }
    RESOURCE_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"id", "name", "provider", "metadata", *RELATIONSHIP_FIELDS}
    )

    def parse_file(self, path: str | Path) -> Topology:
        """Parse a topology YAML file.

        Args:
            path: YAML file path.

        Returns:
            Parsed topology.

        Raises:
            TopologyParseError: If the file cannot be read, parsed, or validated.
        """
        source_path = Path(path)
        try:
            payload = source_path.read_text(encoding="utf-8")
        except OSError as error:
            message = f"unable to read topology file: {error.strerror or error}"
            raise TopologyParseError(message, source=str(source_path)) from error

        return self.parse_text(payload, source=str(source_path))

    def parse_text(self, payload: str, *, source: str = "<string>") -> Topology:
        """Parse a topology YAML document from text.

        Args:
            payload: YAML document text.
            source: Source label used in error messages.

        Returns:
            Parsed topology.

        Raises:
            TopologyParseError: If the document is malformed or invalid.
        """
        document = self._load_yaml(payload, source=source)
        raw_sections = self._as_mapping(document, path="$", source=source)
        self._reject_unknown_sections(raw_sections, source=source)

        topology = Topology()
        node_paths: dict[str, str] = {}
        pending_edges: list[PendingEdge] = []

        for section_name, section_value in raw_sections.items():
            section = self.SECTIONS[section_name]
            resources = self._parse_section(
                section_name,
                section,
                section_value,
                source=source,
            )

            for resource in resources:
                if resource.node_id in node_paths:
                    first_path = node_paths[resource.node_id]
                    message = (
                        f"duplicate node id {resource.node_id!r} at "
                        f"{resource.path}; first declared at {first_path}"
                    )
                    raise TopologyParseError(message, source=source)

                node = self._build_node(
                    resource,
                    section=section,
                    source=source,
                )
                topology.add_node(node)
                node_paths[node.id] = resource.path
                pending_edges.extend(resource.edges)

        if not topology.nodes:
            raise TopologyParseError(
                "topology must declare at least one node", source=source
            )

        self._add_edges(topology, pending_edges, source=source)
        return topology

    def _load_yaml(self, payload: str, *, source: str) -> object:
        """Load YAML text into Python values."""
        try:
            document = yaml.safe_load(payload)
        except yaml.YAMLError as error:
            message = self._format_yaml_error(error)
            raise TopologyParseError(message, source=source) from error

        if document is None:
            raise TopologyParseError("topology document is empty", source=source)

        return cast(object, document)

    def _parse_section(
        self,
        section_name: str,
        section: SectionSpec,
        value: object,
        *,
        source: str,
    ) -> tuple[ResourceSpec, ...]:
        """Parse one top-level section."""
        path = f"$.{section_name}"
        if isinstance(value, list):
            return tuple(
                self._parse_sequence_resource(
                    item,
                    section_name=section_name,
                    section=section,
                    path=f"{path}[{index}]",
                    source=source,
                )
                for index, item in enumerate(value)
            )

        mapping = self._as_mapping(value, path=path, source=source)
        if self._looks_like_resource_config(mapping):
            return (
                self._parse_resource_config(
                    section_name,
                    mapping,
                    section=section,
                    path=path,
                    source=source,
                ),
            )

        return tuple(
            self._parse_named_resource(
                resource_id,
                config,
                section=section,
                path=f"{path}.{resource_id}",
                source=source,
            )
            for resource_id, config in mapping.items()
        )

    def _parse_sequence_resource(
        self,
        value: object,
        *,
        section_name: str,
        section: SectionSpec,
        path: str,
        source: str,
    ) -> ResourceSpec:
        """Parse a resource from a YAML sequence."""
        if isinstance(value, str):
            node_id = self._validate_identifier(value, path=path, source=source)
            return ResourceSpec(
                node_id=node_id,
                path=path,
                name=None,
                provider=(
                    node_id
                    if section.simple_provider_from_id
                    else section.default_provider
                ),
                metadata={},
                edges=(),
            )

        mapping = self._as_mapping(value, path=path, source=source)
        if "id" not in mapping:
            message = f"{path}.id is required for object entries in {section_name!r}"
            raise TopologyParseError(message, source=source)

        node_id = self._validate_identifier(
            mapping["id"], path=f"{path}.id", source=source
        )
        return self._parse_resource_config(
            node_id,
            mapping,
            section=section,
            path=path,
            source=source,
        )

    def _parse_named_resource(
        self,
        resource_id: str,
        config: object,
        *,
        section: SectionSpec,
        path: str,
        source: str,
    ) -> ResourceSpec:
        """Parse a named resource from a YAML mapping."""
        node_id = self._validate_identifier(resource_id, path=path, source=source)
        mapping = self._as_mapping(config, path=path, source=source)
        if "id" in mapping and mapping["id"] != node_id:
            message = f"{path}.id must match mapping key {node_id!r}"
            raise TopologyParseError(message, source=source)

        return self._parse_resource_config(
            node_id,
            mapping,
            section=section,
            path=path,
            source=source,
        )

    def _parse_resource_config(
        self,
        node_id: str,
        mapping: Mapping[str, object],
        *,
        section: SectionSpec,
        path: str,
        source: str,
    ) -> ResourceSpec:
        """Parse a resource configuration mapping."""
        unknown_fields = sorted(set(mapping) - self.RESOURCE_FIELDS)
        if unknown_fields:
            message = f"{path} has unsupported field(s): {', '.join(unknown_fields)}"
            raise TopologyParseError(message, source=source)

        name = self._optional_string(
            mapping.get("name"), path=f"{path}.name", source=source
        )
        provider = self._provider(
            mapping.get("provider"),
            section=section,
            node_id=node_id,
            path=f"{path}.provider",
            source=source,
        )
        metadata = self._metadata(
            mapping.get("metadata"), path=f"{path}.metadata", source=source
        )
        edges = self._relationship_edges(node_id, mapping, path=path, source=source)

        return ResourceSpec(
            node_id=node_id,
            path=path,
            name=name,
            provider=provider,
            metadata=metadata,
            edges=edges,
        )

    def _build_node(
        self,
        resource: ResourceSpec,
        *,
        section: SectionSpec,
        source: str,
    ) -> Node:
        """Build a validated `Node` from a resource declaration."""
        try:
            return Node(
                id=resource.node_id,
                name=resource.name or resource.node_id,
                provider=resource.provider,
                node_type=section.node_type,
                metadata=resource.metadata,
            )
        except ValidationError as error:
            message = f"{resource.path}: invalid node {resource.node_id!r}: {error}"
            raise TopologyParseError(message, source=source) from error

    def _add_edges(
        self,
        topology: Topology,
        pending_edges: list[PendingEdge],
        *,
        source: str,
    ) -> None:
        """Add validated relationship edges to a topology."""
        for pending_edge in pending_edges:
            if pending_edge.target not in topology.nodes:
                message = (
                    f"{pending_edge.path}: dependency target "
                    f"{pending_edge.target!r} is not defined"
                )
                raise TopologyParseError(message, source=source)

            try:
                topology.add_edge(
                    Edge(
                        source=pending_edge.source,
                        target=pending_edge.target,
                        relationship=pending_edge.relationship,
                    )
                )
            except ValueError as error:
                message = f"{pending_edge.path}: invalid relationship: {error}"
                raise TopologyParseError(message, source=source) from error

    def _relationship_edges(
        self,
        source_node_id: str,
        mapping: Mapping[str, object],
        *,
        path: str,
        source: str,
    ) -> tuple[PendingEdge, ...]:
        """Parse relationship fields from a resource mapping."""
        edges: list[PendingEdge] = []
        for field_name, relationship in self.RELATIONSHIP_FIELDS.items():
            if field_name not in mapping:
                continue

            values = mapping[field_name]
            if not isinstance(values, list):
                message = f"{path}.{field_name} must be a list of node ids"
                raise TopologyParseError(message, source=source)

            for index, raw_target in enumerate(values):
                target = self._validate_identifier(
                    raw_target,
                    path=f"{path}.{field_name}[{index}]",
                    source=source,
                )
                edges.append(
                    PendingEdge(
                        source=source_node_id,
                        target=target,
                        relationship=relationship,
                        path=f"{path}.{field_name}[{index}]",
                    )
                )

        return tuple(edges)

    def _reject_unknown_sections(
        self,
        raw_sections: Mapping[str, object],
        *,
        source: str,
    ) -> None:
        """Reject unknown top-level YAML sections."""
        unknown_sections = sorted(set(raw_sections) - set(self.SECTIONS))
        if unknown_sections:
            allowed = ", ".join(sorted(self.SECTIONS))
            message = (
                "unsupported top-level section(s): "
                f"{', '.join(unknown_sections)}. Allowed sections: {allowed}"
            )
            raise TopologyParseError(message, source=source)

    def _as_mapping(
        self,
        value: object,
        *,
        path: str,
        source: str,
    ) -> Mapping[str, object]:
        """Validate and return a string-keyed mapping."""
        if not isinstance(value, Mapping):
            message = f"{path} must be a mapping"
            raise TopologyParseError(message, source=source)

        for key in value:
            if not isinstance(key, str) or not key.strip():
                message = f"{path} keys must be non-empty strings"
                raise TopologyParseError(message, source=source)

        return cast(Mapping[str, object], value)

    def _looks_like_resource_config(self, mapping: Mapping[str, object]) -> bool:
        """Return whether a mapping is a single resource config."""
        return bool(set(mapping) & self.RESOURCE_FIELDS)

    def _provider(
        self,
        value: object,
        *,
        section: SectionSpec,
        node_id: str,
        path: str,
        source: str,
    ) -> str:
        """Return the provider for a resource."""
        if value is None:
            return (
                node_id if section.simple_provider_from_id else section.default_provider
            )

        return self._validate_identifier(value, path=path, source=source)

    def _metadata(self, value: object, *, path: str, source: str) -> Metadata:
        """Return metadata for a resource."""
        if value is None:
            return {}

        mapping = self._as_mapping(value, path=path, source=source)
        return {
            key: self._json_value(item, path=f"{path}.{key}", source=source)
            for key, item in mapping.items()
        }

    def _json_value(self, value: object, *, path: str, source: str) -> JsonValue:
        """Validate JSON-compatible metadata values."""
        if value is None or isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, list):
            return [
                self._json_value(item, path=f"{path}[{index}]", source=source)
                for index, item in enumerate(value)
            ]
        if isinstance(value, Mapping):
            metadata = self._as_mapping(value, path=path, source=source)
            return {
                key: self._json_value(item, path=f"{path}.{key}", source=source)
                for key, item in metadata.items()
            }

        message = f"{path} must be a JSON-compatible metadata value"
        raise TopologyParseError(message, source=source)

    def _optional_string(
        self,
        value: object,
        *,
        path: str,
        source: str,
    ) -> str | None:
        """Validate an optional non-empty string."""
        if value is None:
            return None
        return self._validate_identifier(value, path=path, source=source)

    def _validate_identifier(self, value: object, *, path: str, source: str) -> str:
        """Validate a non-empty string identifier."""
        if not isinstance(value, str) or not value.strip():
            message = f"{path} must be a non-empty string"
            raise TopologyParseError(message, source=source)
        return value.strip()

    def _format_yaml_error(self, error: yaml.YAMLError) -> str:
        """Format low-level YAML parser errors with location details."""
        problem = getattr(error, "problem", None)
        mark = getattr(error, "problem_mark", None)
        if mark is None:
            return f"malformed YAML: {error}"

        line = mark.line + 1
        column = mark.column + 1
        detail = str(problem or error)
        return f"malformed YAML at line {line}, column {column}: {detail}"


def parse_topology_yaml_file(path: str | Path) -> Topology:
    """Parse a topology YAML file.

    Args:
        path: YAML file path.

    Returns:
        Parsed topology.
    """
    return YamlTopologyParser().parse_file(path)


def parse_topology_yaml_text(payload: str, *, source: str = "<string>") -> Topology:
    """Parse topology YAML text.

    Args:
        payload: YAML document text.
        source: Source label used in error messages.

    Returns:
        Parsed topology.
    """
    return YamlTopologyParser().parse_text(payload, source=source)
