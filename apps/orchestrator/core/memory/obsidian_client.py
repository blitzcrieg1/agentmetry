"""Obsidian vault client — reads skill configs and writes memory closeout notes."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


_WRITE_ALLOWED_PREFIXES = (
    "20-Active-Loops/",
    "30-Archive/",
    ".system/run-log.md",
    ".system/Approvals-Digest.md",
)


class ObsidianClient:
    def __init__(self, vault_path: str | Path):
        self.vault_path = Path(vault_path)
        self.skill_path = self.vault_path / ".system" / "skill-definitions"
        self.archive_path = self.vault_path / "30-Archive"
        self.active_path = self.vault_path / "20-Active-Loops"
        self.knowledge_path = self.vault_path / "10-Knowledge"

        for p in (self.archive_path, self.active_path, self.skill_path):
            p.mkdir(parents=True, exist_ok=True)

    def _assert_writable(self, target: Path) -> None:
        """Reject writes outside whitelisted vault directories."""
        resolved = target.resolve()
        vault_root = self.vault_path.resolve()
        if resolved != vault_root and vault_root not in resolved.parents:
            raise PermissionError(f"Write blocked — path escapes vault: {target}")

        rel = resolved.relative_to(vault_root).as_posix()
        if any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in _WRITE_ALLOWED_PREFIXES):
            return
        raise PermissionError(f"Write blocked — path not whitelisted: {rel}")

    def _write_text(self, target: Path, content: str) -> Path:
        self._assert_writable(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def write_system_note(self, relative_name: str, content: str) -> Path:
        """Write a note under .system/ (whitelisted filenames only)."""
        rel = relative_name.replace("\\", "/").lstrip("/")
        if not rel.startswith(".system/"):
            rel = f".system/{rel}"
        target = self.vault_path / rel
        return self._write_text(target, content)

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

    def _resolve_safe_path(self, relative_path: str) -> Path | None:
        """Resolve a vault-relative path, rejecting traversal outside the vault."""
        rel = Path(relative_path)
        if rel.is_absolute() or ".." in rel.parts:
            return None
        resolved = (self.vault_path / rel).resolve()
        vault_root = self.vault_path.resolve()
        if resolved != vault_root and vault_root not in resolved.parents:
            return None
        return resolved

    def read_note(self, relative_path: str) -> str | None:
        """Read a markdown note by vault-relative path."""
        file = self._resolve_safe_path(relative_path)
        if file is None or not file.exists() or not file.is_file():
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

    def list_vault_entries(self) -> list[dict[str, Any]]:
        """Return folders and markdown files for the Memory Navigator."""
        entries: list[dict[str, Any]] = []
        skip = {".system", ".git"}

        for item in sorted(self.vault_path.iterdir()):
            if item.name in skip or item.name.startswith("."):
                continue
            if item.is_dir():
                entries.append({
                    "type": "folder",
                    "path": item.name,
                    "name": item.name,
                })
                for md in sorted(item.rglob("*.md")):
                    rel = md.relative_to(self.vault_path).as_posix()
                    entries.append({
                        "type": "file",
                        "path": rel,
                        "name": md.name,
                        "folder": md.parent.as_posix(),
                    })
        return entries

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
        thread_id: str = "",
        status: str = "success",
        confidence_score: float = 0.0,
        context_sources: list[str] | None = None,
        key_decisions: list[str] | None = None,
        next_steps: list[str] | None = None,
    ) -> Path:
        """Write a structured memory closeout note to 30-Archive/."""
        timestamp = datetime.now(timezone.utc)
        suffix = f"-{thread_id[:8]}" if thread_id else ""
        filename = f"{timestamp.strftime('%Y-%m-%d-%H%M%S')}-{skill_name}{suffix}.md"

        frontmatter: dict[str, Any] = {
            "type": "agent-log",
            "skill": skill_name,
            "status": status,
            "confidence_score": confidence_score,
            "created": timestamp.isoformat(),
            **(metadata or {}),
        }
        if thread_id:
            frontmatter["thread_id"] = thread_id

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

{steps_section}
"""

        yaml_block = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
        content = f"---\n{yaml_block}---\n\n{body}"

        # The archive is append-only: never overwrite an existing closeout note.
        target_file = self.archive_path / filename
        counter = 2
        while target_file.exists():
            target_file = self.archive_path / f"{filename[:-3]}-{counter}.md"
            counter += 1
        return self._write_text(target_file, content)

    def write_active_loop(
        self,
        thread_id: str,
        skill_name: str,
        user_input: str,
        nodes: list[str] | None = None,
    ) -> Path:
        """Write a running task note to 20-Active-Loops/."""
        timestamp = datetime.now(timezone.utc)
        filename = f"{timestamp.strftime('%Y-%m-%d-%H%M')}-{skill_name}-{thread_id[:8]}.md"

        frontmatter: dict[str, Any] = {
            "type": "active-loop",
            "skill": skill_name,
            "thread_id": thread_id,
            "status": "running",
            "created": timestamp.isoformat(),
        }

        pipeline_nodes = nodes or []
        pipeline_lines = "\n".join(f"- [ ] {n.replace('_', ' ').title()}" for n in pipeline_nodes)
        pipeline_section = f"## Pipeline\n{pipeline_lines}" if pipeline_lines else ""

        body = f"""# Active Task

**Status:** Running  
**Thread:** `{thread_id}`

## User Input
{user_input}

{pipeline_section}
"""

        yaml_block = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
        content = f"---\n{yaml_block}---\n\n{body}"

        target_file = self.active_path / filename
        return self._write_text(target_file, content)

    def resolve_active_loop(
        self,
        path: Path | str,
        status: str,
        note: str = "",
    ) -> None:
        """Update an active-loop note when a thread completes or terminates."""
        file = Path(path)
        if not file.is_absolute():
            resolved = self._resolve_safe_path(str(file))
            if resolved is None:
                return
            file = resolved
        if not file.exists():
            return

        content = file.read_text(encoding="utf-8")
        meta, body = self.parse_frontmatter(content)
        meta["status"] = status
        meta["resolved"] = datetime.now(timezone.utc).isoformat()

        if note:
            body = body.rstrip() + f"\n\n## Resolution\n{note}\n"

        yaml_block = yaml.dump(meta, default_flow_style=False, allow_unicode=True)
        self._write_text(file, f"---\n{yaml_block}---\n\n{body}")

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
        return self._write_text(target_file, content)
