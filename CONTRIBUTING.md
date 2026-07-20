# Contributing

Thank you for contributing to ChokePoint. This project values focused changes,
clear boundaries, typed Python, and tests that describe the expected behavior.

## Local Setup

```bash
uv sync
uv run pre-commit install
```

## Quality Checks

Run these checks before opening a pull request:

```bash
uv sync
uv run black --check src tests
uv run ruff check src tests
uv run mypy
uv run pytest -q
```

If test collection fails with missing imports, verify that the command is being
run through uv from the repository root. Running a globally installed `pytest`
without first installing the project dependencies is not a supported check.

Plain commands such as `pytest -q` or `chokepoint analyze ...` are fine after
activating the project virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
pytest -q
chokepoint analyze examples/topology-basic.yaml
```

## Code Style

- Use typed Python for public and internal interfaces.
- Write Google-style docstrings for public modules, classes, and functions.
- Keep modules aligned with the architecture boundaries in
  [Architecture.md](Architecture.md).
- Prefer dependency injection at application boundaries and integration points.
- Keep pull requests small enough to review carefully.

## Pull Requests

Every pull request should include:

- A concise explanation of the change
- Tests for new or changed behavior
- Notes about architectural tradeoffs when boundaries are affected
