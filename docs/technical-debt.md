# Technical Debt Report

This report summarizes the release-maintenance review for code quality,
duplication, coupling, readability, and packaging hygiene.

## Fixed

- Consolidated duplicated text-formatting helpers into
  `chokepoint.utils.text`.
- Reused shared helpers for Mermaid node IDs, Mermaid label escaping, Markdown
  table escaping, and human-readable list joining.
- Removed duplicate private helper functions from report generation and export
  modules.
- Replaced repeated SVG layout magic numbers with named constants.
- Split SVG export rendering into focused helpers for canvas sizing, node
  positions, SVG definitions, edge rendering, and node rendering.
- Made utility exports explicit through `chokepoint.utils`.

## Current Status

- Formatting passes with Black.
- Linting passes with Ruff.
- Type checking passes with mypy strict settings.
- Unit and integration tests pass.
- Package build succeeds.

## Remaining Debt

- `chokepoint.report.generator` is still the largest module and contains several
  long rendering functions. It is cohesive, but future report formats should
  avoid adding more responsibilities to this module.
- `chokepoint.parser.terraform_parser` remains large because Terraform
  normalization, reference extraction, and topology construction are colocated.
  Further decomposition would be useful only if Terraform coverage expands.
- `chokepoint.parser.yaml_parser` has several schema-normalization helpers that
  are intentionally explicit. Keep parser behavior stable before extracting
  more abstractions.
- CLI command functions are readable but centrally housed in one module. If the
  command surface grows, split commands by concern.

## Verification

```text
uv run black --check src tests scripts
uv run ruff check src tests scripts
uv run mypy
uv run python -m pytest -q
uv build
```

All checks passed after the maintenance pass.
