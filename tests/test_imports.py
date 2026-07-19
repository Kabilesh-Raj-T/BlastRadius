"""Import tests for the ChokePoint package structure."""

import importlib
from collections.abc import Iterable


def test_package_modules_are_importable() -> None:
    """Verify that each public package boundary can be imported."""
    module_names: Iterable[str] = (
        "chokepoint",
        "chokepoint.cli",
        "chokepoint.parser",
        "chokepoint.graph",
        "chokepoint.models",
        "chokepoint.report",
        "chokepoint.visualization",
        "chokepoint.utils",
    )

    for module_name in module_names:
        assert importlib.import_module(module_name).__name__ == module_name
