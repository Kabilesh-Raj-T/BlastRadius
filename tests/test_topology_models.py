"""Unit tests for the ChokePoint topology data model."""

import json

import pytest
from pydantic import ValidationError

from chokepoint.models import Edge, Node, NodeType, Relationship, Topology


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


def make_topology() -> Topology:
    topology = Topology()
    topology.add_node(make_node("api", name="API", node_type=NodeType.SERVICE))
    topology.add_node(make_node("db", name="Database", node_type=NodeType.DATABASE))
    topology.add_node(make_node("cache", name="Cache", node_type=NodeType.CACHE))
    topology.add_node(
        make_node(
            "identity",
            name="Identity",
            provider="okta",
            node_type=NodeType.IDENTITY,
        )
    )
    topology.add_edge(
        Edge(
            source="api",
            target="db",
            relationship=Relationship.READS_FROM,
            metadata={"protocol": "postgres"},
        )
    )
    topology.add_edge(
        Edge(source="api", target="cache", relationship=Relationship.CONNECTS_TO)
    )
    topology.add_edge(
        Edge(
            source="identity",
            target="api",
            relationship=Relationship.AUTHENTICATES_WITH,
        )
    )
    return topology


def test_node_accepts_json_metadata_and_strips_identifiers() -> None:
    node = Node(
        id=" api ",
        name=" API ",
        provider=" aws ",
        node_type=NodeType.SERVICE,
        metadata={
            "tags": {"env": "prod"},
            "ports": [443, 8443],
            "managed": True,
        },
    )

    assert node.id == "api"
    assert node.name == "API"
    assert node.provider == "aws"
    assert node.metadata["tags"] == {"env": "prod"}


def test_node_rejects_empty_required_strings() -> None:
    with pytest.raises(ValidationError):
        Node(id=" ", name="API", provider="aws", node_type=NodeType.SERVICE)


def test_metadata_rejects_non_json_values() -> None:
    with pytest.raises(ValidationError):
        Node(
            id="api",
            name="API",
            provider="aws",
            node_type=NodeType.SERVICE,
            metadata={"raw": object()},
        )


def test_node_and_edge_values_are_immutable() -> None:
    node = make_node("api")
    edge = Edge(source="api", target="db", relationship=Relationship.READS_FROM)

    with pytest.raises(ValidationError):
        node.name = "Changed"

    with pytest.raises(ValidationError):
        edge.target = "cache"


def test_edge_accepts_enum_values_and_metadata() -> None:
    edge = Edge(
        source=" api ",
        target=" db ",
        relationship="reads_from",
        metadata={"latency_ms": 12.5},
    )

    assert edge.source == "api"
    assert edge.target == "db"
    assert edge.relationship is Relationship.READS_FROM
    assert edge.metadata == {"latency_ms": 12.5}


def test_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Node(
            id="api",
            name="API",
            provider="aws",
            node_type=NodeType.SERVICE,
            region="us-east-1",
        )

    with pytest.raises(ValidationError):
        Edge(
            source="api",
            target="db",
            relationship=Relationship.READS_FROM,
            weight=1,
        )


def test_add_node_rejects_duplicate_node_ids() -> None:
    topology = Topology()
    node = make_node("api")

    assert topology.add_node(node) == node
    with pytest.raises(ValueError, match="already exists"):
        topology.add_node(node)


def test_add_edge_requires_existing_endpoint_nodes() -> None:
    topology = Topology(nodes={"api": make_node("api")})
    edge = Edge(source="api", target="db", relationship=Relationship.DEPENDS_ON)

    with pytest.raises(ValueError, match="missing node ids"):
        topology.add_edge(edge)


def test_add_edge_rejects_duplicate_relationship_identity() -> None:
    topology = Topology(
        nodes={"api": make_node("api"), "db": make_node("db")},
    )
    edge = Edge(source="api", target="db", relationship=Relationship.READS_FROM)

    assert topology.add_edge(edge) == edge
    with pytest.raises(ValueError, match="edge already exists"):
        topology.add_edge(edge)


def test_remove_node_deletes_incident_edges() -> None:
    topology = make_topology()

    removed = topology.remove_node("api")

    assert removed.id == "api"
    assert "api" not in topology.nodes
    assert topology.edges == []


def test_remove_node_rejects_unknown_node_id() -> None:
    topology = Topology()

    with pytest.raises(KeyError, match="does not exist"):
        topology.remove_node("missing")


def test_remove_edge_deletes_matching_directed_relationship() -> None:
    topology = make_topology()

    removed = topology.remove_edge("api", "db", Relationship.READS_FROM)

    assert removed.source == "api"
    assert removed.target == "db"
    assert removed.relationship is Relationship.READS_FROM
    assert topology.find(node_id="db") == (topology.nodes["db"],)
    assert Relationship.READS_FROM not in {edge.relationship for edge in topology.edges}


def test_remove_edge_rejects_unknown_edge() -> None:
    topology = make_topology()

    with pytest.raises(KeyError, match="edge does not exist"):
        topology.remove_edge("db", "api", Relationship.READS_FROM)


def test_neighbors_returns_outgoing_nodes_by_default() -> None:
    topology = make_topology()

    neighbors = topology.neighbors("api")

    assert neighbors == (topology.nodes["db"], topology.nodes["cache"])


def test_neighbors_supports_incoming_and_bidirectional_traversal() -> None:
    topology = make_topology()

    assert topology.neighbors("api", direction="incoming") == (
        topology.nodes["identity"],
    )
    assert topology.neighbors("api", direction="both") == (
        topology.nodes["db"],
        topology.nodes["cache"],
        topology.nodes["identity"],
    )


def test_neighbors_filters_by_relationship() -> None:
    topology = make_topology()

    assert topology.neighbors("api", relationship=Relationship.READS_FROM) == (
        topology.nodes["db"],
    )


def test_neighbors_rejects_unknown_node_id() -> None:
    topology = Topology()

    with pytest.raises(KeyError, match="does not exist"):
        topology.neighbors("missing")


def test_neighbors_rejects_invalid_direction_from_untyped_callers() -> None:
    topology = make_topology()

    with pytest.raises(ValueError, match="invalid neighbor direction"):
        topology.neighbors("api", direction="sideways")  # type: ignore[arg-type]


def test_find_matches_all_provided_criteria() -> None:
    topology = make_topology()

    assert topology.find(provider="aws", node_type=NodeType.DATABASE) == (
        topology.nodes["db"],
    )
    assert topology.find(name="API", provider="okta") == ()


def test_find_requires_at_least_one_criterion() -> None:
    topology = Topology()

    with pytest.raises(ValueError, match="criterion"):
        topology.find()


def test_export_json_and_import_json_round_trip_topology() -> None:
    topology = make_topology()

    exported = topology.export_json()
    imported = Topology.import_json(exported)

    assert json.loads(exported)["nodes"]["api"]["node_type"] == "service"
    assert imported == topology


def test_topology_validation_rejects_mismatched_node_key() -> None:
    with pytest.raises(ValidationError, match="does not match"):
        Topology(nodes={"wrong": make_node("actual")})


def test_topology_validation_rejects_edges_with_missing_nodes() -> None:
    with pytest.raises(ValidationError, match="missing node ids"):
        Topology(
            nodes={"api": make_node("api")},
            edges=[
                Edge(source="api", target="db", relationship=Relationship.DEPENDS_ON)
            ],
        )


def test_topology_validation_rejects_duplicate_edges() -> None:
    edge = Edge(source="api", target="db", relationship=Relationship.READS_FROM)

    with pytest.raises(ValidationError, match="duplicate edge"):
        Topology(
            nodes={"api": make_node("api"), "db": make_node("db")},
            edges=[edge, edge],
        )
