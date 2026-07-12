#!/usr/bin/env python3
"""Fail CI if any shipped skill YAML violates governance invariants."""

from __future__ import annotations

import sys
from fnmatch import fnmatch
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[3]
SKILLS_DIR = _REPO / "vault" / ".system" / "skill-definitions"
REQUIRED = ("name", "graph")
KNOWN_GRAPHS = {
    "pipeline",
}


def lint_file(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"{path.name}: invalid YAML — {exc}"]

    if not isinstance(cfg, dict):
        return [f"{path.name}: root must be a mapping"]

    for field in REQUIRED:
        if field not in cfg:
            errors.append(f"{path.name}: missing required field '{field}'")

    stem = path.stem
    if cfg.get("name") and cfg["name"] != stem:
        errors.append(f"{path.name}: name '{cfg['name']}' must match filename stem '{stem}'")

    graph = cfg.get("graph")
    if graph and graph not in KNOWN_GRAPHS:
        errors.append(f"{path.name}: unknown graph '{graph}' — known: {sorted(KNOWN_GRAPHS)}")

    allow = cfg.get("tools") or []
    node_tools = cfg.get("node_tools") or {}
    if node_tools and not allow:
        errors.append(f"{path.name}: node_tools declared but tools allowlist is empty")

    for step, calls in node_tools.items():
        if not isinstance(calls, list):
            errors.append(f"{path.name}: node_tools.{step} must be a list")
            continue
        for call in calls:
            tool = call.get("tool") if isinstance(call, dict) else None
            if not tool:
                errors.append(f"{path.name}: node_tools.{step} entry missing 'tool'")
                continue
            if not any(fnmatch(tool, pattern) for pattern in allow):
                errors.append(
                    f"{path.name}: node_tools.{step} uses '{tool}' "
                    f"but tools allowlist is {allow}"
                )

    threshold = cfg.get("approval_threshold")
    if threshold is not None and not isinstance(threshold, (int, float)):
        errors.append(f"{path.name}: approval_threshold must be numeric")

    max_cost = cfg.get("max_cost_per_run")
    if max_cost is not None and not isinstance(max_cost, (int, float)):
        errors.append(f"{path.name}: max_cost_per_run must be numeric")

    return errors


def main() -> int:
    if not SKILLS_DIR.is_dir():
        print(f"Skills directory not found: {SKILLS_DIR}", file=sys.stderr)
        return 1

    paths = sorted(SKILLS_DIR.glob("*.yaml"))
    if not paths:
        print("No skill YAML files found", file=sys.stderr)
        return 1

    all_errors: list[str] = []
    for path in paths:
        all_errors.extend(lint_file(path))

    if all_errors:
        print("\n".join(all_errors), file=sys.stderr)
        return 1

    print(f"OK — {len(paths)} skills passed governance lint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
