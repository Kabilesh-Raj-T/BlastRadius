"""Docker Compose ingestion for ChokePoint."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import yaml

from chokepoint.models import Edge, Node, NodeType, Relationship, Topology

COMPOSE_DEFAULT_PATTERN = re.compile(r"^\$\{[^}:]+(?::-|-)(?P<default>[^}]+)\}$")


class DockerComposeParseError(ValueError):
    """Raised when a Docker Compose file cannot be parsed."""

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


class DockerComposeParser:
    """Parse a basic Docker Compose file into a topology graph."""

    def parse_file(self, path: str | Path) -> Topology:
        """Parse a Docker Compose YAML file.

        Args:
            path: Compose file path.

        Returns:
            Parsed topology.
        """
        source_path = Path(path)
        try:
            payload = source_path.read_text(encoding="utf-8")
        except OSError as error:
            message = f"unable to read Docker Compose file: {error.strerror or error}"
            raise DockerComposeParseError(message, source=str(source_path)) from error
        return self.parse_text(payload, source=str(source_path))

    def parse_text(self, payload: str, *, source: str = "<string>") -> Topology:
        """Parse Docker Compose YAML text.

        Args:
            payload: Compose YAML text.
            source: Source label used in errors and metadata.

        Returns:
            Parsed topology.
        """
        document = _load_yaml_mapping(payload, source=source)
        services = _optional_mapping(document.get("services"))
        topology = Topology()

        for service_name, raw_service in services.items():
            config = _optional_mapping(raw_service)
            topology.add_node(
                Node(
                    id=_service_id(service_name),
                    name=service_name,
                    provider="docker",
                    node_type=NodeType.SERVICE,
                    metadata={"source": source, "format": "docker-compose"},
                )
            )
            _add_support_nodes(topology, config, source=source)

        for service_name, raw_service in services.items():
            config = _optional_mapping(raw_service)
            for dependency in _depends_on(config.get("depends_on")):
                _try_add_edge(
                    topology,
                    source=_service_id(service_name),
                    target=_service_id(dependency),
                )
            _add_support_edges(topology, service_name, config)

        return topology


def parse_docker_compose_file(path: str | Path) -> Topology:
    """Parse a Docker Compose YAML file."""
    return DockerComposeParser().parse_file(path)


def parse_docker_compose_text(
    payload: str,
    *,
    source: str = "<string>",
) -> Topology:
    """Parse Docker Compose YAML text."""
    return DockerComposeParser().parse_text(payload, source=source)


def _load_yaml_mapping(payload: str, *, source: str) -> Mapping[str, object]:
    try:
        loaded = yaml.safe_load(payload)
    except yaml.YAMLError as error:
        raise DockerComposeParseError(
            f"malformed YAML: {error}", source=source
        ) from error
    if loaded is None:
        raise DockerComposeParseError("document is empty", source=source)
    return _mapping(loaded, path="$", source=source)


def _mapping(value: object, *, path: str, source: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DockerComposeParseError(f"{path} must be a mapping", source=source)
    for key in value:
        if not isinstance(key, str) or not key.strip():
            raise DockerComposeParseError(
                f"{path} keys must be non-empty strings",
                source=source,
            )
    return cast(Mapping[str, object], value)


def _optional_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return {}


def _depends_on(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(
            dependency
            for item in value
            if isinstance(item, str)
            for dependency in (_service_reference(item),)
            if dependency is not None
        )
    if isinstance(value, Mapping):
        return tuple(
            dependency
            for key in value
            if isinstance(key, str)
            for dependency in (_service_reference(key),)
            if dependency is not None
        )
    return ()


def _service_reference(value: str) -> str | None:
    reference = value.strip()
    if not reference:
        return None
    match = COMPOSE_DEFAULT_PATTERN.match(reference)
    if match:
        reference = match.group("default").strip()
    return reference or None


def _add_support_nodes(
    topology: Topology,
    config: Mapping[str, object],
    *,
    source: str,
) -> None:
    for field_name, node_type in (
        ("networks", NodeType.NETWORK),
        ("volumes", NodeType.STORAGE),
        ("secrets", NodeType.SECRET),
    ):
        for name in _compose_names(config.get(field_name), field_name=field_name):
            node_id = f"compose:{field_name[:-1]}:{name}"
            if node_id in topology.nodes:
                continue
            topology.add_node(
                Node(
                    id=node_id,
                    name=name,
                    provider="docker",
                    node_type=node_type,
                    metadata={"source": source, "format": "docker-compose"},
                )
            )


def _add_support_edges(
    topology: Topology,
    service_name: str,
    config: Mapping[str, object],
) -> None:
    for field_name in ("networks", "volumes", "secrets"):
        for name in _compose_names(config.get(field_name), field_name=field_name):
            _try_add_edge(
                topology,
                source=_service_id(service_name),
                target=f"compose:{field_name[:-1]}:{name}",
            )


def _compose_names(value: object, *, field_name: str) -> tuple[str, ...]:
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            if isinstance(item, str):
                name = _compose_resource_name(item, field_name=field_name)
                if name is not None:
                    names.append(name)
            elif isinstance(item, Mapping):
                source = item.get("source") or item.get("target")
                if (
                    isinstance(source, str)
                    and source
                    and not _is_ignored_volume_source(
                        source,
                        field_name=field_name,
                        resource_type=item.get("type"),
                    )
                ):
                    names.append(source)
        return tuple(names)
    if isinstance(value, Mapping):
        return tuple(key for key in value if isinstance(key, str) and key)
    return ()


def _compose_resource_name(value: str, *, field_name: str) -> str | None:
    name = value.split(":", maxsplit=1)[0].strip()
    if not name:
        return None
    if _is_ignored_volume_source(name, field_name=field_name, resource_type=None):
        return None
    return name


def _is_ignored_volume_source(
    value: str,
    *,
    field_name: str,
    resource_type: object,
) -> bool:
    if field_name != "volumes":
        return False
    if resource_type == "bind":
        return True
    normalized = value.replace("\\", "/")
    return normalized.startswith(("/", "./", "../", "~"))


def _try_add_edge(topology: Topology, *, source: str, target: str) -> None:
    if source not in topology.nodes or target not in topology.nodes or source == target:
        return
    edge = Edge(
        source=source,
        target=target,
        relationship=Relationship.DEPENDS_ON,
        metadata={"source": "docker-compose"},
    )
    edge_key = (edge.source, edge.target, edge.relationship)
    if any(
        (existing.source, existing.target, existing.relationship) == edge_key
        for existing in topology.edges
    ):
        return
    topology.add_edge(edge)


def _service_id(service_name: str) -> str:
    return f"compose:service:{service_name}"
