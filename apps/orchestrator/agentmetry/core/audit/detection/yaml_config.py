"""Load detection thresholds and YAML count rules from agentmetry/policies/detection/manifest.yaml."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_ORCH_ROOT = Path(__file__).resolve().parents[4]
# The packaged manifest lives inside the package
# (`agentmetry/policies/detection/manifest.yaml`), not at the repo root —
# `config._policy` says so, and the old path here pointed at a file that
# does not exist. It only ever served as the fallback when settings could
# not be read, so nothing loaded through it, but `manifest_is_default`
# compares against it and needs the real anchor.
_DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[3] / "policies" / "detection" / "manifest.yaml"
)

_DEFAULT_THRESHOLDS: dict[str, int] = {
    "discovery_burst": 3,
    "delete_burst": 5,
    "subagent_burst": 5,
    "session_tool_burst": 40,
    "host_subagent_burst": 8,
    # Burst rules need a clock as well as a count. Without one, 40 tool calls is
    # an ordinary long coding session and 8 subagent starts is two quiet weeks —
    # both fired as "autonomous campaign". Set a window to 0 to disable the time
    # bound and match on the raw count (the pre-2026-07-24 behaviour).
    "subagent_burst_window_minutes": 15,
    "delete_burst_window_minutes": 10,
    "session_tool_burst_window_minutes": 10,
    "host_subagent_burst_window_minutes": 60,
    # Two-step rules ("credential read, then egress") pair only when the
    # second step follows within this many minutes. 0 pairs across the
    # whole session, which is how they worked before 2026-11.
    "sequence_window_minutes": 240,
}

_cache: dict[str, Any] | None = None


def _manifest_path() -> Path:
    try:
        from agentmetry.core.config import settings

        custom = settings.detection_rules_path
        if custom:
            return Path(custom)
    except Exception as exc:
        # Falling back to the packaged manifest is correct, but doing it in
        # silence means an operator who configured their own rules runs the
        # default ones and is never told.
        logger.debug("could not read detection_rules_path from settings: %s", exc)
    return _DEFAULT_MANIFEST


def manifest_is_default() -> bool:
    """True when the active manifest is the packaged one.

    A custom manifest (`settings.detection_rules_path` pointing elsewhere)
    replaces the whole file, so any rule id it defines is the operator's
    own — even one that collides with a shipped id. Code that special-cases
    a shipped rule (for example the engine deduplicating a denial burst)
    must check this first, so it never drops a finding that belongs to an
    operator-authored rule.
    """
    try:
        return _manifest_path().resolve() == _DEFAULT_MANIFEST.resolve()
    except Exception:
        return True


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
