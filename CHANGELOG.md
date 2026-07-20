# Changelog

All notable changes to ChokePoint are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses semantic versioning.

## [Unreleased]

No unreleased changes.

## [1.0.0] - 2026-07-19

Portfolio milestone focused on the core infrastructure graph model, CLI, and
single-point-of-failure analysis.

### Added

- Core `Topology`, `Node`, `Edge`, `NodeType`, and `Relationship` models.
- YAML topology parsing with schema validation and helpful errors.
- Basic Terraform HCL ingestion with provider/resource mapping.
- Basic Docker Compose ingestion for services, support resources, and
  `depends_on` relationships.
- NetworkX graph builder and analyzer for articulation points, bridges,
  connected components, centrality, cycles, and graph validation.
- Risk analysis engine with structured risk reports, blast radius, dependency
  chains, and human-readable explanations.
- Markdown, JSON, terminal, CSV, and Mermaid outputs.
- SVG export for dependency graph previews.
- Topology diffing and Click/Rich CLI.
- Confidence levels and confidence reasons on risk findings and generated
  single-point-of-failure reports.
- Repository scanner and `chokepoint scan` command for best-effort analysis of
  arbitrary repositories.
- Terraform mappings for common AWS VPC route, network ACL, security group rule,
  IAM attachment, EKS access, compute, and CloudWatch log group resources.
- GitHub Actions CI for formatting, linting, type checking, tests, coverage,
  and package builds.
- Project maintenance files, including issue templates, pull request template,
  code of conduct, security policy, and support policy.

### Fixed

- Docker Compose parsing resolves simple variable defaults in `depends_on` and
  ignores local bind mounts as storage dependencies.
- Terraform parsing ignores missing implicit references while still rejecting
  missing explicit `depends_on` targets.

### Quality

- Test suite enforces at least 95% coverage.
- Strict mypy checking, Ruff linting, Black formatting, and pre-commit hooks are
  configured.
- Release metadata, documentation, and smoke-install checks are aligned for a
  public 1.0.0 release candidate.
