"""Vault watch trigger evaluation and skill dispatch."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from core.execution.context import obsidian
from core.execution.service import run_skill
from core.scheduler.rules import (
    load_trigger_rules,
    note_matches_rule,
    render_user_input,
)

logger = logging.getLogger(__name__)

_cooldowns: dict[tuple[str, str], float] = {}


async def evaluate_vault_triggers(file_path: Path, vault_path: Path) -> None:
    """Match a changed vault file against trigger rules and dispatch skills."""
    try:
        rel_path = file_path.relative_to(vault_path).as_posix()
    except ValueError:
        return

    if not rel_path.endswith(".md") or rel_path.startswith(".system/"):
        return

    now = time.monotonic()
    for rule in load_trigger_rules(vault_path):
        if not note_matches_rule(rule, rel_path, obsidian):
            continue

        key = (rule.id, rel_path)
        last = _cooldowns.get(key, 0.0)
        if now - last < rule.cooldown_seconds:
            logger.debug("Trigger %s cooldown active for %s", rule.id, rel_path)
            continue

        _cooldowns[key] = now
        user_input = render_user_input(rule, rel_path)
        session_id = f"autonomous-{rule.id}"

        logger.info("Trigger %s firing skill %s for %s", rule.id, rule.skill, rel_path)
        result = await run_skill(
            rule.skill,
            user_input,
            session_id,
            triggered_by="vault_watch",
            trigger_rule_id=rule.id,
        )
        logger.info("Trigger %s result: %s", rule.id, result.get("status"))
