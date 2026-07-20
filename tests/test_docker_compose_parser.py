"""Docker Compose parser tests."""

from pathlib import Path

import pytest

from chokepoint.models import NodeType
from chokepoint.parser import (
    DockerComposeParseError,
    DockerComposeParser,
    parse_docker_compose_file,
    parse_docker_compose_text,
)


def test_parse_compose_services_dependencies_and_support_resources() -> None:
    payload = """
services:
  api:
    depends_on:
      db:
        condition: service_started
    networks:
      backend: {}
    secrets:
      - api_key
  db:
    volumes:
      - source: data
        target: /var/lib/postgresql/data
"""

    topology = parse_docker_compose_text(payload, source="compose.yaml")

    assert topology.nodes["compose:service:api"].node_type == NodeType.SERVICE
    assert topology.nodes["compose:service:db"].node_type == NodeType.SERVICE
    assert topology.nodes["compose:network:backend"].node_type == NodeType.NETWORK
    assert topology.nodes["compose:secret:api_key"].node_type == NodeType.SECRET
    assert topology.nodes["compose:volume:data"].node_type == NodeType.STORAGE
    assert _edge_ids(topology) == {
        ("compose:service:api", "compose:service:db"),
        ("compose:service:api", "compose:network:backend"),
        ("compose:service:api", "compose:secret:api_key"),
        ("compose:service:db", "compose:volume:data"),
    }


def test_parser_accepts_file_entrypoint(tmp_path: Path) -> None:
    path = tmp_path / "compose.yaml"
    path.write_text(
        """
services:
  worker:
    image: example/worker
""",
        encoding="utf-8",
    )

    topology = parse_docker_compose_file(path)

    assert tuple(topology.nodes) == ("compose:service:worker",)


def test_parser_reports_unreadable_file(tmp_path: Path) -> None:
    path = tmp_path / "missing-compose.yaml"

    with pytest.raises(DockerComposeParseError, match="unable to read"):
        parse_docker_compose_file(path)


def test_parser_rejects_malformed_yaml() -> None:
    with pytest.raises(DockerComposeParseError, match="malformed YAML"):
        DockerComposeParser().parse_text("services: [", source="bad-compose.yaml")


def test_parser_rejects_non_mapping_document() -> None:
    with pytest.raises(DockerComposeParseError, match=r"\$ must be a mapping"):
        parse_docker_compose_text("- api", source="bad-compose.yaml")


def test_parser_rejects_empty_document() -> None:
    with pytest.raises(DockerComposeParseError, match="document is empty"):
        parse_docker_compose_text("", source="empty-compose.yaml")


def test_parser_rejects_empty_root_key() -> None:
    with pytest.raises(DockerComposeParseError, match="keys must be non-empty"):
        parse_docker_compose_text('"": value', source="bad-compose.yaml")


def test_parser_ignores_non_mapping_services_section() -> None:
    topology = parse_docker_compose_text("services: api", source="compose.yaml")

    assert topology.nodes == {}
    assert topology.edges == []


def test_parser_handles_list_dependencies_and_ignores_missing_targets() -> None:
    topology = parse_docker_compose_text(
        """
services:
  api:
    depends_on:
      - db
      - missing
  db:
    image: postgres
""",
        source="compose.yaml",
    )

    assert _edge_ids(topology) == {("compose:service:api", "compose:service:db")}


def test_parser_resolves_compose_variable_default_dependencies() -> None:
    topology = parse_docker_compose_text(
        """
services:
  api:
    depends_on:
      - ${APP_DB_HOST:-postgresql}
      - ${CACHE_HOST-redis}
      - ${UNRESOLVED_SERVICE}
  postgresql:
    image: postgres
  redis:
    image: redis
""",
        source="compose.yaml",
    )

    assert _edge_ids(topology) == {
        ("compose:service:api", "compose:service:postgresql"),
        ("compose:service:api", "compose:service:redis"),
    }


def test_parser_ignores_bind_mounts_but_keeps_named_volumes() -> None:
    topology = parse_docker_compose_text(
        """
services:
  api:
    volumes:
      - ./src:/app/src
      - ../config:/app/config
      - /var/run/docker.sock:/var/run/docker.sock
      - app-data:/var/lib/app
      - type: bind
        source: ./fixtures/coredns
        target: /etc/coredns
      - type: volume
        source: cache-data
        target: /cache
""",
        source="compose.yaml",
    )

    assert sorted(topology.nodes) == [
        "compose:service:api",
        "compose:volume:app-data",
        "compose:volume:cache-data",
    ]
    assert _edge_ids(topology) == {
        ("compose:service:api", "compose:volume:app-data"),
        ("compose:service:api", "compose:volume:cache-data"),
    }


def test_parser_deduplicates_support_resources_and_edges() -> None:
    topology = parse_docker_compose_text(
        """
services:
  api:
    networks:
      - backend
      - backend
  worker:
    networks:
      - backend
""",
        source="compose.yaml",
    )

    assert sorted(topology.nodes) == [
        "compose:network:backend",
        "compose:service:api",
        "compose:service:worker",
    ]
    assert _edge_ids(topology) == {
        ("compose:service:api", "compose:network:backend"),
        ("compose:service:worker", "compose:network:backend"),
    }


def _edge_ids(topology) -> set[tuple[str, str]]:
    return {(edge.source, edge.target) for edge in topology.edges}
