# Advanced Ingestion

Advanced parsers convert additional infrastructure formats into the same
`Topology` model used by YAML and Terraform ingestion. Parser-specific details
stay in `chokepoint.parser`; graph analysis consumes only `Topology`.

## Supported Inputs

- Kubernetes YAML manifests
- CloudFormation YAML or JSON templates
- Docker Compose YAML
- Pulumi stack export JSON
- OpenTofu HCL through Terraform-compatible parsing
- Terraform plan JSON
- Terraform state JSON

## API

```python
from chokepoint.parser import (
    KubernetesParser,
    CloudFormationParser,
    DockerComposeParser,
    PulumiParser,
    TerraformPlanParser,
    TerraformStateParser,
)

topology = KubernetesParser().parse_file("deployment.yaml")
```

Convenience functions are also exported:

- `parse_kubernetes_text(payload)`
- `parse_cloudformation_text(payload)`
- `parse_docker_compose_text(payload)`
- `parse_pulumi_text(payload)`
- `parse_terraform_plan_text(payload)`
- `parse_terraform_state_text(payload)`

## Dependency Inference

`AutomaticDependencyInferrer` reads common metadata reference fields such as
`references`, `depends_on`, `target`, and `targets`. It only adds edges where
both endpoints already exist in the topology.

Unsupported resources are ignored when they cannot be represented accurately.
Malformed documents raise `AdvancedParseError` with source context when
available.
