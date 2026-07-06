from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.memory.obsidian_client import ObsidianClient
from core.config import settings

router = APIRouter(prefix="/vault", tags=["vault"])
obsidian = ObsidianClient(settings.vault_path)


@router.get("/tree")
async def vault_tree():
    """Return vault folder/file structure for the Memory Navigator."""
    return {"entries": obsidian.list_vault_entries()}


@router.get("/active-loops")
async def vault_active_loops():
    """Live runs in 20-Active-Loops/ for dashboard constellation."""
    return {"loops": obsidian.list_active_loops()}


@router.get("/notes/{note_path:path}")
async def read_vault_note(note_path: str):
    content = obsidian.read_note(note_path)
    if content is None:
        raise HTTPException(status_code=404, detail="Note not found")

    meta, body = obsidian.parse_frontmatter(content)
    return {
        "path": note_path,
        "meta": meta,
        "body": body,
        "preview": body[:500] + ("..." if len(body) > 500 else ""),
    }
