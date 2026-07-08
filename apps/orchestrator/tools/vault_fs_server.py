"""vault_fs — read-only MCP driver jailed to the Obsidian vault.

Local-first by construction: runs on the orchestrator's own Python, no Node or
network needed. Mounted via vault/.system/drivers.json:

    { "name": "vault_fs", "command": "<venv python>",
      "args": ["<this file>", "<vault path>"] }
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

VAULT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd() / "vault"

server = FastMCP("vault_fs")


def _safe(rel: str) -> Path:
    path = (VAULT / rel).resolve()
    if path != VAULT and VAULT not in path.parents:
        raise ValueError(f"Path escapes vault: {rel}")
    return path


@server.tool()
def read_note(path: str) -> str:
    """Read a vault-relative markdown note (e.g. '00-Inbox/meeting.md')."""
    target = _safe(path)
    if not target.is_file():
        raise FileNotFoundError(f"No such note: {path}")
    return target.read_text(encoding="utf-8")


@server.tool()
def read_jsonl_tail(path: str, limit: int = 20) -> str:
    """Read the last N JSONL records from a vault file, formatted as markdown."""
    target = _safe(path)
    if not target.is_file():
        return "(no edit log yet — zero operator corrections captured)"
    raw = target.read_text(encoding="utf-8").strip()
    if not raw:
        return "(edit log is empty)"
    cap = max(1, min(int(limit), 50))
    lines = [ln for ln in raw.splitlines() if ln.strip()][-cap:]
    blocks: list[str] = []
    for i, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        tid = str(row.get("thread_id", "?"))
        blocks.append(
            f"### Correction {i}\n"
            f"- **When:** {row.get('ts', '?')}\n"
            f"- **Skill:** {row.get('skill_name', '?')}\n"
            f"- **Thread:** {tid[:8]}…\n\n"
            f"**Original draft:**\n{row.get('original_draft', '')}\n\n"
            f"**Operator-approved version:**\n{row.get('modified_input', '')}"
        )
    if not blocks:
        return "(edit log has no parseable JSON lines)"
    return f"# Last {len(blocks)} operator corrections\n\n" + "\n\n---\n\n".join(blocks)


@server.tool()
def list_notes(folder: str = "") -> list[str]:
    """List markdown files under a vault-relative folder ('' = whole vault)."""
    root = _safe(folder) if folder else VAULT
    return [
        f.relative_to(VAULT).as_posix()
        for f in sorted(root.rglob("*.md"))
        if ".system" not in f.parts
    ][:200]


if __name__ == "__main__":
    server.run()
