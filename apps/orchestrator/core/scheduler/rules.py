"""Trigger rule loading and matching."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from core.config import settings
from core.memory.obsidian_client import ObsidianClient


@dataclass
class TriggerRule:
    id: str
    type: str  # vault_watch | cron
    skill: str
    enabled: bool
    path_glob: str = ""
    frontmatter_tags: list[str] | None = None
    frontmatter_not_tags: list[str] | None = None
    user_input_template: str = ""
    cron: str = ""
    cooldown_seconds: int = 60

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TriggerRule:
        match = data.get("match") or {}
        frontmatter = match.get("frontmatter", {}) or {}
        tags = frontmatter.get("tags")
        if isinstance(tags, str):
            tags = [tags]
        not_tags = frontmatter.get("not_tags")
        if isinstance(not_tags, str):
            not_tags = [not_tags]
        return cls(
            id=data["id"],
            type=data.get("type", "vault_watch"),
            skill=data["skill"],
            enabled=bool(data.get("enabled", True)),
            path_glob=match.get("path_glob", ""),
            frontmatter_tags=tags,
            frontmatter_not_tags=not_tags,
            user_input_template=data.get("user_input_template", ""),
            cron=data.get("cron", ""),
            cooldown_seconds=int(data.get("cooldown_seconds", 60)),
        )


def load_trigger_rules(vault_path: Path | None = None) -> list[TriggerRule]:
    root = (vault_path or settings.vault_path) / ".system" / "trigger-rules"
    rules: list[TriggerRule] = []
    if not root.exists():
        return rules
    for file in sorted(root.glob("*.yaml")):
        with open(file, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if "id" not in data:
            data["id"] = file.stem
        rules.append(TriggerRule.from_dict(data))
    return [r for r in rules if r.enabled]


def note_matches_rule(rule: TriggerRule, rel_path: str, obsidian: ObsidianClient) -> bool:
    if rule.type != "vault_watch":
        return False
    normalized = rel_path.replace("\\", "/")
    if rule.path_glob and not fnmatch.fnmatch(normalized, rule.path_glob):
        return False
    if not rule.frontmatter_tags and not rule.frontmatter_not_tags:
        return True
    content = obsidian.read_note(normalized)
    if content is None:
        return False  # cannot verify frontmatter constraints — do not fire
    meta, _ = obsidian.parse_frontmatter(content)
    note_tags = meta.get("tags", [])
    if isinstance(note_tags, str):
        note_tags = [note_tags]
    if rule.frontmatter_not_tags and any(tag in note_tags for tag in rule.frontmatter_not_tags):
        return False  # exclusion lets a catch-all rule defer to a specific one
    if not rule.frontmatter_tags:
        return True
    return any(tag in note_tags for tag in rule.frontmatter_tags)


def render_user_input(rule: TriggerRule, rel_path: str) -> str:
    template = rule.user_input_template.strip()
    if not template:
        return f"Process vault note: {rel_path}"
    return template.replace("{{ trigger.file_path }}", rel_path).replace("{{file_path}}", rel_path)
