"""Topology enrichment and merge algorithms."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from types import MappingProxyType

from chokepoint.models import Node, Relationship, Topology
from chokepoint.models.topology import Metadata
from chokepoint.parser.terraform_parser import TerraformParser
from chokepoint.parser.yaml_parser import YamlTopologyParser

DEFAULT_PROVIDER_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "amazon": "aws",
        "amazon web services": "aws",
        "aws": "aws",
        "awscc": "aws",
        "azure": "azure",
        "azurerm": "azure",
        "cloudflare": "cloudflare",
        "github": "github",
        "google": "gcp",
        "google-beta": "gcp",
        "gcp": "gcp",
        "okta": "okta",
        "stripe": "stripe",
    }
)


class TopologyMergeError(ValueError):
    """Raised when topology enrichment cannot merge inputs safely."""


class ProviderNormalizer:
    """Normalize provider names across Terraform and overlay inputs."""

    def __init__(self, aliases: Mapping[str, str] | None = None) -> None:
        """Create a provider normalizer.

        Args:
            aliases: Optional provider alias mapping.
        """
        self._aliases = aliases or DEFAULT_PROVIDER_ALIASES

    def normalize(self, provider: str) -> str:
        """Normalize a provider identifier.

        Args:
            provider: Provider value from a node.

        Returns:
            Canonical provider identifier.
        """
        normalized = provider.strip().lower().replace("_", "-")
        base_provider = normalized.split(".", maxsplit=1)[0]
        return self._aliases.get(base_provider, base_provider)


class TopologyMerger:
    """Merge Terraform topologies with YAML overlay topologies."""

    def __init__(self, normalizer: ProviderNormalizer | None = None) -> None:
        """Create a topology merger.

        Args:
            normalizer: Optional provider normalizer.
        """
        self._normalizer = normalizer or ProviderNormalizer()

    def merge(self, *topologies: Topology) -> Topology:
        """Merge topologies into one enriched topology.

        Args:
            *topologies: Topologies to merge in priority order.

        Returns:
            Merged topology with normalized providers.

        Raises:
            TopologyMergeError: If duplicate node ids describe different nodes.
        """
        merged = Topology()
        edge_keys: set[tuple[str, str, Relationship]] = set()

        for topology in topologies:
            normalized = self._normalize_topology(topology)
            for node in normalized.nodes.values():
                self._add_or_merge_node(merged, node)

            for edge in normalized.edges:
                edge_key = (edge.source, edge.target, edge.relationship)
                if edge_key in edge_keys:
                    continue
                if edge.source not in merged.nodes or edge.target not in merged.nodes:
                    message = (
                        f"edge {edge.source!r}->{edge.target!r} cannot be merged "
                        "because one or both endpoint nodes are missing"
                    )
                    raise TopologyMergeError(message)

                merged.add_edge(edge)
                edge_keys.add(edge_key)

        return merged

    def _normalize_topology(self, topology: Topology) -> Topology:
        """Return a topology with normalized providers."""
        normalized = Topology()
        for node in topology.nodes.values():
            normalized.add_node(self._normalize_node(node))
        for edge in topology.edges:
            normalized.add_edge(edge)
        return normalized

    def _normalize_node(self, node: Node) -> Node:
        """Normalize provider metadata on one node."""
        provider = self._normalizer.normalize(node.provider)
        metadata = dict(node.metadata)
        if node.provider != provider:
            metadata["original_provider"] = node.provider

        return Node(
            id=node.id,
            name=node.name,
            provider=provider,
            node_type=node.node_type,
            metadata=metadata,
        )

    def _add_or_merge_node(self, topology: Topology, node: Node) -> None:
        """Add a node or merge an identical duplicate."""
        existing = topology.nodes.get(node.id)
        if existing is None:
            topology.add_node(node)
            return

        self._validate_duplicate_node(existing, node)
        topology.nodes[node.id] = Node(
            id=existing.id,
            name=existing.name,
            provider=existing.provider,
            node_type=existing.node_type,
            metadata=_merge_metadata(existing.metadata, node.metadata),
        )

    def _validate_duplicate_node(self, existing: Node, incoming: Node) -> None:
        """Validate that duplicate node ids describe the same entity."""
        conflicts: list[str] = []
        if existing.name != incoming.name:
            conflicts.append(f"name {existing.name!r} != {incoming.name!r}")
        if existing.provider != incoming.provider:
            conflicts.append(f"provider {existing.provider!r} != {incoming.provider!r}")
        if existing.node_type != incoming.node_type:
            conflicts.append(
                f"node_type {existing.node_type.value!r} != "
                f"{incoming.node_type.value!r}"
            )

        if conflicts:
            message = (
                f"duplicate node id {existing.id!r} has conflicting attributes: "
                + "; ".join(conflicts)
            )
            raise TopologyMergeError(message)


def merge_topologies(*topologies: Topology) -> Topology:
    """Merge topologies using default provider normalization.

    Args:
        *topologies: Topologies to merge.

    Returns:
        Merged topology.
    """
    return TopologyMerger().merge(*topologies)


def enrich_terraform_with_yaml_overlay(
    terraform_paths: Iterable[str | Path],
    overlay_path: str | Path,
) -> Topology:
    """Parse Terraform files and enrich them with a YAML overlay.

    Args:
        terraform_paths: Terraform file paths.
        overlay_path: YAML overlay path.

    Returns:
        Merged topology.
    """
    terraform_topology = TerraformParser().parse_files(terraform_paths)
    overlay_topology = YamlTopologyParser().parse_file(overlay_path)
    return merge_topologies(terraform_topology, overlay_topology)


def _merge_metadata(left: Metadata, right: Metadata) -> Metadata:
    """Merge metadata maps without silently overwriting conflicts."""
    merged: Metadata = dict(left)
    for key, value in right.items():
        if key not in merged:
            merged[key] = value
        elif merged[key] != value:
            merged[f"overlay_{key}"] = value
    return merged
