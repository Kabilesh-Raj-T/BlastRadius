"""Unit tests for topology enrichment and merge behavior."""

from pathlib import Path

import pytest

from chokepoint.models import Edge, Node, NodeType, Relationship, Topology
from chokepoint.parser import (
    ProviderNormalizer,
    TopologyMergeError,
    TopologyMerger,
    enrich_terraform_with_yaml_overlay,
    merge_topologies,
    parse_terraform_text,
    parse_topology_yaml_text,
)


def make_node(
    node_id: str,
    *,
    name: str | None = None,
    provider: str = "aws",
    node_type: NodeType = NodeType.SERVICE,
) -> Node:
    return Node(
        id=node_id,
        name=name or node_id,
        provider=provider,
        node_type=node_type,
    )


def topology_with_node(node: Node) -> Topology:
    topology = Topology()
    topology.add_node(node)
    return topology


def test_provider_normalizer_collapses_common_provider_aliases() -> None:
    normalizer = ProviderNormalizer()

    assert normalizer.normalize("aws.west") == "aws"
    assert normalizer.normalize("Amazon Web Services") == "aws"
    assert normalizer.normalize("azurerm") == "azure"
    assert normalizer.normalize("google-beta") == "gcp"
    assert normalizer.normalize("GitHub") == "github"


def test_merge_terraform_with_yaml_overlay_adds_external_nodes() -> None:
    terraform_topology = parse_terraform_text(
        """
resource "aws_lb" "frontend" {
  provider = aws.west
}
""",
        source="main.tf",
    )
    overlay_topology = parse_topology_yaml_text(
        """
external:
  - cloudflare
  - okta
  - stripe
  - github
""",
        source="overlay.yaml",
    )

    merged = merge_topologies(terraform_topology, overlay_topology)

    assert set(merged.nodes) == {
        "aws_lb.frontend",
        "cloudflare",
        "okta",
        "stripe",
        "github",
    }
    assert merged.nodes["aws_lb.frontend"].provider == "aws"
    assert merged.nodes["aws_lb.frontend"].metadata["original_provider"] == "aws.west"
    assert merged.nodes["cloudflare"].provider == "cloudflare"
    assert merged.nodes["okta"].provider == "okta"


def test_enrich_terraform_with_yaml_overlay_parses_paths(tmp_path: Path) -> None:
    terraform_path = tmp_path / "main.tf"
    overlay_path = tmp_path / "overlay.yaml"
    terraform_path.write_text(
        """
resource "aws_iam_role" "app" {
  name = "app"
}
""",
        encoding="utf-8",
    )
    overlay_path.write_text(
        """
external:
  - github
""",
        encoding="utf-8",
    )

    topology = enrich_terraform_with_yaml_overlay((terraform_path,), overlay_path)

    assert set(topology.nodes) == {"aws_iam_role.app", "github"}


def test_merge_removes_identical_duplicate_nodes_and_merges_metadata() -> None:
    first = topology_with_node(
        Node(
            id="cloudflare",
            name="cloudflare",
            provider="cloudflare",
            node_type=NodeType.EXTERNAL,
            metadata={"source": "terraform"},
        )
    )
    second = topology_with_node(
        Node(
            id="cloudflare",
            name="cloudflare",
            provider="Cloudflare",
            node_type=NodeType.EXTERNAL,
            metadata={"overlay": True},
        )
    )

    merged = TopologyMerger().merge(first, second)

    assert tuple(merged.nodes) == ("cloudflare",)
    assert merged.nodes["cloudflare"].provider == "cloudflare"
    assert merged.nodes["cloudflare"].metadata == {
        "source": "terraform",
        "overlay": True,
        "original_provider": "Cloudflare",
    }


def test_merge_removes_duplicate_edges() -> None:
    first = Topology()
    first.add_node(make_node("frontend"))
    first.add_node(make_node("cloudflare", node_type=NodeType.EXTERNAL))
    first.add_edge(
        Edge(
            source="frontend",
            target="cloudflare",
            relationship=Relationship.DEPENDS_ON,
        )
    )
    second = Topology()
    second.add_node(make_node("frontend"))
    second.add_node(make_node("cloudflare", node_type=NodeType.EXTERNAL))
    second.add_edge(
        Edge(
            source="frontend",
            target="cloudflare",
            relationship=Relationship.DEPENDS_ON,
        )
    )

    merged = merge_topologies(first, second)

    assert len(merged.edges) == 1
    assert merged.edges[0].source == "frontend"
    assert merged.edges[0].target == "cloudflare"


def test_merge_detects_duplicate_node_type_conflict() -> None:
    terraform_topology = topology_with_node(
        make_node(
            "shared",
            provider="aws",
            node_type=NodeType.LOAD_BALANCER,
        )
    )
    overlay_topology = topology_with_node(
        make_node(
            "shared",
            provider="aws",
            node_type=NodeType.EXTERNAL,
        )
    )

    with pytest.raises(TopologyMergeError, match="node_type"):
        merge_topologies(terraform_topology, overlay_topology)


def test_merge_detects_duplicate_provider_conflict_after_normalization() -> None:
    first = topology_with_node(make_node("shared", provider="aws"))
    second = topology_with_node(make_node("shared", provider="stripe"))

    with pytest.raises(TopologyMergeError, match="provider"):
        merge_topologies(first, second)


def test_merge_detects_duplicate_name_conflict() -> None:
    first = topology_with_node(make_node("shared", name="one"))
    second = topology_with_node(make_node("shared", name="two"))

    with pytest.raises(TopologyMergeError, match="name"):
        merge_topologies(first, second)
