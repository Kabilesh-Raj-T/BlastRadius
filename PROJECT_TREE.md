# Project Tree

```text
.
|-- .github/
|   |-- ISSUE_TEMPLATE/
|   |   |-- bug_report.md
|   |   |-- config.yml
|   |   `-- feature_request.md
|   |-- pull_request_template.md
|   `-- workflows/
|       |-- ci.yml
|       `-- release.yml
|-- .gitignore
|-- .pre-commit-config.yaml
|-- Architecture.md
|-- BENCHMARKS.md
|-- CHANGELOG.md
|-- CODE_OF_CONDUCT.md
|-- CONTRIBUTING.md
|-- LICENSE
|-- PROJECT_TREE.md
|-- README.md
|-- RELEASE_NOTES.md
|-- SECURITY.md
|-- SUPPORT.md
|-- docs/
|   |-- assets/
|   |   `-- readme-demo.svg
|   |-- README.md
|   |-- docker-compose-parser.md
|   |-- exports.md
|   |-- graph-engine.md
|   |-- release-candidate-report.md
|   |-- repository-scanner.md
|   |-- risk-engine.md
|   |-- technical-debt.md
|   |-- terraform-parser.md
|   `-- yaml-parser.md
|-- examples/
|   |-- README.md
|   |-- basic.yaml
|   |-- topology-basic.yaml
|   |-- topology-cycle.yaml
|   |-- topology-disconnected.yaml
|   |-- topology-expanded.yaml
|   |-- topology-microservices.yaml
|   `-- topology-multi-cloud.yaml
|-- pyproject.toml
|-- src/
|   `-- chokepoint/
|       |-- __init__.py
|       |-- __main__.py
|       |-- cli/
|       |   |-- __init__.py
|       |   `-- app.py
|       |-- graph/
|       |   |-- __init__.py
|       |   |-- diff.py
|       |   `-- engine.py
|       |-- models/
|       |   |-- __init__.py
|       |   `-- topology.py
|       |-- parser/
|       |   |-- __init__.py
|       |   |-- docker_compose_parser.py
|       |   |-- repository_scanner.py
|       |   |-- terraform_parser.py
|       |   `-- yaml_parser.py
|       |-- py.typed
|       |-- report/
|       |   |-- __init__.py
|       |   |-- export.py
|       |   |-- generator.py
|       |   `-- risk.py
|       |-- utils/
|       |   |-- __init__.py
|       |   `-- text.py
|       `-- visualization/
|           `-- __init__.py
|-- tests/
|   |-- test_cli.py
|   |-- test_docker_compose_parser.py
|   |-- test_examples.py
|   |-- test_graph_engine.py
|   |-- test_imports.py
|   |-- test_report_generator.py
|   |-- test_repository_scanner.py
|   |-- test_risk_engine.py
|   |-- test_terraform_parser.py
|   |-- test_topology_models.py
|   `-- test_yaml_parser.py
`-- uv.lock
```
