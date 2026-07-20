"""Unit tests for Terraform topology ingestion."""

from pathlib import Path

import pytest

from chokepoint.models import NodeType, Relationship, Topology
from chokepoint.parser import (
    TERRAFORM_RESOURCE_MAPPINGS,
    TerraformParseError,
    TerraformParser,
    TerraformResourceMapping,
    parse_terraform_directory,
    parse_terraform_file,
    parse_terraform_files,
    parse_terraform_text,
)
from chokepoint.report import RiskAnalyzer, RiskCategory, RiskLevel

TERRAFORM_EXAMPLE = """
provider "aws" {
  region = "us-east-1"
}

provider "aws" {
  alias = "west"
  region = "us-west-2"
}

resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
}

resource "aws_security_group" "frontend" {
  vpc_id = aws_vpc.main.id
}

resource "aws_iam_role" "app" {
  name = "app"
}

resource "aws_lb" "frontend" {
  provider = aws.west
  depends_on = [aws_iam_role.app]
  security_groups = [aws_security_group.frontend.id]
}

resource "aws_route53_zone" "primary" {
  name = "example.com"
}

resource "aws_route53_record" "frontend" {
  zone_id = aws_route53_zone.primary.zone_id

  alias {
    name = aws_lb.frontend.dns_name
    zone_id = aws_lb.frontend.zone_id
    evaluate_target_health = true
  }
}
"""
EXPECTED_MONITORING_BLAST_RADIUS = 2


def edge_set(payload: str) -> set[tuple[str, str, Relationship]]:
    topology = parse_terraform_text(payload)
    return {(edge.source, edge.target, edge.relationship) for edge in topology.edges}


def test_resource_mapping_contains_required_examples() -> None:
    assert TERRAFORM_RESOURCE_MAPPINGS["aws_route53_zone"].node_type is NodeType.DNS
    assert TERRAFORM_RESOURCE_MAPPINGS["aws_lb"].node_type is NodeType.LOAD_BALANCER
    assert TERRAFORM_RESOURCE_MAPPINGS["aws_iam_role"].node_type is NodeType.IDENTITY
    assert TERRAFORM_RESOURCE_MAPPINGS["aws_route"].node_type is NodeType.NETWORK
    assert TERRAFORM_RESOURCE_MAPPINGS["aws_route_table"].node_type is NodeType.NETWORK
    assert (
        TERRAFORM_RESOURCE_MAPPINGS["aws_iam_role_policy_attachment"].node_type
        is NodeType.IDENTITY
    )
    assert (
        TERRAFORM_RESOURCE_MAPPINGS["aws_cloudwatch_log_group"].node_type
        is NodeType.EXTERNAL
    )


def test_parse_terraform_resources_into_topology_nodes() -> None:
    topology = parse_terraform_text(TERRAFORM_EXAMPLE, source="main.tf")

    assert set(topology.nodes) == {
        "aws_vpc.main",
        "aws_security_group.frontend",
        "aws_iam_role.app",
        "aws_lb.frontend",
        "aws_route53_zone.primary",
        "aws_route53_record.frontend",
    }
    assert topology.nodes["aws_route53_zone.primary"].node_type is NodeType.DNS
    assert topology.nodes["aws_route53_record.frontend"].node_type is NodeType.DNS
    assert topology.nodes["aws_lb.frontend"].node_type is NodeType.LOAD_BALANCER
    assert topology.nodes["aws_lb.frontend"].provider == "aws.west"
    assert topology.nodes["aws_iam_role.app"].node_type is NodeType.IDENTITY
    assert topology.nodes["aws_vpc.main"].node_type is NodeType.NETWORK
    assert topology.nodes["aws_lb.frontend"].metadata["terraform_type"] == "aws_lb"
    assert topology.nodes["aws_lb.frontend"].metadata["source"] == "main.tf"


def test_parse_explicit_depends_on_and_implicit_references() -> None:
    assert edge_set(TERRAFORM_EXAMPLE) == {
        ("aws_security_group.frontend", "aws_vpc.main", Relationship.DEPENDS_ON),
        ("aws_lb.frontend", "aws_iam_role.app", Relationship.DEPENDS_ON),
        (
            "aws_lb.frontend",
            "aws_security_group.frontend",
            Relationship.DEPENDS_ON,
        ),
        (
            "aws_route53_record.frontend",
            "aws_route53_zone.primary",
            Relationship.DEPENDS_ON,
        ),
        (
            "aws_route53_record.frontend",
            "aws_lb.frontend",
            Relationship.DEPENDS_ON,
        ),
    }


def test_parse_common_vpc_and_eks_resources() -> None:
    topology = parse_terraform_text(
        """
resource "aws_vpc" "main" {}
resource "aws_subnet" "public" {
  vpc_id = aws_vpc.main.id
}
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
}
resource "aws_route" "internet" {
  route_table_id = aws_route_table.public.id
}
resource "aws_route_table_association" "public" {
  subnet_id = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}
resource "aws_network_acl" "main" {
  vpc_id = aws_vpc.main.id
}
resource "aws_network_acl_rule" "ingress" {
  network_acl_id = aws_network_acl.main.id
}
resource "aws_iam_role" "cluster" {}
resource "aws_iam_role_policy_attachment" "cluster" {
  role = aws_iam_role.cluster.name
}
resource "aws_eks_cluster" "main" {
  role_arn = aws_iam_role.cluster.arn
}
resource "aws_eks_access_entry" "admin" {
  cluster_name = aws_eks_cluster.main.name
  principal_arn = aws_iam_role.cluster.arn
}
resource "aws_cloudwatch_log_group" "cluster" {}
""",
        source="main.tf",
    )

    assert topology.nodes["aws_route.internet"].node_type is NodeType.NETWORK
    assert topology.nodes["aws_route_table.public"].node_type is NodeType.NETWORK
    assert topology.nodes["aws_network_acl_rule.ingress"].node_type is NodeType.NETWORK
    assert (
        topology.nodes["aws_iam_role_policy_attachment.cluster"].node_type
        is NodeType.IDENTITY
    )
    assert topology.nodes["aws_eks_access_entry.admin"].node_type is NodeType.IDENTITY
    assert (
        topology.nodes["aws_cloudwatch_log_group.cluster"].node_type
        is NodeType.EXTERNAL
    )
    assert (
        "aws_route_table_association.public",
        "aws_route_table.public",
        Relationship.DEPENDS_ON,
    ) in edge_set_from_topology(topology)


def test_implicit_references_to_missing_supported_resources_are_ignored() -> None:
    topology = parse_terraform_text(
        """
resource "aws_instance" "web" {
  subnet_id = aws_subnet.external.id
  vpc_security_group_ids = [aws_security_group.external.id]
}
"""
    )

    assert set(topology.nodes) == {"aws_instance.web"}
    assert topology.edges == []


def test_shared_cloudwatch_log_group_is_monitoring_risk() -> None:
    topology = parse_terraform_text(
        """
resource "aws_cloudwatch_log_group" "shared" {}
resource "aws_lambda_function" "api" {
  environment {
    variables = {
      LOG_GROUP = aws_cloudwatch_log_group.shared.name
    }
  }
}
resource "aws_ecs_service" "worker" {
  depends_on = [aws_cloudwatch_log_group.shared]
}
"""
    )

    report = RiskAnalyzer().analyze(topology)
    finding = next(
        finding
        for finding in report.findings
        if finding.category is RiskCategory.MONITORING
    )

    assert finding.risk_level is RiskLevel.HIGH
    assert finding.blast_radius == EXPECTED_MONITORING_BLAST_RADIUS


def test_parse_multiple_tf_files_with_cross_file_references(tmp_path: Path) -> None:
    providers = tmp_path / "providers.tf"
    dns = tmp_path / "dns.tf"
    app = tmp_path / "app.tf"
    providers.write_text(
        'provider "aws" { region = "us-east-1" }\n',
        encoding="utf-8",
    )
    dns.write_text(
        'resource "aws_route53_zone" "primary" { name = "example.com" }\n',
        encoding="utf-8",
    )
    app.write_text(
        """
resource "aws_lb" "frontend" {
  depends_on = [aws_route53_zone.primary]
}
""",
        encoding="utf-8",
    )

    topology = parse_terraform_files((app, providers, dns))

    assert set(topology.nodes) == {"aws_lb.frontend", "aws_route53_zone.primary"}
    assert edge_set_from_topology(topology) == {
        ("aws_lb.frontend", "aws_route53_zone.primary", Relationship.DEPENDS_ON)
    }


def test_parse_directory_reads_only_tf_files(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "aws_iam_role" "app" { name = "app" }\n',
        encoding="utf-8",
    )
    (tmp_path / "notes.txt").write_text(
        'resource "aws_lb" "ignored" {}\n',
        encoding="utf-8",
    )

    topology = parse_terraform_directory(tmp_path)

    assert set(topology.nodes) == {"aws_iam_role.app"}


def test_parse_file_rejects_non_tf_suffix(tmp_path: Path) -> None:
    path = tmp_path / "main.hcl"
    path.write_text('resource "aws_iam_role" "app" {}\n', encoding="utf-8")

    with pytest.raises(TerraformParseError, match=r"\.tf suffix"):
        parse_terraform_file(path)


def test_unsupported_resources_are_ignored_gracefully() -> None:
    payload = """
resource "random_id" "suffix" {
  byte_length = 8
}

resource "aws_s3_bucket" "logs" {
  bucket = "logs-${random_id.suffix.hex}"
}
"""

    topology = parse_terraform_text(payload)

    assert set(topology.nodes) == {"aws_s3_bucket.logs"}
    assert topology.edges == []


def test_documents_with_only_unsupported_resources_return_empty_topology() -> None:
    topology = parse_terraform_text(
        """
resource "random_id" "suffix" {
  byte_length = 8
}
"""
    )

    assert topology.nodes == {}
    assert topology.edges == []


def test_data_sources_variables_and_outputs_are_ignored() -> None:
    topology = parse_terraform_text(
        """
variable "name" {
  type = string
}

data "aws_ami" "ubuntu" {
  most_recent = true
}

resource "aws_instance" "web" {
  ami = data.aws_ami.ubuntu.id
}

output "instance_id" {
  value = aws_instance.web.id
}
"""
    )

    assert set(topology.nodes) == {"aws_instance.web"}
    assert topology.edges == []


def test_duplicate_supported_resource_addresses_are_rejected() -> None:
    payload = """
resource "aws_iam_role" "app" {
  name = "one"
}

resource "aws_iam_role" "app" {
  name = "two"
}
"""

    with pytest.raises(TerraformParseError, match="duplicate Terraform resource"):
        parse_terraform_text(payload)


def test_malformed_hcl_is_rejected_with_source_label() -> None:
    with pytest.raises(TerraformParseError) as error:
        parse_terraform_text(
            'resource "aws_iam_role" "app" { name = ',
            source="broken.tf",
        )

    assert "broken.tf" in str(error.value)
    assert "malformed Terraform HCL" in str(error.value)


def test_depends_on_must_be_a_list() -> None:
    payload = """
resource "aws_iam_role" "app" {
  name = "app"
}

resource "aws_lb" "frontend" {
  depends_on = aws_iam_role.app
}
"""

    with pytest.raises(TerraformParseError, match="depends_on must be a list"):
        parse_terraform_text(payload)


def test_missing_supported_dependency_target_is_rejected() -> None:
    payload = """
resource "aws_lb" "frontend" {
  depends_on = [aws_iam_role.missing]
}
"""

    with pytest.raises(TerraformParseError, match="was not found"):
        parse_terraform_text(payload)


def test_references_to_self_are_not_converted_to_edges() -> None:
    payload = """
resource "aws_iam_role" "app" {
  name = aws_iam_role.app.name
}
"""

    topology = parse_terraform_text(payload)

    assert set(topology.nodes) == {"aws_iam_role.app"}
    assert topology.edges == []


def test_custom_resource_mapping_can_be_injected() -> None:
    parser = TerraformParser(
        resource_mappings={
            "custom_service": TerraformResourceMapping(NodeType.SERVICE, "custom")
        }
    )

    topology = parser.parse_text(
        """
resource "custom_service" "api" {
  name = "api"
}
"""
    )

    assert set(topology.nodes) == {"custom_service.api"}
    assert topology.nodes["custom_service.api"].node_type is NodeType.SERVICE
    assert topology.nodes["custom_service.api"].provider == "custom"


def test_missing_directory_and_empty_directory_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(TerraformParseError, match="does not exist"):
        parse_terraform_directory(tmp_path / "missing")

    with pytest.raises(TerraformParseError, match=r"no \.tf files"):
        parse_terraform_directory(tmp_path)


def edge_set_from_topology(topology: Topology) -> set[tuple[str, str, Relationship]]:
    return {(edge.source, edge.target, edge.relationship) for edge in topology.edges}
