"""Advanced parser tests."""

from __future__ import annotations

import json
from pathlib import Path

from chokepoint.models import Node, NodeType, Topology
from chokepoint.parser import (
    AdvancedParseError,
    AutomaticDependencyInferrer,
    CloudFormationParser,
    DockerComposeParser,
    KubernetesParser,
    OpenTofuParser,
    PulumiParser,
    TerraformPlanParser,
    TerraformStateParser,
    parse_cloudformation_text,
    parse_docker_compose_text,
    parse_kubernetes_text,
    parse_pulumi_text,
    parse_terraform_plan_text,
    parse_terraform_state_text,
)


def test_kubernetes_parser_infers_service_and_ingress_dependencies() -> None:
    topology = KubernetesParser().parse_text(
        """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
  labels:
    app: api
spec:
  template:
    metadata:
      labels:
        app: api
---
apiVersion: v1
kind: Service
metadata:
  name: api
spec:
  selector:
    app: api
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: edge
spec:
  rules:
    - http:
        paths:
          - backend:
              service:
                name: api
                port:
                  number: 80
"""
    )

    assert set(topology.nodes) == {
        "k8s:default:deployment:api",
        "k8s:default:service:api",
        "k8s:default:ingress:edge",
    }
    assert {
        (edge.source, edge.target, edge.relationship.value) for edge in topology.edges
    } == {
        ("k8s:default:service:api", "k8s:default:deployment:api", "routes_to"),
        ("k8s:default:ingress:edge", "k8s:default:service:api", "routes_to"),
    }


def test_kubernetes_parser_handles_namespaced_secret_and_configmap_refs() -> None:
    topology = parse_kubernetes_text(
        """
apiVersion: v1
kind: Secret
metadata:
  name: app-secret
  namespace: prod
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
  namespace: prod
---
apiVersion: batch/v1
kind: Job
metadata:
  name: migrate
  namespace: prod
spec:
  template:
    spec:
      containers:
        - name: migrate
          envFrom:
            - secretRef:
                name: app-secret
            - configMapRef:
                name: app-config
"""
    )

    assert {(edge.source, edge.target) for edge in topology.edges} == {
        ("k8s:prod:job:migrate", "k8s:prod:secret:app-secret"),
        ("k8s:prod:job:migrate", "k8s:prod:configmap:app-config"),
    }


def test_kubernetes_parser_ignores_unsupported_kinds() -> None:
    topology = parse_kubernetes_text(
        """
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: api-budget
"""
    )

    assert topology.nodes == {}


def test_cloudformation_parser_supports_intrinsic_references() -> None:
    topology = CloudFormationParser().parse_text(
        """
Resources:
  DnsZone:
    Type: AWS::Route53::HostedZone
    Properties:
      Name: example.com
  AppRole:
    Type: AWS::IAM::Role
    DependsOn: DnsZone
    Properties:
      RoleName: app
  Bucket:
    Type: AWS::S3::Bucket
  Function:
    Type: AWS::Lambda::Function
    Properties:
      Role: !GetAtt AppRole.Arn
      Environment:
        Variables:
          BUCKET:
            Ref: Bucket
  Record:
    Type: AWS::Route53::RecordSet
    Properties:
      HostedZoneId:
        Fn::GetAtt:
          - DnsZone
          - Id
"""
    )

    assert topology.nodes["cloudformation:DnsZone"].node_type == NodeType.DNS
    assert ("cloudformation:AppRole", "cloudformation:DnsZone") in {
        (edge.source, edge.target) for edge in topology.edges
    }
    assert ("cloudformation:Function", "cloudformation:AppRole") in {
        (edge.source, edge.target) for edge in topology.edges
    }
    assert ("cloudformation:Function", "cloudformation:Bucket") in {
        (edge.source, edge.target) for edge in topology.edges
    }
    assert ("cloudformation:Record", "cloudformation:DnsZone") in {
        (edge.source, edge.target) for edge in topology.edges
    }


def test_cloudformation_parser_ignores_unsupported_resources() -> None:
    topology = parse_cloudformation_text(
        """
Resources:
  Topic:
    Type: AWS::SNS::Topic
"""
    )

    assert topology.nodes == {}


def test_docker_compose_parser_extracts_services_and_support_resources() -> None:
    topology = DockerComposeParser().parse_text(
        """
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
    )

    assert "compose:service:api" in topology.nodes
    assert "compose:network:backend" in topology.nodes
    assert "compose:secret:api_key" in topology.nodes
    assert ("compose:service:api", "compose:service:db") in {
        (edge.source, edge.target) for edge in topology.edges
    }


def test_pulumi_parser_extracts_dependencies() -> None:
    dependency = "urn:pulumi:dev::app::aws:route53/zone:Zone::dns"
    resource = "urn:pulumi:dev::app::aws:lambda/function:Function::api"
    payload = {
        "deployment": {
            "resources": [
                {"urn": dependency, "type": "aws:route53/zone:Zone"},
                {
                    "urn": resource,
                    "type": "aws:lambda/function:Function",
                    "dependencies": [dependency],
                },
            ]
        }
    }

    topology = PulumiParser().parse_text(json.dumps(payload))

    assert topology.nodes[f"pulumi:{dependency}"].node_type == NodeType.DNS
    assert (f"pulumi:{resource}", f"pulumi:{dependency}") in {
        (edge.source, edge.target) for edge in topology.edges
    }


def test_pulumi_parser_classifies_common_resource_types() -> None:
    payload = {
        "deployment": {
            "resources": [
                {
                    "urn": "urn:pulumi:dev::app::pulumi:pulumi:Stack::app",
                    "type": "pulumi:pulumi:Stack",
                },
                {"urn": "urn::lb", "type": "aws:elasticloadbalancing/loadBalancer"},
                {"urn": "urn::role", "type": "aws:iam/role:Role"},
                {"urn": "urn::secret", "type": "aws:secretsmanager/secret:Secret"},
                {"urn": "urn::db", "type": "aws:rds/instance:Instance"},
                {"urn": "urn::vpc", "type": "aws:ec2/vpc:Vpc"},
                {"urn": "urn::bucket", "type": "aws:s3/bucket:Bucket"},
                {"urn": "urn::app", "type": "custom:component:App"},
            ]
        }
    }

    topology = parse_pulumi_text(json.dumps(payload))

    assert [node.node_type for node in topology.nodes.values()] == [
        NodeType.LOAD_BALANCER,
        NodeType.IDENTITY,
        NodeType.SECRET,
        NodeType.DATABASE,
        NodeType.NETWORK,
        NodeType.STORAGE,
        NodeType.SERVICE,
    ]


def test_terraform_plan_and_state_parsers_support_json_outputs() -> None:
    plan_payload = {
        "planned_values": {
            "root_module": {
                "resources": [
                    {
                        "address": "aws_route53_zone.main",
                        "type": "aws_route53_zone",
                        "name": "main",
                        "provider_name": "registry.terraform.io/hashicorp/aws",
                    },
                    {
                        "address": "aws_lambda_function.api",
                        "type": "aws_lambda_function",
                        "name": "api",
                        "depends_on": ["aws_route53_zone.main"],
                    },
                ]
            }
        }
    }
    state_payload = {
        "values": {
            "root_module": {
                "resources": [
                    {
                        "address": "aws_s3_bucket.assets",
                        "type": "aws_s3_bucket",
                        "name": "assets",
                    }
                ]
            }
        }
    }

    plan = TerraformPlanParser().parse_text(json.dumps(plan_payload))
    state = TerraformStateParser().parse_text(json.dumps(state_payload))

    assert plan.nodes["aws_route53_zone.main"].node_type == NodeType.DNS
    assert ("aws_lambda_function.api", "aws_route53_zone.main") in {
        (edge.source, edge.target) for edge in plan.edges
    }
    assert state.nodes["aws_s3_bucket.assets"].node_type == NodeType.STORAGE


def test_terraform_plan_parser_uses_configuration_references_in_module_calls() -> None:
    payload = {
        "planned_values": {
            "root_module": {
                "resources": [
                    {"address": "aws_s3_bucket.assets", "type": "aws_s3_bucket"},
                ],
                "child_modules": [
                    {
                        "resources": [
                            {
                                "address": "module.app.aws_lambda_function.api",
                                "type": "aws_lambda_function",
                            }
                        ]
                    }
                ],
            }
        },
        "configuration": {
            "root_module": {
                "module_calls": {
                    "app": {
                        "module": {
                            "resources": [
                                {
                                    "address": "module.app.aws_lambda_function.api",
                                    "expressions": {
                                        "bucket": {
                                            "references": ["aws_s3_bucket.assets"]
                                        }
                                    },
                                }
                            ]
                        }
                    }
                }
            }
        },
    }

    topology = parse_terraform_plan_text(json.dumps(payload))

    assert ("module.app.aws_lambda_function.api", "aws_s3_bucket.assets") in {
        (edge.source, edge.target) for edge in topology.edges
    }


def test_terraform_state_parser_supports_legacy_state_shape() -> None:
    topology = parse_terraform_state_text(
        json.dumps(
            {
                "resources": [
                    {
                        "type": "aws_iam_role",
                        "name": "api",
                        "provider": "provider.aws",
                    }
                ]
            }
        )
    )

    assert topology.nodes["aws_iam_role.api"].node_type == NodeType.IDENTITY


def test_opentofu_parser_uses_terraform_compatible_hcl() -> None:
    topology = OpenTofuParser().parse_text(
        """
resource "aws_route53_zone" "main" {
  name = "example.com"
}
"""
    )

    assert topology.nodes["aws_route53_zone.main"].metadata["terraform_type"] == (
        "aws_route53_zone"
    )


def test_automatic_dependency_inferrer_uses_metadata_references() -> None:
    topology = Topology()
    topology.add_node(
        Node(
            id="api",
            name="api",
            provider="app",
            node_type=NodeType.SERVICE,
            metadata={"references": ["dns"]},
        )
    )
    topology.add_node(
        Node(id="dns", name="dns", provider="cloudflare", node_type=NodeType.DNS)
    )

    inferred = AutomaticDependencyInferrer().infer(topology)

    assert [(edge.source, edge.target) for edge in inferred.edges] == [("api", "dns")]


def test_automatic_dependency_inferrer_ignores_missing_and_self_references() -> None:
    topology = Topology()
    topology.add_node(
        Node(
            id="api",
            name="api",
            provider="app",
            node_type=NodeType.SERVICE,
            metadata={"references": ["api", "missing", ["api"]]},
        )
    )

    inferred = AutomaticDependencyInferrer().infer(topology)

    assert inferred.edges == []


def test_advanced_parser_file_entrypoints(tmp_path: Path) -> None:
    k8s_path = tmp_path / "deploy.yaml"
    k8s_path.write_text(
        "apiVersion: v1\nkind: Service\nmetadata:\n  name: api\n",
        encoding="utf-8",
    )
    cfn_path = tmp_path / "template.yaml"
    cfn_path.write_text(
        "Resources:\n  Zone:\n    Type: AWS::Route53::HostedZone\n",
        encoding="utf-8",
    )
    compose_path = tmp_path / "compose.yaml"
    compose_path.write_text("services:\n  api: {}\n", encoding="utf-8")
    pulumi_path = tmp_path / "stack.json"
    pulumi_path.write_text(
        json.dumps(
            {
                "deployment": {
                    "resources": [{"urn": "urn::api", "type": "custom:component:App"}]
                }
            }
        ),
        encoding="utf-8",
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "planned_values": {
                    "root_module": {
                        "resources": [
                            {"address": "aws_s3_bucket.assets", "type": "aws_s3_bucket"}
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "values": {
                    "root_module": {
                        "resources": [
                            {"address": "aws_s3_bucket.assets", "type": "aws_s3_bucket"}
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    assert KubernetesParser().parse_file(k8s_path).nodes
    assert CloudFormationParser().parse_file(cfn_path).nodes
    assert DockerComposeParser().parse_file(compose_path).nodes
    assert PulumiParser().parse_file(pulumi_path).nodes
    assert TerraformPlanParser().parse_file(plan_path).nodes
    assert TerraformStateParser().parse_file(state_path).nodes


def test_advanced_parser_errors_are_helpful(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    errors = [
        lambda: KubernetesParser().parse_file(missing),
        lambda: parse_kubernetes_text(""),
        lambda: parse_cloudformation_text("---\nkind: Service\n---\nkind: Service\n"),
        lambda: parse_docker_compose_text("services: ["),
        lambda: parse_pulumi_text("{"),
        lambda: parse_pulumi_text(json.dumps({"deployment": {"resources": {}}})),
        lambda: parse_terraform_plan_text(json.dumps([])),
    ]

    for trigger in errors:
        try:
            trigger()
        except AdvancedParseError as error:
            assert str(error)
        else:
            raise AssertionError("expected AdvancedParseError")
