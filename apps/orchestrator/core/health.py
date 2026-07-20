"""Service health for Agentmetry SIEM."""

from __future__ import annotations

from typing import Any

from core.config import settings
from core.extensions import get_extension_registry
from pathlib import Path


async def get_system_health() -> dict[str, Any]:
    """Return health of the SIEM components."""
    path = Path(settings.audit_export_path)
    extensions = get_extension_registry().summary()

    return {
        "status": "up",
        "mode": "siem",
        "audit_export": {
            "enabled": settings.audit_export_enabled,
            "path": str(path),
            "accessible": path.parent.exists() if settings.audit_export_enabled else None,
        },
        "extensions": extensions,
    }
