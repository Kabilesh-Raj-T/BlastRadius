"""Terraform ingestion for ChokePoint."""

from __future__ import annotations

import io
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar, cast

from hcl2.api import load as hcl2_load

from chokepoint.models import Edge, Node, NodeType, Relationship, Topology
from chokepoint.models.topology import Metadata


class TerraformParseError(ValueError):
    """Raised when Terraform configuration cannot be ingested."""

    def __init__(self, message: str, *, source: str | None = None) -> None:
        """Create a Terraform parser error.

        Args:
            message: Human-readable parse failure.
            source: Optional source path or label.
        """
        self.message = message
        self.source = source
        detail = f"{source}: {message}" if source else message
        super().__init__(detail)


@dataclass(frozen=True)
class TerraformResourceMapping:
    """Mapping entry for a supported Terraform resource type."""

    node_type: NodeType
    provider: str


@dataclass(frozen=True)
class TerraformProvider:
    """Provider configuration discovered in Terraform files."""

    address: str
    name: str
    alias: str | None
    source: str


@dataclass(frozen=True)
class TerraformResource:
    """Supported Terraform resource discovered before topology construction."""

    address: str
    resource_type: str
    resource_name: str
    node_type: NodeType
    provider: str
    source: str
    explicit_dependencies: tuple[str, ...]
    references: tuple[str, ...]


@dataclass(frozen=True)
class ParsedTerraformDocument:
    """Parsed Terraform document with source context."""

    source: str
    content: Mapping[str, object]


TERRAFORM_RESOURCE_MAPPINGS: Mapping[str, TerraformResourceMapping] = MappingProxyType(
    {
        "aws_route53_zone": TerraformResourceMapping(NodeType.DNS, "aws"),
        "aws_route53_record": TerraformResourceMapping(NodeType.DNS, "aws"),
        "aws_lb": TerraformResourceMapping(NodeType.LOAD_BALANCER, "aws"),
        "aws_alb": TerraformResourceMapping(NodeType.LOAD_BALANCER, "aws"),
        "aws_elb": TerraformResourceMapping(NodeType.LOAD_BALANCER, "aws"),
        "aws_lb_listener": TerraformResourceMapping(NodeType.LOAD_BALANCER, "aws"),
        "aws_lb_target_group": TerraformResourceMapping(
            NodeType.LOAD_BALANCER,
            "aws",
        ),
        "aws_iam_group": TerraformResourceMapping(NodeType.IDENTITY, "aws"),
        "aws_iam_instance_profile": TerraformResourceMapping(
            NodeType.IDENTITY,
            "aws",
        ),
        "aws_iam_policy": TerraformResourceMapping(NodeType.IDENTITY, "aws"),
        "aws_iam_role": TerraformResourceMapping(NodeType.IDENTITY, "aws"),
        "aws_iam_role_policy": TerraformResourceMapping(NodeType.IDENTITY, "aws"),
        "aws_iam_role_policy_attachment": TerraformResourceMapping(
            NodeType.IDENTITY,
            "aws",
        ),
        "aws_iam_user": TerraformResourceMapping(NodeType.IDENTITY, "aws"),
        "aws_eks_access_entry": TerraformResourceMapping(NodeType.IDENTITY, "aws"),
        "aws_eks_access_policy_association": TerraformResourceMapping(
            NodeType.IDENTITY,
            "aws",
        ),
        "aws_db_instance": TerraformResourceMapping(NodeType.DATABASE, "aws"),
        "aws_dynamodb_table": TerraformResourceMapping(NodeType.DATABASE, "aws"),
        "aws_rds_cluster": TerraformResourceMapping(NodeType.DATABASE, "aws"),
        "aws_elasticache_cluster": TerraformResourceMapping(NodeType.CACHE, "aws"),
        "aws_elasticache_replication_group": TerraformResourceMapping(
            NodeType.CACHE,
            "aws",
        ),
        "aws_sns_topic": TerraformResourceMapping(NodeType.QUEUE, "aws"),
        "aws_sqs_queue": TerraformResourceMapping(NodeType.QUEUE, "aws"),
        "aws_ebs_volume": TerraformResourceMapping(NodeType.STORAGE, "aws"),
        "aws_efs_file_system": TerraformResourceMapping(NodeType.STORAGE, "aws"),
        "aws_s3_bucket": TerraformResourceMapping(NodeType.STORAGE, "aws"),
        "aws_autoscaling_group": TerraformResourceMapping(NodeType.COMPUTE, "aws"),
        "aws_ecs_service": TerraformResourceMapping(NodeType.SERVICE, "aws"),
        "aws_lambda_function": TerraformResourceMapping(NodeType.SERVICE, "aws"),
        "aws_eks_cluster": TerraformResourceMapping(NodeType.COMPUTE, "aws"),
        "aws_eks_node_group": TerraformResourceMapping(NodeType.COMPUTE, "aws"),
        "aws_instance": TerraformResourceMapping(NodeType.COMPUTE, "aws"),
        "aws_launch_template": TerraformResourceMapping(NodeType.COMPUTE, "aws"),
        "aws_cloudwatch_log_group": TerraformResourceMapping(
            NodeType.EXTERNAL,
            "aws",
        ),
        "aws_internet_gateway": TerraformResourceMapping(NodeType.NETWORK, "aws"),
        "aws_nat_gateway": TerraformResourceMapping(NodeType.NETWORK, "aws"),
        "aws_network_acl": TerraformResourceMapping(NodeType.NETWORK, "aws"),
        "aws_network_acl_rule": TerraformResourceMapping(NodeType.NETWORK, "aws"),
        "aws_route": TerraformResourceMapping(NodeType.NETWORK, "aws"),
        "aws_route_table": TerraformResourceMapping(NodeType.NETWORK, "aws"),
        "aws_route_table_association": TerraformResourceMapping(
            NodeType.NETWORK,
            "aws",
        ),
        "aws_security_group": TerraformResourceMapping(NodeType.NETWORK, "aws"),
        "aws_subnet": TerraformResourceMapping(NodeType.NETWORK, "aws"),
        "aws_vpc": TerraformResourceMapping(NodeType.NETWORK, "aws"),
        "aws_vpc_endpoint": TerraformResourceMapping(NodeType.NETWORK, "aws"),
        "aws_vpc_security_group_egress_rule": TerraformResourceMapping(
            NodeType.NETWORK,
            "aws",
        ),
        "aws_vpc_security_group_ingress_rule": TerraformResourceMapping(
            NodeType.NETWORK,
            "aws",
        ),
        "aws_vpn_gateway": TerraformResourceMapping(NodeType.NETWORK, "aws"),
        "aws_vpn_gateway_route_propagation": TerraformResourceMapping(
            NodeType.NETWORK,
            "aws",
        ),
        "azurerm_dns_zone": TerraformResourceMapping(NodeType.DNS, "azurerm"),
        "azurerm_lb": TerraformResourceMapping(
            NodeType.LOAD_BALANCER,
            "azurerm",
        ),
        "azurerm_role_assignment": TerraformResourceMapping(
            NodeType.IDENTITY,
            "azurerm",
        ),
        "azurerm_mssql_database": TerraformResourceMapping(
            NodeType.DATABASE,
            "azurerm",
        ),
        "azurerm_storage_account": TerraformResourceMapping(
            NodeType.STORAGE,
            "azurerm",
        ),
        "azurerm_virtual_machine": TerraformResourceMapping(
            NodeType.COMPUTE,
            "azurerm",
        ),
        "azurerm_virtual_network": TerraformResourceMapping(
            NodeType.NETWORK,
            "azurerm",
        ),
        "google_dns_managed_zone": TerraformResourceMapping(
            NodeType.DNS,
            "google",
        ),
        "google_compute_backend_service": TerraformResourceMapping(
            NodeType.LOAD_BALANCER,
            "google",
        ),
        "google_compute_global_forwarding_rule": TerraformResourceMapping(
            NodeType.LOAD_BALANCER,
            "google",
        ),
        "google_project_iam_binding": TerraformResourceMapping(
            NodeType.IDENTITY,
            "google",
        ),
        "google_sql_database_instance": TerraformResourceMapping(
            NodeType.DATABASE,
            "google",
        ),
        "google_storage_bucket": TerraformResourceMapping(
            NodeType.STORAGE,
            "google",
        ),
        "google_compute_instance": TerraformResourceMapping(
            NodeType.COMPUTE,
            "google",
        ),
        "google_compute_network": TerraformResourceMapping(
            NodeType.NETWORK,
            "google",
        ),
    }
)


class TerraformParser:
    """Parse Terraform HCL files into ChokePoint topologies."""

    REFERENCE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"\b(?P<type>[A-Za-z][A-Za-z0-9_]*)\.(?P<name>[A-Za-z_][A-Za-z0-9_-]*)\b"
    )

    def __init__(
        self,
        resource_mappings: Mapping[str, TerraformResourceMapping] | None = None,
    ) -> None:
        """Create a Terraform parser.

        Args:
            resource_mappings: Optional custom resource mapping.
        """
        self._resource_mappings = resource_mappings or TERRAFORM_RESOURCE_MAPPINGS

    @property
    def resource_mappings(self) -> Mapping[str, TerraformResourceMapping]:
        """Return supported Terraform resource mappings."""
        return self._resource_mappings

    def parse_file(self, path: str | Path) -> Topology:
        """Parse one Terraform file.

        Args:
            path: `.tf` file path.

        Returns:
            Parsed topology.
        """
        return self.parse_files((path,))

    def parse_files(self, paths: Iterable[str | Path]) -> Topology:
        """Parse multiple Terraform files into one topology.

        Args:
            paths: Terraform file paths.

        Returns:
            Parsed topology.

        Raises:
            TerraformParseError: If files cannot be read or parsed.
        """
        resolved_paths = tuple(Path(path) for path in paths)
        if not resolved_paths:
            raise TerraformParseError("at least one Terraform file is required")

        documents = tuple(self._load_file(path) for path in sorted(resolved_paths))
        return self._build_topology(documents)

    def parse_directory(self, path: str | Path) -> Topology:
        """Parse all `.tf` files in a directory.

        Args:
            path: Directory containing Terraform files.

        Returns:
            Parsed topology.
        """
        directory = Path(path)
        if not directory.exists():
            raise TerraformParseError(
                "Terraform directory does not exist", source=str(directory)
            )
        if not directory.is_dir():
            raise TerraformParseError(
                "Terraform path must be a directory", source=str(directory)
            )

        tf_files = tuple(sorted(directory.glob("*.tf")))
        if not tf_files:
            raise TerraformParseError("no .tf files found", source=str(directory))

        return self.parse_files(tf_files)

    def parse_text(self, payload: str, *, source: str = "<string>") -> Topology:
        """Parse Terraform HCL text into a topology.

        Args:
            payload: Terraform HCL text.
            source: Source label used in errors and metadata.

        Returns:
            Parsed topology.
        """
        document = self._load_text(payload, source=source)
        return self._build_topology((document,))

    def _load_file(self, path: Path) -> ParsedTerraformDocument:
        """Load and parse a Terraform file."""
        if path.suffix != ".tf":
            raise TerraformParseError(
                "Terraform file must have a .tf suffix", source=str(path)
            )

        try:
            payload = path.read_text(encoding="utf-8")
        except OSError as error:
            message = f"unable to read Terraform file: {error.strerror or error}"
            raise TerraformParseError(message, source=str(path)) from error

        return self._load_text(payload, source=str(path))

    def _load_text(self, payload: str, *, source: str) -> ParsedTerraformDocument:
        """Load Terraform HCL text into a parsed document."""
        try:
            loaded = hcl2_load(io.StringIO(payload))
        except Exception as error:
            message = f"malformed Terraform HCL: {error}"
            raise TerraformParseError(message, source=source) from error

        if not isinstance(loaded, Mapping):
            raise TerraformParseError(
                "Terraform document must parse to a mapping", source=source
            )

        return ParsedTerraformDocument(
            source=source, content=cast(Mapping[str, object], loaded)
        )

    def _build_topology(
        self,
        documents: tuple[ParsedTerraformDocument, ...],
    ) -> Topology:
        """Build a topology from parsed Terraform documents."""
        providers = self._extract_providers(documents)
        resources = self._extract_resources(documents, providers)
        topology = Topology()

        for resource in resources.values():
            topology.add_node(self._node_from_resource(resource))

        self._add_edges(topology, resources)
        return topology

    def _extract_providers(
        self,
        documents: tuple[ParsedTerraformDocument, ...],
    ) -> dict[str, TerraformProvider]:
        """Extract provider configurations from Terraform documents."""
        providers: dict[str, TerraformProvider] = {}
        for document in documents:
            for provider_block in _block_list(
                document.content.get("provider"),
                block_name="provider",
                source=document.source,
            ):
                for provider_name, raw_config in provider_block.items():
                    config = _mapping(
                        raw_config,
                        path=f'provider "{provider_name}"',
                        source=document.source,
                    )
                    alias = _optional_string(config.get("alias"))
                    address = f"{provider_name}.{alias}" if alias else provider_name
                    providers[address] = TerraformProvider(
                        address=address,
                        name=provider_name,
                        alias=alias,
                        source=document.source,
                    )
        return providers

    def _extract_resources(
        self,
        documents: tuple[ParsedTerraformDocument, ...],
        providers: Mapping[str, TerraformProvider],
    ) -> dict[str, TerraformResource]:
        """Extract supported Terraform resource declarations."""
        resources: dict[str, TerraformResource] = {}
        for document in documents:
            for resource_block in _block_list(
                document.content.get("resource"),
                block_name="resource",
                source=document.source,
            ):
                for resource_type, named_resources in resource_block.items():
                    mapping = self._resource_mappings.get(resource_type)
                    if mapping is None:
                        continue

                    resource_configs = _mapping(
                        named_resources,
                        path=f'resource "{resource_type}"',
                        source=document.source,
                    )
                    for resource_name, raw_config in resource_configs.items():
                        config = _mapping(
                            raw_config,
                            path=f'resource "{resource_type}" "{resource_name}"',
                            source=document.source,
                        )
                        address = f"{resource_type}.{resource_name}"
                        if address in resources:
                            message = (
                                f"duplicate Terraform resource address {address!r}"
                            )
                            raise TerraformParseError(message, source=document.source)

                        explicit_dependencies = self._explicit_dependencies(
                            config,
                            source=document.source,
                            path=address,
                        )
                        references = self._implicit_references(config)
                        provider = self._provider_for_resource(
                            config,
                            mapping=mapping,
                            providers=providers,
                        )
                        resources[address] = TerraformResource(
                            address=address,
                            resource_type=resource_type,
                            resource_name=resource_name,
                            node_type=mapping.node_type,
                            provider=provider,
                            source=document.source,
                            explicit_dependencies=explicit_dependencies,
                            references=tuple(sorted(set(references) - {address})),
                        )

        return resources

    def _explicit_dependencies(
        self,
        config: Mapping[str, object],
        *,
        source: str,
        path: str,
    ) -> tuple[str, ...]:
        """Extract explicit `depends_on` resource addresses."""
        if "depends_on" not in config:
            return ()

        raw_depends_on = config["depends_on"]
        if not isinstance(raw_depends_on, list):
            message = f"{path}.depends_on must be a list"
            raise TerraformParseError(message, source=source)

        return tuple(
            sorted(
                {
                    reference
                    for item in raw_depends_on
                    for reference in self._references_from_value(item)
                }
            )
        )

    def _implicit_references(self, config: Mapping[str, object]) -> tuple[str, ...]:
        """Extract implicit references from resource attributes."""
        references: set[str] = set()
        for key, value in config.items():
            if key in {"depends_on", "provider"}:
                continue
            references.update(self._references_from_value(value))
        return tuple(sorted(references))

    def _references_from_value(self, value: object) -> tuple[str, ...]:
        """Extract Terraform resource references from an HCL value."""
        if isinstance(value, str):
            return tuple(
                sorted(
                    {
                        f"{match.group('type')}.{match.group('name')}"
                        for match in self.REFERENCE_PATTERN.finditer(value)
                    }
                )
            )
        if isinstance(value, list):
            return tuple(
                sorted(
                    {
                        reference
                        for item in value
                        for reference in self._references_from_value(item)
                    }
                )
            )
        if isinstance(value, Mapping):
            return tuple(
                sorted(
                    {
                        reference
                        for item in value.values()
                        for reference in self._references_from_value(item)
                    }
                )
            )
        return ()

    def _provider_for_resource(
        self,
        config: Mapping[str, object],
        *,
        mapping: TerraformResourceMapping,
        providers: Mapping[str, TerraformProvider],
    ) -> str:
        """Return the provider address for a resource."""
        raw_provider = config.get("provider")
        if raw_provider is None:
            return mapping.provider

        provider = _terraform_expression(raw_provider)
        if provider:
            return provider

        return mapping.provider if mapping.provider in providers else mapping.provider

    def _node_from_resource(self, resource: TerraformResource) -> Node:
        """Create a ChokePoint node from a Terraform resource."""
        metadata: Metadata = {
            "terraform_type": resource.resource_type,
            "terraform_name": resource.resource_name,
            "terraform_address": resource.address,
            "source": resource.source,
            "explicit_depends_on": list(resource.explicit_dependencies),
            "references": list(resource.references),
        }
        return Node(
            id=resource.address,
            name=resource.resource_name,
            provider=resource.provider,
            node_type=resource.node_type,
            metadata=metadata,
        )

    def _add_edges(
        self,
        topology: Topology,
        resources: Mapping[str, TerraformResource],
    ) -> None:
        """Add dependency edges between supported Terraform resources."""
        edge_keys: set[tuple[str, str, Relationship]] = set()
        for resource in resources.values():
            for target in resource.explicit_dependencies:
                if target not in resources:
                    self._reject_missing_supported_dependency(resource, target)
                    continue
                _add_terraform_edge(topology, edge_keys, resource.address, target)

            for target in resource.references:
                if target not in resources:
                    continue
                _add_terraform_edge(topology, edge_keys, resource.address, target)

    def _reject_missing_supported_dependency(
        self,
        resource: TerraformResource,
        target: str,
    ) -> None:
        """Reject references to supported resource types missing from the parse set."""
        resource_type = target.split(".", maxsplit=1)[0]
        if resource_type not in self._resource_mappings:
            return

        message = (
            f"{resource.address} references supported resource {target!r}, "
            "but it was not found in the parsed Terraform files"
        )
        raise TerraformParseError(message, source=resource.source)


def _add_terraform_edge(
    topology: Topology,
    edge_keys: set[tuple[str, str, Relationship]],
    source: str,
    target: str,
) -> None:
    edge_key = (source, target, Relationship.DEPENDS_ON)
    if edge_key in edge_keys:
        return

    topology.add_edge(
        Edge(
            source=source,
            target=target,
            relationship=Relationship.DEPENDS_ON,
            metadata={"source": "terraform"},
        )
    )
    edge_keys.add(edge_key)


def parse_terraform_file(path: str | Path) -> Topology:
    """Parse one Terraform file.

    Args:
        path: `.tf` file path.

    Returns:
        Parsed topology.
    """
    return TerraformParser().parse_file(path)


def parse_terraform_files(paths: Iterable[str | Path]) -> Topology:
    """Parse multiple Terraform files.

    Args:
        paths: Terraform file paths.

    Returns:
        Parsed topology.
    """
    return TerraformParser().parse_files(paths)


def parse_terraform_directory(path: str | Path) -> Topology:
    """Parse all `.tf` files in a directory.

    Args:
        path: Directory containing `.tf` files.

    Returns:
        Parsed topology.
    """
    return TerraformParser().parse_directory(path)


def parse_terraform_text(payload: str, *, source: str = "<string>") -> Topology:
    """Parse Terraform HCL text.

    Args:
        payload: Terraform HCL text.
        source: Source label used in errors and metadata.

    Returns:
        Parsed topology.
    """
    return TerraformParser().parse_text(payload, source=source)


def _block_list(
    value: object, *, block_name: str, source: str
) -> tuple[Mapping[str, object], ...]:
    """Return a Terraform block list."""
    if value is None:
        return ()
    if not isinstance(value, list):
        message = f"Terraform {block_name!r} blocks must parse as a list"
        raise TerraformParseError(message, source=source)

    return tuple(_mapping(item, path=block_name, source=source) for item in value)


def _mapping(value: object, *, path: str, source: str) -> Mapping[str, object]:
    """Validate and return a Terraform mapping."""
    if not isinstance(value, Mapping):
        message = f"{path} must parse as a mapping"
        raise TerraformParseError(message, source=source)

    for key in value:
        if not isinstance(key, str) or not key:
            message = f"{path} keys must be non-empty strings"
            raise TerraformParseError(message, source=source)

    return cast(Mapping[str, object], value)


def _optional_string(value: object) -> str | None:
    """Return an optional Terraform string value."""
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _terraform_expression(value: object) -> str | None:
    """Normalize a Terraform expression string from python-hcl2 output."""
    if not isinstance(value, str):
        return None

    expression = value.strip()
    if expression.startswith("${") and expression.endswith("}"):
        expression = expression[2:-1].strip()

    return expression or None
