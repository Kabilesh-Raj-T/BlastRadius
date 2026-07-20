"""Pytest environment checks for ChokePoint."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

import pytest

REQUIRED_PYDANTIC_MAJOR = 2


def pytest_configure(config: pytest.Config) -> None:
    """Fail fast when pytest is run outside the project environment."""
    _prefer_project_environment()
    problems: list[str] = []

    try:
        pydantic = import_module("pydantic")
    except ModuleNotFoundError:
        problems.append("pydantic>=2 is not installed")
    else:
        version = str(getattr(pydantic, "__version__", "0"))
        if _major_version(version) < REQUIRED_PYDANTIC_MAJOR:
            problems.append(f"pydantic>=2 is required, found pydantic {version}")

    try:
        import_module("yaml")
    except ModuleNotFoundError:
        problems.append("PyYAML is not installed")

    if problems:
        details = "\n".join(f"- {problem}" for problem in problems)
        pytest.exit(
            "ChokePoint tests are running outside the project environment.\n"
            f"{details}\n\n"
            "Run the supported test command from the repository root:\n"
            "  uv sync\n"
            "  uv run pytest -q\n\n"
            "Plain `pytest -q` is supported after activating the uv virtualenv.",
            returncode=2,
        )


def _prefer_project_environment() -> None:
    """Prefer dependencies installed by uv when pytest is launched globally."""
    root = Path(__file__).resolve().parents[1]
    python_tag = f"python{sys.version_info.major}.{sys.version_info.minor}"
    candidates = [
        root / ".venv" / "Lib" / "site-packages",
        root / ".venv" / "lib" / python_tag / "site-packages",
    ]
    for site_packages in candidates:
        if site_packages.exists():
            sys.path.insert(0, str(site_packages))
            return


def _major_version(version: str) -> int:
    """Return the major component of a version string."""
    try:
        return int(version.split(".", maxsplit=1)[0])
    except ValueError:
        return 0
