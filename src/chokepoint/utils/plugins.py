"""Plugin interfaces for ChokePoint extensions."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from chokepoint.models import Topology


class ChokePointPlugin(Protocol):
    """Protocol implemented by topology extension plugins."""

    name: str

    def transform(self, topology: Topology) -> Topology:
        """Transform or enrich a topology."""
        ...


class PluginRegistry:
    """Apply registered plugins in deterministic order."""

    def __init__(self, plugins: Iterable[ChokePointPlugin] = ()) -> None:
        """Create a plugin registry.

        Args:
            plugins: Initial plugins to register.
        """
        self._plugins: dict[str, ChokePointPlugin] = {}
        for plugin in plugins:
            self.register(plugin)

    def register(self, plugin: ChokePointPlugin) -> None:
        """Register a plugin by name."""
        if not plugin.name.strip():
            raise ValueError("plugin name must be non-empty")
        if plugin.name in self._plugins:
            raise ValueError(f"plugin {plugin.name!r} is already registered")
        self._plugins[plugin.name] = plugin

    def names(self) -> tuple[str, ...]:
        """Return registered plugin names."""
        return tuple(sorted(self._plugins))

    def apply(self, topology: Topology) -> Topology:
        """Apply every registered plugin to a topology."""
        current = Topology.model_validate(topology.model_dump())
        for name in self.names():
            current = self._plugins[name].transform(current)
            current = Topology.model_validate(current.model_dump())
        return current
