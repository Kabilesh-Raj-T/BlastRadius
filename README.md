# ChokePoint

ChokePoint is a production-grade open-source infrastructure dependency analyzer.
It is intended to help teams understand critical dependencies, concentration
risk, and architectural choke points across infrastructure systems.

## Engineering Baseline

The repository is initialized for Python 3.12+ with:

- `uv` for package and environment management
- `pyproject.toml` as the single project configuration surface
- `src/` package layout
- `pytest` for testing
- `ruff`, `black`, and `mypy` for quality gates
- `pre-commit` hooks
- GitHub Actions CI

## Development

Install the development environment:

```bash
uv sync --extra dev
```

Run the checks used by CI:

```bash
uv run black --check src tests
uv run ruff check src tests
uv run mypy
uv run pytest
```

Install local hooks:

```bash
uv run pre-commit install
```

## CLI

Run ChokePoint from a YAML topology file:

```bash
chokepoint analyze topology.yaml
chokepoint graph topology.yaml --json
chokepoint report topology.yaml --markdown
chokepoint validate topology.yaml
chokepoint export topology.yaml --format sarif
chokepoint export topology.yaml --format mermaid
chokepoint diff before.yaml after.yaml --json
```

Use `--verbose` before the command for colored diagnostic logs:

```bash
chokepoint --verbose validate topology.yaml
```

## Architecture

The architecture is documented in [Architecture.md](Architecture.md). The
package is organized around independent layers for parsing, graph construction,
domain models, reporting, visualization, utilities, and the command-line entry
point.

The graph engine algorithms and complexity profile are documented in
[docs/graph-engine.md](docs/graph-engine.md).

The supported YAML topology format is documented in
[docs/yaml-parser.md](docs/yaml-parser.md).

Terraform ingestion is documented in
[docs/terraform-parser.md](docs/terraform-parser.md).

Advanced ingestion supports Kubernetes, CloudFormation, Docker Compose,
Pulumi, OpenTofu, Terraform plan JSON, and Terraform state JSON through the
parser API described in [docs/advanced-ingestion.md](docs/advanced-ingestion.md).

Terraform enrichment with YAML overlays is documented in
[docs/enrichment.md](docs/enrichment.md).

Risk analysis output is documented in [docs/risk-engine.md](docs/risk-engine.md).

Graphviz visualization is documented in [docs/visualization.md](docs/visualization.md).

Report and topology exports are documented in [docs/exports.md](docs/exports.md).
