"""Obsidian vault client — reads skill configs and writes memory closeout notes."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


class ObsidianClient:
    def __init__(self, vault_path: str | Path):
        self.vault_path = Path(vault_path)
        self.skill_path = self.vault_path / ".system" / "skill-definitions"
        self.archive_path = self.vault_path / "30-Archive"
        self.active_path = self.vault_path / "20-Active-Loops"
        self.knowledge_path = self.vault_path / "10-Knowledge"

        for p in (self.archive_path, self.active_path, self.skill_path):
            p.mkdir(parents=True, exist_ok=True)

    def read_skill_config(self, skill_name: str) -> dict[str, Any] | None:
        """Read a YAML skill definition from .system/skill-definitions/."""
        file = self.skill_path / f"{skill_name}.yaml"
        if not file.exists():
            return None
        with open(file, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def list_skills(self) -> list[dict[str, Any]]:
        """Return all available skill definitions."""
        skills = []
        if not self.skill_path.exists():
            return skills
        for file in self.skill_path.glob("*.yaml"):
            with open(file, encoding="utf-8") as f:
                config = yaml.safe_load(f)
                config["id"] = file.stem
                skills.append(config)
        return skills

    def read_note(self, relative_path: str) -> str | None:
        """Read a markdown note by vault-relative path."""
        file = self.vault_path / relative_path
        if not file.exists():
            return None
        return file.read_text(encoding="utf-8")

    def list_markdown_files(self, subdir: str | None = None) -> list[Path]:
        """Enumerate all .md files in the vault (excluding .system)."""
        root = self.vault_path / subdir if subdir else self.vault_path
        files = []
        for path in root.rglob("*.md"):
            if ".system" not in path.parts:
                files.append(path)
        return files

    def parse_frontmatter(self, content: str) -> tuple[dict[str, Any], str]:
        """Split YAML frontmatter from markdown body."""
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
        if not match:
            return {}, content
        meta = yaml.safe_load(match.group(1)) or {}
        return meta, match.group(2)

    def write_closeout_note(
        self,
        skill_name: str,
        result: str,
        metadata: dict[str, Any] | None = None,
        *,
        status: str = "success",
        confidence_score: float = 0.0,
        context_sources: list[str] | None = None,
        key_decisions: list[str] | None = None,
        next_steps: list[str] | None = None,
    ) -> Path:
        """Write a structured memory closeout note to 30-Archive/."""
        timestamp = datetime.now(timezone.utc)
        filename = f"{timestamp.strftime('%Y-%m-%d')}-{skill_name}-outreach-v1.md"

        frontmatter: dict[str, Any] = {
            "type": "agent-log",
            "skill": skill_name,
            "status": status,
            "confidence_score": confidence_score,
            "created": timestamp.isoformat(),
            **(metadata or {}),
        }

        sources_section = ""
        if context_sources:
            sources_section = "# Context Sources Used\n" + "\n".join(
                f"- [[{s}]]" for s in context_sources
            )

        decisions_section = ""
        if key_decisions:
            decisions_section = "# Key Decisions\n" + "\n".join(
                f"{i}. {d}" for i, d in enumerate(key_decisions, 1)
            )

        steps_section = ""
        if next_steps:
            steps_section = "# Next Steps (Open Loops)\n" + "\n".join(
                f"- [ ] {s}" for s in next_steps
            )

        body = f"""# Executive Summary
{result}

{sources_section}

{decisions_section}

# Generated Artifacts
{result}

{steps_section}
"""

        yaml_block = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
        content = f"---\n{yaml_block}---\n\n{body}"

        target_file = self.archive_path / filename
        target_file.write_text(content, encoding="utf-8")
        return target_file

    def write_crash_report(self, thread_id: str, error: str, skill_name: str) -> Path:
        """Write a crash report when a thread is terminated."""
        timestamp = datetime.now(timezone.utc)
        filename = f"{timestamp.strftime('%Y-%m-%d-%H%M')}-crash-{thread_id[:8]}.md"
        content = f"""---
type: crash-report
skill: {skill_name}
thread_id: {thread_id}
created: {timestamp.isoformat()}
status: terminated
---

# Crash Report

Thread `{thread_id}` was terminated by user or system.

## Error
```
{error}
```
"""
        target_file = self.archive_path / filename
        target_file.write_text(content, encoding="utf-8")
        return target_file
