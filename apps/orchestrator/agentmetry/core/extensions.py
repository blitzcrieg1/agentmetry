"""Optional extension loader for enterprise add-ons.

Third-party packages register via setuptools entry points in the group
``agentmetry.extensions``::

    [project.entry-points."agentmetry.extensions"]
    enterprise = "agentmetry_enterprise.register:register"

The orchestrator discovers installed extensions at startup and calls
``register(app, settings=...)``. When no enterprise package is installed,
this module is a no-op and the OSS quickstart is unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from importlib.metadata import entry_points, version
from typing import Any, Protocol, runtime_checkable

from fastapi import FastAPI

logger = logging.getLogger(__name__)

EXTENSION_GROUP = "agentmetry.extensions"


@runtime_checkable
class AgentmetryExtension(Protocol):
    """Contract for ``agentmetry.extensions`` entry points."""

    def register(self, app: FastAPI, *, settings: Any) -> None: ...


@dataclass
class ExtensionInfo:
    name: str
    value: str
    distribution: str | None = None


@dataclass
class ExtensionRegistry:
    loaded: list[ExtensionInfo] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "count": len(self.loaded),
            "extensions": [
                {
                    "name": item.name,
                    "entry": item.value,
                    "distribution": item.distribution,
                }
                for item in self.loaded
            ],
        }


_registry = ExtensionRegistry()


def get_extension_registry() -> ExtensionRegistry:
    return _registry


def _iter_extension_entry_points():
    try:
        return entry_points(group=EXTENSION_GROUP)
    except TypeError:
        return entry_points().select(group=EXTENSION_GROUP)


def _distribution_for_module(module_name: str) -> str | None:
    root = module_name.split(".", 1)[0]
    try:
        return version(root)
    except Exception:
        return None


def load_extensions(app: FastAPI, *, settings: Any) -> ExtensionRegistry:
    """Discover and invoke all ``agentmetry.extensions`` entry points."""
    _registry.loaded.clear()

    for ep in sorted(_iter_extension_entry_points(), key=lambda e: e.name):
        try:
            target = ep.load()
            if not callable(target):
                raise TypeError(f"entry point {ep.value!r} is not callable")
            target(app, settings=settings)
            module = ep.module or ep.value.split(":", 1)[0]
            _registry.loaded.append(
                ExtensionInfo(
                    name=ep.name,
                    value=ep.value,
                    distribution=_distribution_for_module(module),
                )
            )
            logger.info("Loaded Agentmetry extension %r (%s)", ep.name, ep.value)
        except Exception:
            logger.exception("Failed to load Agentmetry extension %r (%s)", ep.name, ep.value)

    if not _registry.loaded:
        logger.debug("No Agentmetry extensions installed (group=%s)", EXTENSION_GROUP)

    return _registry
