"""APScheduler integration for cron triggers and digests."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from core.config import settings
from core.execution.service import run_skill
from core.llm.degraded import llm_degraded
from core.scheduler.approval_digest import write_approval_digest
from core.scheduler.rules import load_trigger_rules

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _run_cron_rule(rule_id: str, skill: str, user_input_template: str) -> None:
    if llm_degraded.active and settings.llm_provider.lower() == "gemini":
        logger.warning("Skipping cron trigger %s — LLM degraded", rule_id)
        return

    user_input = render_user_input_template(user_input_template, skill)
    await run_skill(
        skill,
        user_input,
        f"autonomous-{rule_id}",
        triggered_by="cron",
        trigger_rule_id=rule_id,
    )


def render_user_input_template(template: str, skill: str) -> str:
    text = (template or "").strip()
    if not text:
        return f"Scheduled run for skill {skill}"
    return text


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        write_approval_digest,
        CronTrigger(minute=0),
        id="approval_digest",
        replace_existing=True,
    )

    for rule in load_trigger_rules():
        if rule.type != "cron" or not rule.cron:
            continue
        parts = rule.cron.split()
        if len(parts) != 5:
            logger.warning("Invalid cron for rule %s: %s", rule.id, rule.cron)
            continue
        minute, hour, day, month, dow = parts
        _scheduler.add_job(
            _run_cron_rule,
            CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=dow,
            ),
            args=[rule.id, rule.skill, rule.user_input_template],
            id=f"cron-{rule.id}",
            replace_existing=True,
        )
        logger.info("Registered cron trigger %s (%s)", rule.id, rule.cron)

    _scheduler.start()
    logger.info("Scheduler started")
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")
