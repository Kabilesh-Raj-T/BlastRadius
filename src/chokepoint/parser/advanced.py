"""Advanced infrastructure parsers and dependency inference."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import cast

import yaml

from chokepoint.models import Edge, Node, NodeType, Relationship, Topology
from chokepoint.models.topology import JsonValue, Metadata
from chokepoint.parser.terraform_parser import TerraformParser


class AdvancedParseError(ValueError):
    """Raised when an advanced infrastructure document cannot be parsed."""

    def __init__(self, message: str, *, source: str | None = None) -> None:
        """Create an advanced parser error.

        Args:
            message: Human-readable parse failure.
            source: Optional source path or label.
        """
        self.message = message
        self.source = source
        detail = f"{source}: {message}" if source else message
        super().__init__(detail)


class KubernetesParser:
    """Parse Kubernetes YAML manifests into a topology."""

    WORKLOAD_KINDS = frozenset({"Deployment", "StatefulSet", "DaemonSet", "Job"})

    def parse_file(self, path: str | Path) -> Topology:
        """Parse a Kubernetes manifest file."""
        source_path = Path(path)
        return self.parse_text(
            _read_text(source_path, parser_name="Kubernetes"),
            source=str(source_path),
        )

    def parse_text(self, payload: str, *, source: str = "<string>") -> Topology:
        """Parse Kubernetes YAML manifest text."""
        documents = _load_yaml_documents(payload, source=source)
        topology = Topology()
        service_selectors: dict[str, Mapping[str, object]] = {}
        workload_labels: dict[str, Mapping[str, object]] = {}
        pending_edges: list[Edge] = []

        for document in documents:
            item = _mapping(document, path="$", source=source)
            kind = _string(item.get("kind"), path="$.kind", source=source)
            metadata = _mapping(item.get("metadata"), path="$.metadata", source=source)
            name = _string(metadata.get("name"), path="$.metadata.name", source=source)
            namespace = _optional_string(metadata.get("namespace")) or "default"
            node_id = _kubernetes_id(namespace, kind, name)

            node_type = _kubernetes_node_type(kind)
            if node_type is None:
                continue

            topology.add_node(
                Node(
                    id=node_id,
                    name=name,
                    provider="kubernetes",
                    node_type=node_type,
                    metadata={
                        "source": source,
                        "platform": "kubernetes",
                        "kind": kind,
                        "namespace": namespace,
                    },
                )
            )

            spec = _optional_mapping(item.get("spec"))
            if kind == "Service":
                service_selectors[node_id] = _optional_mapping(spec.get("selector"))
            if kind in self.WORKLOAD_KINDS:
                workload_labels[node_id] = _workload_labels(item)
                pending_edges.extend(_kubernetes_secret_edges(node_id, item, namespace))
            if kind == "Ingress":
                pending_edges.extend(
                    _kubernetes_ingress_edges(node_id, spec, namespace)
                )

        _add_matching_service_edges(topology, service_selectors, workload_labels)
        _add_existing_edges(topology, pending_edges)
        return topology


class CloudFormationParser:
    """Parse CloudFormation JSON or YAML templates into a topology."""

    TYPE_MAPPINGS: Mapping[str, NodeType] = {
        "AWS::Route53::HostedZone": NodeType.DNS,
        "AWS::Route53::RecordSet": NodeType.DNS,
        "AWS::ElasticLoadBalancingV2::LoadBalancer": NodeType.LOAD_BALANCER,
        "AWS::ElasticLoadBalancing::LoadBalancer": NodeType.LOAD_BALANCER,
        "AWS::IAM::Role": NodeType.IDENTITY,
        "AWS::IAM::Policy": NodeType.IDENTITY,
        "AWS::RDS::DBInstance": NodeType.DATABASE,
        "AWS::DynamoDB::Table": NodeType.DATABASE,
        "AWS::S3::Bucket": NodeType.STORAGE,
        "AWS::SecretsManager::Secret": NodeType.SECRET,
        "AWS::EC2::VPC": NodeType.NETWORK,
        "AWS::EC2::Subnet": NodeType.NETWORK,
        "AWS::EC2::SecurityGroup": NodeType.NETWORK,
        "AWS::Lambda::Function": NodeType.SERVICE,
        "AWS::ECS::Service": NodeType.SERVICE,
    }

    def parse_file(self, path: str | Path) -> Topology:
        """Parse one CloudFormation template file."""
        source_path = Path(path)
        return self.parse_text(
            _read_text(source_path, parser_name="CloudFormation"),
            source=str(source_path),
        )

    def parse_text(self, payload: str, *, source: str = "<string>") -> Topology:
        """Parse CloudFormation template text."""
        template = _load_yaml_mapping(payload, source=source)
        resources = _optional_mapping(template.get("Resources"))
        topology = Topology()
        pending_edges: list[Edge] = []

        for logical_id, raw_resource in resources.items():
            resource = _mapping(
                raw_resource,
                path=f"$.Resources.{logical_id}",
                source=source,
            )
            resource_type = _string(
                resource.get("Type"),
                path=f"$.Resources.{logical_id}.Type",
                source=source,
            )
            node_type = self.TYPE_MAPPINGS.get(resource_type)
            if node_type is None:
                continue

            node_id = f"cloudformation:{logical_id}"
            topology.add_node(
                Node(
                    id=node_id,
                    name=logical_id,
                    provider="aws",
                    node_type=node_type,
                    metadata={
                        "source": source,
                        "platform": "cloudformation",
                        "cloudformation_type": resource_type,
                    },
                )
            )
            for target in _cloudformation_dependencies(resource):
                pending_edges.append(
                    Edge(
                        source=node_id,
                        target=f"cloudformation:{target}",
                        relationship=Relationship.DEPENDS_ON,
                        metadata={"source": "cloudformation"},
                    )
                )

        _add_existing_edges(topology, pending_edges)
        return topology


class DockerComposeParser:
    """Parse Docker Compose YAML into a topology."""

    def parse_file(self, path: str | Path) -> Topology:
        """Parse a Docker Compose file."""
        source_path = Path(path)
        return self.parse_text(
            _read_text(source_path, parser_name="Docker Compose"),
            source=str(source_path),
        )

    def parse_text(self, payload: str, *, source: str = "<string>") -> Topology:
        """Parse Docker Compose YAML text."""
        document = _load_yaml_mapping(payload, source=source)
        topology = Topology()
        services = _optional_mapping(document.get("services"))

        for service_name, raw_service in services.items():
            config = _optional_mapping(raw_service)
            topology.add_node(
                Node(
                    id=f"compose:service:{service_name}",
                    name=service_name,
                    provider="docker",
                    node_type=NodeType.SERVICE,
                    metadata={"source": source, "platform": "docker-compose"},
                )
            )
            _add_compose_support_nodes(topology, service_name, config, source=source)

        for service_name, raw_service in services.items():
            config = _optional_mapping(raw_service)
            source_id = f"compose:service:{service_name}"
            for dependency in _compose_depends_on(config.get("depends_on")):
                _try_add_edge(
                    topology,
                    source=source_id,
                    target=f"compose:service:{dependency}",
                    metadata_source="docker-compose",
                )
            _add_compose_support_edges(topology, service_name, config)

        return topology


class PulumiParser:
    """Parse Pulumi stack export JSON into a topology."""

    def parse_file(self, path: str | Path) -> Topology:
        """Parse a Pulumi stack export file."""
        source_path = Path(path)
        return self.parse_text(
            _read_text(source_path, parser_name="Pulumi"),
            source=str(source_path),
        )

    def parse_text(self, payload: str, *, source: str = "<string>") -> Topology:
        """Parse Pulumi stack export JSON text."""
        document = _load_json_mapping(payload, source=source)
        deployment = _optional_mapping(document.get("deployment"))
        resources = _sequence(
            deployment.get("resources"),
            path="$.deployment.resources",
            source=source,
        )
        topology = Topology()
        dependencies: list[tuple[str, str]] = []

        for raw_resource in resources:
            resource = _mapping(
                raw_resource,
                path="$.deployment.resources[]",
                source=source,
            )
            urn = _string(resource.get("urn"), path="resource.urn", source=source)
            pulumi_type = _string(
                resource.get("type"),
                path="resource.type",
                source=source,
            )
            if pulumi_type == "pulumi:pulumi:Stack":
                continue
            node_type = _pulumi_node_type(pulumi_type)
            provider = _provider_from_type(pulumi_type)
            topology.add_node(
                Node(
                    id=f"pulumi:{urn}",
                    name=urn.rsplit("::", maxsplit=1)[-1],
                    provider=provider,
                    node_type=node_type,
                    metadata={
                        "source": source,
                        "platform": "pulumi",
                        "pulumi_type": pulumi_type,
                        "pulumi_urn": urn,
                    },
                )
            )
            for dependency in _string_sequence(resource.get("dependencies")):
                dependencies.append((f"pulumi:{urn}", f"pulumi:{dependency}"))

        for source_id, target_id in dependencies:
            _try_add_edge(
                topology,
                source=source_id,
                target=target_id,
                metadata_source="pulumi",
            )
        return topology


class TerraformPlanParser:
    """Parse Terraform or OpenTofu plan JSON into a topology."""

    def parse_file(self, path: str | Path) -> Topology:
        """Parse a Terraform plan JSON file."""
        source_path = Path(path)
        return self.parse_text(
            _read_text(source_path, parser_name="Terraform plan"),
            source=str(source_path),
        )

    def parse_text(self, payload: str, *, source: str = "<string>") -> Topology:
        """Parse Terraform plan JSON text."""
        document = _load_json_mapping(payload, source=source)
        planned_values = _optional_mapping(document.get("planned_values"))
        root_module = _optional_mapping(planned_values.get("root_module"))
        topology = _terraform_json_module_topology(
            root_module,
            source=source,
            platform="terraform-plan",
        )
        configuration = _optional_mapping(document.get("configuration"))
        _add_configuration_references(
            topology,
            _optional_mapping(configuration.get("root_module")),
        )
        return AutomaticDependencyInferrer().infer(topology)


class TerraformStateParser:
    """Parse Terraform or OpenTofu state JSON into a topology."""

    def parse_file(self, path: str | Path) -> Topology:
        """Parse a Terraform state JSON file."""
        source_path = Path(path)
        return self.parse_text(
            _read_text(source_path, parser_name="Terraform state"),
            source=str(source_path),
        )

    def parse_text(self, payload: str, *, source: str = "<string>") -> Topology:
        """Parse Terraform state JSON text."""
        document = _load_json_mapping(payload, source=source)
        values = _optional_mapping(document.get("values"))
        root_module = _optional_mapping(values.get("root_module"))
        if root_module:
            return AutomaticDependencyInferrer().infer(
                _terraform_json_module_topology(
                    root_module,
                    source=source,
                    platform="terraform-state",
                )
            )
        return _legacy_state_topology(document, source=source)


class OpenTofuParser(TerraformParser):
    """Parse OpenTofu HCL files using Terraform-compatible semantics."""


class AutomaticDependencyInferrer:
    """Infer dependency edges from common metadata reference fields."""

    REFERENCE_FIELDS = frozenset(
        {
            "depends_on",
            "dependencies",
            "references",
            "ref",
            "refs",
            "target",
            "targets",
        }
    )

    def infer(self, topology: Topology) -> Topology:
        """Return a copy of the topology with inferred dependency edges."""
        inferred = Topology.model_validate(topology.model_dump())
        for node in tuple(inferred.nodes.values()):
            for target in self._metadata_references(node.metadata):
                if target in inferred.nodes:
                    _try_add_edge(
                        inferred,
                        source=node.id,
                        target=target,
                        metadata_source="inference",
                    )
        return inferred

    def _metadata_references(self, metadata: Metadata) -> tuple[str, ...]:
        references: set[str] = set()
        for key, value in metadata.items():
            if key in self.REFERENCE_FIELDS:
                references.update(_flatten_strings(value))
        return tuple(sorted(references))


def parse_kubernetes_text(payload: str, *, source: str = "<string>") -> Topology:
    """Parse Kubernetes manifest text."""
    return KubernetesParser().parse_text(payload, source=source)


def parse_cloudformation_text(payload: str, *, source: str = "<string>") -> Topology:
    """Parse CloudFormation template text."""
    return CloudFormationParser().parse_text(payload, source=source)


def parse_docker_compose_text(payload: str, *, source: str = "<string>") -> Topology:
    """Parse Docker Compose YAML text."""
    return DockerComposeParser().parse_text(payload, source=source)


def parse_pulumi_text(payload: str, *, source: str = "<string>") -> Topology:
    """Parse Pulumi stack export JSON text."""
    return PulumiParser().parse_text(payload, source=source)


def parse_terraform_plan_text(payload: str, *, source: str = "<string>") -> Topology:
    """Parse Terraform plan JSON text."""
    return TerraformPlanParser().parse_text(payload, source=source)


def parse_terraform_state_text(payload: str, *, source: str = "<string>") -> Topology:
    """Parse Terraform state JSON text."""
    return TerraformStateParser().parse_text(payload, source=source)


def _read_text(path: Path, *, parser_name: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        message = f"unable to read {parser_name} file: {error.strerror or error}"
        raise AdvancedParseError(message, source=str(path)) from error


def _load_yaml_documents(payload: str, *, source: str) -> tuple[object, ...]:
    try:
        documents = tuple(
            document
            for document in yaml.load_all(payload, Loader=_CloudFormationYamlLoader)
            if document is not None
        )
    except yaml.YAMLError as error:
        raise AdvancedParseError(f"malformed YAML: {error}", source=source) from error
    if not documents:
        raise AdvancedParseError("document is empty", source=source)
    return documents


def _load_yaml_mapping(payload: str, *, source: str) -> Mapping[str, object]:
    documents = _load_yaml_documents(payload, source=source)
    if len(documents) != 1:
        raise AdvancedParseError("expected exactly one YAML document", source=source)
    return _mapping(documents[0], path="$", source=source)


def _load_json_mapping(payload: str, *, source: str) -> Mapping[str, object]:
    try:
        loaded = json.loads(payload)
    except json.JSONDecodeError as error:
        message = f"malformed JSON: {error.msg}"
        raise AdvancedParseError(message, source=source) from error
    return _mapping(loaded, path="$", source=source)


class _CloudFormationYamlLoader(yaml.SafeLoader):  # type: ignore[misc]
    """YAML loader that preserves CloudFormation intrinsic tags as mappings."""


def _unknown_yaml_tag(
    loader: yaml.SafeLoader,
    tag_suffix: str,
    node: yaml.Node,
) -> object:
    tag = node.tag.lstrip("!")
    if tag_suffix:
        tag = tag_suffix
    if isinstance(node, yaml.ScalarNode):
        return {tag: loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {tag: loader.construct_sequence(node)}
    return {tag: loader.construct_mapping(node)}


_CloudFormationYamlLoader.add_multi_constructor("!", _unknown_yaml_tag)


def _mapping(value: object, *, path: str, source: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AdvancedParseError(f"{path} must be a mapping", source=source)
    for key in value:
        if not isinstance(key, str):
            raise AdvancedParseError(f"{path} keys must be strings", source=source)
    return cast(Mapping[str, object], value)


def _optional_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return {}


def _sequence(value: object, *, path: str, source: str) -> tuple[object, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise AdvancedParseError(f"{path} must be a list", source=source)
    return tuple(value)


def _string(value: object, *, path: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdvancedParseError(f"{path} must be a non-empty string", source=source)
    return value.strip()


def _optional_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _string_sequence(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str) and item)
    return ()


def _kubernetes_id(namespace: str, kind: str, name: str) -> str:
    return f"k8s:{namespace}:{kind.lower()}:{name}"


def _kubernetes_node_type(kind: str) -> NodeType | None:
    return {
        "ConfigMap": NodeType.EXTERNAL,
        "DaemonSet": NodeType.COMPUTE,
        "Deployment": NodeType.SERVICE,
        "Ingress": NodeType.LOAD_BALANCER,
        "Job": NodeType.COMPUTE,
        "Secret": NodeType.SECRET,
        "Service": NodeType.LOAD_BALANCER,
        "StatefulSet": NodeType.SERVICE,
    }.get(kind)


def _workload_labels(item: Mapping[str, object]) -> Mapping[str, object]:
    metadata = _optional_mapping(item.get("metadata"))
    labels = _optional_mapping(metadata.get("labels"))
    spec = _optional_mapping(item.get("spec"))
    template = _optional_mapping(spec.get("template"))
    template_metadata = _optional_mapping(template.get("metadata"))
    template_labels = _optional_mapping(template_metadata.get("labels"))
    return template_labels or labels


def _kubernetes_secret_edges(
    source_id: str,
    item: Mapping[str, object],
    namespace: str,
) -> list[Edge]:
    edges: list[Edge] = []
    for reference_type, secret_name in _walk_kubernetes_references(item):
        node_type = "secret" if reference_type == "secretRef" else "configmap"
        target = f"k8s:{namespace}:{node_type}:{secret_name}"
        edges.append(
            Edge(
                source=source_id,
                target=target,
                relationship=Relationship.DEPENDS_ON,
                metadata={"source": "kubernetes"},
            )
        )
    return edges


def _walk_kubernetes_references(value: object) -> tuple[tuple[str, str], ...]:
    references: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        for field_name in ("secretRef", "configMapRef"):
            ref = _optional_mapping(mapping.get(field_name))
            name = _optional_string(ref.get("name"))
            if name:
                references.append((field_name, name))
        for item in mapping.values():
            references.extend(_walk_kubernetes_references(item))
    elif isinstance(value, list):
        for item in value:
            references.extend(_walk_kubernetes_references(item))
    return tuple(references)


def _kubernetes_ingress_edges(
    source_id: str,
    spec: Mapping[str, object],
    namespace: str,
) -> list[Edge]:
    edges: list[Edge] = []
    for service_name in _walk_ingress_services(spec):
        edges.append(
            Edge(
                source=source_id,
                target=_kubernetes_id(namespace, "Service", service_name),
                relationship=Relationship.ROUTES_TO,
                metadata={"source": "kubernetes"},
            )
        )
    return edges


def _walk_ingress_services(value: object) -> tuple[str, ...]:
    services: list[str] = []
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        service = _optional_mapping(mapping.get("service"))
        name = _optional_string(service.get("name"))
        if name:
            services.append(name)
        backend_service_name = _optional_string(mapping.get("serviceName"))
        if backend_service_name:
            services.append(backend_service_name)
        for item in mapping.values():
            services.extend(_walk_ingress_services(item))
    elif isinstance(value, list):
        for item in value:
            services.extend(_walk_ingress_services(item))
    return tuple(sorted(set(services)))


def _add_matching_service_edges(
    topology: Topology,
    service_selectors: Mapping[str, Mapping[str, object]],
    workload_labels: Mapping[str, Mapping[str, object]],
) -> None:
    for service_id, selector in service_selectors.items():
        if not selector:
            continue
        for workload_id, labels in workload_labels.items():
            if all(labels.get(key) == value for key, value in selector.items()):
                _try_add_edge(
                    topology,
                    source=service_id,
                    target=workload_id,
                    relationship=Relationship.ROUTES_TO,
                    metadata_source="kubernetes",
                )


def _add_existing_edges(topology: Topology, edges: Iterable[Edge]) -> None:
    for edge in edges:
        if edge.source in topology.nodes and edge.target in topology.nodes:
            _try_add_edge(
                topology,
                source=edge.source,
                target=edge.target,
                relationship=edge.relationship,
                metadata_source=str(edge.metadata.get("source", "advanced")),
            )


def _cloudformation_dependencies(resource: Mapping[str, object]) -> tuple[str, ...]:
    dependencies = set(_string_sequence(resource.get("DependsOn")))
    dependencies.update(_cloudformation_refs(resource.get("Properties")))
    return tuple(sorted(dependencies))


def _cloudformation_refs(value: object) -> tuple[str, ...]:
    refs: list[str] = []
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        ref = _optional_string(mapping.get("Ref"))
        if ref:
            refs.append(ref)
        get_att = mapping.get("Fn::GetAtt") or mapping.get("GetAtt")
        if isinstance(get_att, str):
            refs.append(get_att.split(".", maxsplit=1)[0])
        elif isinstance(get_att, list) and get_att and isinstance(get_att[0], str):
            refs.append(get_att[0])
        for item in mapping.values():
            refs.extend(_cloudformation_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.extend(_cloudformation_refs(item))
    return tuple(sorted(set(refs)))


def _compose_depends_on(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str))
    if isinstance(value, Mapping):
        return tuple(key for key in value if isinstance(key, str))
    return ()


def _add_compose_support_nodes(
    topology: Topology,
    service_name: str,
    config: Mapping[str, object],
    *,
    source: str,
) -> None:
    del service_name
    for category, node_type in (
        ("networks", NodeType.NETWORK),
        ("volumes", NodeType.STORAGE),
        ("secrets", NodeType.SECRET),
    ):
        for item in _compose_names(config.get(category)):
            node_id = f"compose:{category[:-1]}:{item}"
            if node_id not in topology.nodes:
                topology.add_node(
                    Node(
                        id=node_id,
                        name=item,
                        provider="docker",
                        node_type=node_type,
                        metadata={"source": source, "platform": "docker-compose"},
                    )
                )


def _add_compose_support_edges(
    topology: Topology,
    service_name: str,
    config: Mapping[str, object],
) -> None:
    source_id = f"compose:service:{service_name}"
    for category in ("networks", "volumes", "secrets"):
        for item in _compose_names(config.get(category)):
            _try_add_edge(
                topology,
                source=source_id,
                target=f"compose:{category[:-1]}:{item}",
                metadata_source="docker-compose",
            )


def _compose_names(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            if isinstance(item, str):
                names.append(item.split(":", maxsplit=1)[0])
            elif isinstance(item, Mapping):
                source = item.get("source") or item.get("target")
                if isinstance(source, str):
                    names.append(source)
        return tuple(names)
    if isinstance(value, Mapping):
        return tuple(key for key in value if isinstance(key, str))
    return ()


def _pulumi_node_type(pulumi_type: str) -> NodeType:
    text = pulumi_type.lower()
    rules = (
        (("route53", "dns"), NodeType.DNS),
        (("loadbalancer", "loadbalancing"), NodeType.LOAD_BALANCER),
        (("iam", "identity"), NodeType.IDENTITY),
        (("secret",), NodeType.SECRET),
        (("database", "rds", "sql"), NodeType.DATABASE),
        (("network", "vpc", "subnet"), NodeType.NETWORK),
        (("bucket", "storage"), NodeType.STORAGE),
    )
    for needles, node_type in rules:
        if any(needle in text for needle in needles):
            return node_type
    return NodeType.SERVICE


def _provider_from_type(resource_type: str) -> str:
    return resource_type.split(":", maxsplit=1)[0].lower() or "pulumi"


def _terraform_json_module_topology(
    module: Mapping[str, object],
    *,
    source: str,
    platform: str,
) -> Topology:
    topology = Topology()
    _add_terraform_json_module(topology, module, source=source, platform=platform)
    return topology


def _add_terraform_json_module(
    topology: Topology,
    module: Mapping[str, object],
    *,
    source: str,
    platform: str,
) -> None:
    resources = _sequence(module.get("resources"), path="resources", source=source)
    for raw_resource in resources:
        resource = _mapping(raw_resource, path="resource", source=source)
        address = _string(
            resource.get("address"),
            path="resource.address",
            source=source,
        )
        resource_type = _string(
            resource.get("type"),
            path="resource.type",
            source=source,
        )
        provider = _provider_from_terraform_json(resource)
        if address not in topology.nodes:
            topology.add_node(
                Node(
                    id=address,
                    name=address.split(".", maxsplit=1)[-1],
                    provider=provider,
                    node_type=_terraform_json_node_type(resource_type),
                    metadata={
                        "source": source,
                        "platform": platform,
                        "terraform_type": resource_type,
                        "references": list(
                            _string_sequence(resource.get("depends_on"))
                        ),
                    },
                )
            )
    child_modules = _sequence(
        module.get("child_modules"),
        path="child_modules",
        source=source,
    )
    for child in child_modules:
        _add_terraform_json_module(
            topology,
            _mapping(child, path="child_module", source=source),
            source=source,
            platform=platform,
        )


def _add_configuration_references(
    topology: Topology,
    module: Mapping[str, object],
) -> None:
    for raw_resource in _optional_sequence(module.get("resources")):
        resource = _optional_mapping(raw_resource)
        address = _optional_string(resource.get("address"))
        if address is None or address not in topology.nodes:
            continue
        expressions = _optional_mapping(resource.get("expressions"))
        references = _terraform_expression_references(expressions)
        node = topology.nodes[address]
        metadata = dict(node.metadata)
        reference_values = cast(
            list[JsonValue],
            sorted({*_flatten_strings(metadata.get("references")), *references}),
        )
        metadata["references"] = reference_values
        topology.nodes[address] = Node(
            id=node.id,
            name=node.name,
            provider=node.provider,
            node_type=node.node_type,
            metadata=metadata,
        )
    for child in _configuration_child_modules(module.get("module_calls")):
        _add_configuration_references(topology, _optional_mapping(child))


def _optional_sequence(value: object) -> tuple[object, ...]:
    return tuple(value) if isinstance(value, list) else ()


def _configuration_child_modules(value: object) -> tuple[object, ...]:
    if isinstance(value, Mapping):
        return tuple(
            _optional_mapping(module_call).get("module")
            for module_call in value.values()
        )
    return _optional_sequence(value)


def _terraform_expression_references(expressions: Mapping[str, object]) -> set[str]:
    references: set[str] = set()
    for value in expressions.values():
        mapping = _optional_mapping(value)
        references.update(_string_sequence(mapping.get("references")))
    return references


def _provider_from_terraform_json(resource: Mapping[str, object]) -> str:
    provider_name = _optional_string(resource.get("provider_name"))
    if provider_name:
        return provider_name.rsplit("/", maxsplit=1)[-1]
    return "terraform"


def _terraform_json_node_type(resource_type: str) -> NodeType:
    mapping = TerraformParser().resource_mappings.get(resource_type)
    if mapping is not None:
        return mapping.node_type
    return _pulumi_node_type(resource_type)


def _legacy_state_topology(document: Mapping[str, object], *, source: str) -> Topology:
    topology = Topology()
    resources = _sequence(document.get("resources"), path="$.resources", source=source)
    for raw_resource in resources:
        resource = _mapping(raw_resource, path="$.resources[]", source=source)
        resource_type = _string(
            resource.get("type"),
            path="resource.type",
            source=source,
        )
        name = _string(resource.get("name"), path="resource.name", source=source)
        node_id = f"{resource_type}.{name}"
        topology.add_node(
            Node(
                id=node_id,
                name=name,
                provider=_optional_string(resource.get("provider")) or "terraform",
                node_type=_terraform_json_node_type(resource_type),
                metadata={"source": source, "platform": "terraform-state"},
            )
        )
    return topology


def _flatten_strings(value: JsonValue | object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(
            item
            for nested in value
            for item in _flatten_strings(nested)
            if isinstance(item, str)
        )
    return ()


def _try_add_edge(
    topology: Topology,
    *,
    source: str,
    target: str,
    relationship: Relationship = Relationship.DEPENDS_ON,
    metadata_source: str,
) -> None:
    if source not in topology.nodes or target not in topology.nodes or source == target:
        return
    edge = Edge(
        source=source,
        target=target,
        relationship=relationship,
        metadata={"source": metadata_source},
    )
    edge_key = (edge.source, edge.target, edge.relationship)
    if any(
        (item.source, item.target, item.relationship) == edge_key
        for item in topology.edges
    ):
        return
    topology.add_edge(edge)
