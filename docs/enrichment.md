# Enrichment

Terraform cannot expose every infrastructure dependency. ChokePoint supports
YAML overlays so operators can add external services, manual dependencies, and
known platform relationships that are absent from Terraform state.

## API

```python
from chokepoint.parser import enrich_terraform_with_yaml_overlay

topology = enrich_terraform_with_yaml_overlay(
    terraform_paths=["infra/main.tf", "infra/dns.tf"],
    overlay_path="topology-overlay.yaml",
)
```

For already parsed inputs, use `merge_topologies(terraform_topology,
overlay_topology)`.

## Merge Rules

- Providers are normalized before merge. For example, `aws.west` becomes `aws`,
  `azurerm` becomes `azure`, and `google-beta` becomes `gcp`.
- Identical duplicate node ids are merged once.
- Duplicate edges with the same source, target, and relationship are kept once.
- Duplicate node ids with conflicting names, providers, or node types raise
  `TopologyMergeError`.
- Metadata is merged without overwriting conflicting keys. Conflicting overlay
  metadata is retained under an `overlay_` prefix.

## Overlay Example

```yaml
external:
  - cloudflare
  - okta
  - stripe
  - github
```

Simple `external` entries use the entry name as both the node id and normalized
provider.
