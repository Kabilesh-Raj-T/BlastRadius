"""Unit tests for YAML topology parsing."""

from pathlib import Path

import pytest

from chokepoint.models import NodeType, Relationship
from chokepoint.parser import (
    TopologyParseError,
    YamlTopologyParser,
    parse_topology_yaml_file,
    parse_topology_yaml_text,
)

PROMPT_EXAMPLE = """
clouds:
  - aws
  - azure

dns:
  - cloudflare

identity:
  - okta

services:
  frontend:
    depends_on:
      - cloudflare
      - okta

database:
    depends_on:
      - aws
"""


def test_parse_prompt_example_into_topology() -> None:
    topology = parse_topology_yaml_text(PROMPT_EXAMPLE, source="prompt")

    assert set(topology.nodes) == {
        "aws",
        "azure",
        "cloudflare",
        "okta",
        "frontend",
        "database",
    }
    assert topology.nodes["aws"].node_type is NodeType.EXTERNAL
    assert topology.nodes["aws"].provider == "aws"
    assert topology.nodes["cloudflare"].node_type is NodeType.DNS
    assert topology.nodes["okta"].node_type is NodeType.IDENTITY
    assert topology.nodes["frontend"].node_type is NodeType.SERVICE
    assert topology.nodes["database"].node_type is NodeType.DATABASE
    assert {
        (edge.source, edge.target, edge.relationship) for edge in topology.edges
    } == {
        ("frontend", "cloudflare", Relationship.DEPENDS_ON),
        ("frontend", "okta", Relationship.DEPENDS_ON),
        ("database", "aws", Relationship.DEPENDS_ON),
    }


def test_parse_file_reads_yaml_from_disk(tmp_path: Path) -> None:
    path = tmp_path / "topology.yaml"
    path.write_text(PROMPT_EXAMPLE, encoding="utf-8")

    topology = parse_topology_yaml_file(path)

    assert "frontend" in topology.nodes
    assert topology.neighbors("frontend") == (
        topology.nodes["cloudflare"],
        topology.nodes["okta"],
    )


def test_parse_expanded_resource_objects_and_relationship_fields() -> None:
    payload = """
clouds:
  - id: aws
    name: Amazon Web Services
    metadata:
      regions:
        - us-east-1
        - us-west-2

services:
  api:
    provider: internal
    metadata:
      owner: platform
    reads_from:
      - postgres

databases:
  postgres:
    provider: aws
    depends_on:
      - aws
"""

    topology = YamlTopologyParser().parse_text(payload)

    assert topology.nodes["aws"].name == "Amazon Web Services"
    assert topology.nodes["aws"].metadata == {"regions": ["us-east-1", "us-west-2"]}
    assert topology.nodes["api"].provider == "internal"
    assert {
        (edge.source, edge.target, edge.relationship) for edge in topology.edges
    } == {
        ("api", "postgres", Relationship.READS_FROM),
        ("postgres", "aws", Relationship.DEPENDS_ON),
    }


def test_all_valid_example_yaml_files_parse() -> None:
    example_paths = sorted(Path("examples").glob("topology-*.yaml"))

    assert example_paths
    for path in example_paths:
        topology = YamlTopologyParser().parse_file(path)
        assert topology.nodes


def test_rejects_empty_document() -> None:
    with pytest.raises(TopologyParseError, match="document is empty"):
        parse_topology_yaml_text("")


def test_rejects_non_mapping_root() -> None:
    with pytest.raises(TopologyParseError, match=r"\$ must be a mapping"):
        parse_topology_yaml_text("- aws")


def test_rejects_malformed_yaml_with_location() -> None:
    payload = """
services:
  frontend:
    depends_on:
      - okta
    - invalid
"""

    with pytest.raises(TopologyParseError, match="malformed YAML at line"):
        parse_topology_yaml_text(payload, source="bad.yaml")


def test_rejects_unknown_top_level_section() -> None:
    payload = """
terraform:
  - module.vpc
"""

    with pytest.raises(TopologyParseError, match="unsupported top-level section"):
        parse_topology_yaml_text(payload)


def test_rejects_unknown_resource_field() -> None:
    payload = """
services:
  frontend:
    owner: platform
"""

    with pytest.raises(TopologyParseError, match="unsupported field"):
        parse_topology_yaml_text(payload)


def test_rejects_missing_dependency_target() -> None:
    payload = """
services:
  frontend:
    depends_on:
      - missing
"""

    with pytest.raises(TopologyParseError, match="dependency target 'missing'"):
        parse_topology_yaml_text(payload)


def test_rejects_dependency_scalar() -> None:
    payload = """
clouds:
  - aws
services:
  frontend:
    depends_on: aws
"""

    with pytest.raises(TopologyParseError, match="must be a list of node ids"):
        parse_topology_yaml_text(payload)


def test_rejects_non_string_dependency_item() -> None:
    payload = """
clouds:
  - aws
services:
  frontend:
    depends_on:
      - 42
"""

    with pytest.raises(TopologyParseError, match=r"depends_on\[0\]"):
        parse_topology_yaml_text(payload)


def test_rejects_sequence_object_without_id() -> None:
    payload = """
clouds:
  - name: Amazon Web Services
"""

    with pytest.raises(TopologyParseError, match=r"\.id is required"):
        parse_topology_yaml_text(payload)


def test_rejects_duplicate_node_ids() -> None:
    payload = """
clouds:
  - aws
external:
  - aws
"""

    with pytest.raises(TopologyParseError, match="duplicate node id 'aws'"):
        parse_topology_yaml_text(payload)


def test_rejects_named_resource_id_mismatch() -> None:
    payload = """
services:
  frontend:
    id: api
"""

    with pytest.raises(TopologyParseError, match="must match mapping key"):
        parse_topology_yaml_text(payload)


def test_rejects_non_json_metadata_values() -> None:
    payload = """
clouds:
  - id: aws
    metadata:
      raw: !!binary AAA=
"""

    with pytest.raises(TopologyParseError, match="JSON-compatible"):
        parse_topology_yaml_text(payload)


def test_parse_error_includes_source_label() -> None:
    with pytest.raises(TopologyParseError) as error:
        parse_topology_yaml_text("services: frontend", source="topology.yaml")

    assert "topology.yaml" in str(error.value)
    assert "$.services must be a mapping" in str(error.value)
