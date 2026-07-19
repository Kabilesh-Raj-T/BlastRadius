# Changelog

All notable changes to ChokePoint are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses semantic versioning.

## [1.0.0] - 2026-07-19

### Added

- Core `Topology`, `Node`, `Edge`, `NodeType`, and `Relationship` models.
- YAML topology parsing with schema validation and helpful errors.
- Terraform and OpenTofu HCL ingestion with provider/resource mapping.
- Terraform plan JSON and state JSON ingestion.
- Kubernetes, CloudFormation, Docker Compose, and Pulumi ingestion.
- YAML overlay enrichment, provider normalization, duplicate detection, and
  topology merging.
- NetworkX graph builder and analyzer for articulation points, bridges,
  connected components, centrality, cycles, and graph validation.
- Risk analysis engine with structured risk reports, blast radius, dependency
  chains, and human-readable explanations.
- Markdown, HTML, JSON, terminal, SARIF, OpenAPI, CSV, and Mermaid exports.
- Graphviz DOT/SVG/PNG visualization and standalone interactive HTML graphs.
- Topology diffing, risk history, plugin hooks, and Click CLI.
- GitHub Actions CI for formatting, linting, type checking, tests, coverage,
  and package builds.
- Release governance files, including issue templates, pull request template,
  code of conduct, security policy, and support policy.

### Security

- Interactive HTML graph exports use script-safe JSON encoding and DOM text
  rendering for topology values.
- YAML parsing uses safe loaders or a constrained CloudFormation intrinsic-tag
  loader.
- Graphviz rendering invokes the executable without shell interpolation.

### Quality

- Test suite enforces at least 95% coverage.
- Strict mypy checking, Ruff linting, Black formatting, and pre-commit hooks are
  configured.
