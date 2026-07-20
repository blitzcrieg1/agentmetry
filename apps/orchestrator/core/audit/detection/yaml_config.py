"""Load detection thresholds and YAML count rules from policies/detection/manifest.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_ORCH_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_MANIFEST = _ORCH_ROOT.parent.parent / "policies" / "detection" / "manifest.yaml"

_DEFAULT_THRESHOLDS: dict[str, int] = {
    "discovery_burst": 3,
    "delete_burst": 5,
    "subagent_burst": 5,
    "session_tool_burst": 40,
    "host_subagent_burst": 8,
}

_cache: dict[str, Any] | None = None


def _manifest_path() -> Path:
    try:
        from core.config import settings

        custom = settings.detection_rules_path
        if custom:
            return Path(custom)
    except Exception:
        pass
    return _DEFAULT_MANIFEST


def load_manifest(*, reload: bool = False) -> dict[str, Any]:
    global _cache
    if _cache is not None and not reload:
        return _cache

    path = _manifest_path()
    if not path.is_file():
        _cache = {"thresholds": dict(_DEFAULT_THRESHOLDS), "count_rules": []}
        return _cache

    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    thresholds = dict(_DEFAULT_THRESHOLDS)
    raw_thresholds = data.get("thresholds")
    if isinstance(raw_thresholds, dict):
        for key, val in raw_thresholds.items():
            try:
                thresholds[str(key)] = int(val)
            except (TypeError, ValueError):
                continue

    count_rules: list[dict[str, Any]] = []
    for raw in data.get("count_rules") or []:
        if isinstance(raw, dict) and raw.get("id"):
            count_rules.append(raw)

    _cache = {"thresholds": thresholds, "count_rules": count_rules}
    return _cache


def clear_manifest_cache() -> None:
    """Test helper."""
    global _cache
    _cache = None


def threshold(name: str, default: int | None = None) -> int:
    manifest = load_manifest()
    thresholds = manifest.get("thresholds") or {}
    if name in thresholds:
        return int(thresholds[name])
    if default is not None:
        return default
    return int(_DEFAULT_THRESHOLDS.get(name, 1))


def count_rules() -> list[dict[str, Any]]:
    return list(load_manifest().get("count_rules") or [])
