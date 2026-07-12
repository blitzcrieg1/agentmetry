"""POST /api/v1/ingress — universal webhook catch-all for Make/Zapier."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from core.auth import require_api_key
from core.execution.context import obsidian, skill_registry
from core.execution.service import run_skill
from core.ingress.webhook import payload_to_markdown

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingress", tags=["ingress"])


@router.post("", dependencies=[Depends(require_api_key)])
async def webhook_ingress(
    request: Request,
    x_target_skill: str = Header(..., alias="X-Target-Skill"),
    x_source_name: str = Header("webhook", alias="X-Source-Name"),
) -> dict[str, Any]:
    """Accept JSON from automation platforms, drop a vault note, run a skill."""
    skill_name = x_target_skill.strip()
    source = (x_source_name or "webhook").strip() or "webhook"

    if not skill_name:
        raise HTTPException(status_code=400, detail="X-Target-Skill header is required")

    if not obsidian.read_skill_config(skill_name):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found in vault")

    if skill_name not in skill_registry.list_registered():
        raise HTTPException(
            status_code=400,
            detail=f"No graph registered for skill '{skill_name}'",
        )

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")

    markdown = payload_to_markdown(payload, source=source, target_skill=skill_name)
    note_path = obsidian.write_ingress_note(source, markdown)
    vault_rel = note_path.relative_to(obsidian.vault_path).as_posix()

    session_id = f"autonomous-{source.replace(' ', '-').lower()}"
    logger.info("Ingress %s → %s at %s", source, skill_name, vault_rel)

    result = await run_skill(
        skill_name,
        vault_rel,
        session_id,
        triggered_by="ingress",
        trigger_file_path=vault_rel,
    )

    return {
        "status": result.get("status", "unknown"),
        "skill": skill_name,
        "source": source,
        "vault_path": vault_rel,
        "session_id": session_id,
        "thread_id": result.get("thread_id"),
        **{k: result[k] for k in ("confidence_score", "archive_path", "error") if k in result},
    }
