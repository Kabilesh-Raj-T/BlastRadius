"""Topology diff algorithms."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from chokepoint.models import Edge, Node, Relationship, Topology


class EdgeIdentity(BaseModel):
    """Stable identity for a topology edge."""

    model_config = ConfigDict(frozen=True)

    source: str
    target: str
    relationship: Relationship


class TopologyDiff(BaseModel):
    """Difference between two topologies."""

    model_config = ConfigDict(frozen=True)

    added_nodes: tuple[Node, ...]
    removed_nodes: tuple[Node, ...]
    changed_nodes: tuple[tuple[Node, Node], ...]
    added_edges: tuple[Edge, ...]
    removed_edges: tuple[Edge, ...]

    @property
    def has_changes(self) -> bool:
        """Return whether the diff contains any change."""
        return any(
            (
                self.added_nodes,
                self.removed_nodes,
                self.changed_nodes,
                self.added_edges,
                self.removed_edges,
            )
        )


class TopologyDiffer:
    """Compute deterministic diffs between topology snapshots."""

    def diff(self, before: Topology, after: Topology) -> TopologyDiff:
        """Compare two topologies.

        Args:
            before: Baseline topology.
            after: Candidate topology.

        Returns:
            Structured topology diff.
        """
        before_edges = {_edge_identity(edge): edge for edge in before.edges}
        after_edges = {_edge_identity(edge): edge for edge in after.edges}
        before_node_ids = set(before.nodes)
        after_node_ids = set(after.nodes)
        changed_nodes = tuple(
            (before.nodes[node_id], after.nodes[node_id])
            for node_id in sorted(before_node_ids & after_node_ids)
            if before.nodes[node_id] != after.nodes[node_id]
        )

        return TopologyDiff(
            added_nodes=tuple(
                after.nodes[node_id]
                for node_id in sorted(after_node_ids - before_node_ids)
            ),
            removed_nodes=tuple(
                before.nodes[node_id]
                for node_id in sorted(before_node_ids - after_node_ids)
            ),
            changed_nodes=changed_nodes,
            added_edges=tuple(
                after_edges[key]
                for key in sorted(
                    after_edges.keys() - before_edges.keys(), key=_edge_sort_key
                )
            ),
            removed_edges=tuple(
                before_edges[key]
                for key in sorted(
                    before_edges.keys() - after_edges.keys(), key=_edge_sort_key
                )
            ),
        )


def diff_topologies(before: Topology, after: Topology) -> TopologyDiff:
    """Compare two topologies with the default differ."""
    return TopologyDiffer().diff(before, after)


def _edge_identity(edge: Edge) -> EdgeIdentity:
    return EdgeIdentity(
        source=edge.source,
        target=edge.target,
        relationship=edge.relationship,
    )


def _edge_sort_key(edge: EdgeIdentity) -> tuple[str, str, str]:
    return edge.source, edge.target, edge.relationship.value
