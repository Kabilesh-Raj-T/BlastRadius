# Terraform Parser

ChokePoint ingests Terraform HCL through `python-hcl2` and converts supported
`resource` blocks into `Topology` nodes. This parser does not perform graph
analysis.

## API

```python
from chokepoint.parser import parse_terraform_directory

topology = parse_terraform_directory("infra")
```

Available entry points:

- `parse_terraform_text(payload, source="<string>")`
- `parse_terraform_file(path)`
- `parse_terraform_files(paths)`
- `parse_terraform_directory(path)`
- `TerraformParser(resource_mappings=...)`
- `OpenTofuParser(...)` for OpenTofu-compatible HCL
- `TerraformPlanParser().parse_text(...)` for plan JSON
- `TerraformStateParser().parse_text(...)` for state JSON

## Resource Mapping

Supported Terraform resource types are listed in
`TERRAFORM_RESOURCE_MAPPINGS`. Examples:

- `aws_route53_zone` maps to `NodeType.DNS`
- `aws_lb` maps to `NodeType.LOAD_BALANCER`
- `aws_iam_role` maps to `NodeType.IDENTITY`

Unsupported resources are ignored. References to unsupported resources are also
ignored so partially supported Terraform projects can still produce a useful
topology.

## Dependencies

The parser extracts:

- Explicit `depends_on` resource references
- Implicit references in resource attributes, nested blocks, maps, and lists
- Provider addresses from provider blocks and resource `provider` attributes

Edges use `Relationship.DEPENDS_ON`. If a supported resource references another
supported resource type that is not present in the parsed files, ingestion fails
with a `TerraformParseError`.
