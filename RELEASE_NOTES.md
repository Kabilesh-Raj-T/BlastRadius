# ChokePoint 1.0.0 Release Notes

Release date: 2026-07-19

ChokePoint 1.0.0 is the first production-ready release of the infrastructure
dependency analyzer. It provides a typed, layered Python API and a CLI for
ingesting infrastructure descriptions, constructing dependency graphs,
identifying choke points, assessing risk, and exporting reports for engineering
and security workflows.

## Highlights

- Production-ready Python 3.12+ package using `uv`, `pyproject.toml`, and a
  `src/` layout.
- Unified topology model across YAML, Terraform, OpenTofu, Kubernetes,
  CloudFormation, Docker Compose, Pulumi, Terraform plan, and Terraform state
  inputs.
- NetworkX-backed graph analysis for articulation points, bridges, components,
  centrality, cycles, and validation.
- Risk engine for shared DNS, identity, CDN, secrets, monitoring, networking,
  CI/CD, email, and single-service articulation risks.
- CLI commands for `analyze`, `graph`, `report`, `validate`, `export`, and
  `diff`.
- Exports for Markdown, HTML, JSON, terminal, SARIF, OpenAPI, CSV, Mermaid,
  Graphviz DOT/SVG/PNG, and interactive HTML.

## Upgrade Notes

This is the first stable release. Public APIs are expected to remain backward
compatible within the 1.x series unless a security fix requires otherwise.

## Verification

The 1.0.0 release candidate passed:

```text
uv run black src tests
uv run ruff check src tests
uv run mypy
uv run pytest
uv build
```

Coverage is enforced at 95% or higher.
