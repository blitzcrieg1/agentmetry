"""Channel-agnostic command router.

One grammar on every channel:

    /skill <name> <input...>   run a skill (interactive priority, full IVT gating)
    /approve <thread-prefix>   approve a thread paused at the human gate
    /reject <thread-prefix>    reject + terminate a paused thread
    /pending                   threads waiting for approval
    /status                    run counters and today's Flash budget
    /skills                    registered skills
    /help                      this text
    <free text>                filed to 00-Inbox/ where vault triggers pick it up
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from core.channels.base import ChannelReply, InboundMessage
from core.config import settings
from core.execution import service
from core.execution.context import (
    interrupt_table,
    pending_store,
    pending_threads,
    skill_registry,
    telemetry,
)
from core.execution.service import ApprovalNotFound, ApprovalUnavailable

logger = logging.getLogger(__name__)

_DRAFT_PREVIEW_CHARS = 700

HELP_TEXT = (
    "BLACKBOX commands:\n"
    "/skill <name> <input> — run a skill\n"
    "/approve <id> — approve a pending draft\n"
    "/reject <id> — reject + terminate\n"
    "/pending — what's waiting for you\n"
    "/status — runs + budget\n"
    "/skills — registered skills\n"
    "Anything else is filed to 00-Inbox/ for vault triggers."
)


def session_id_for(msg: InboundMessage) -> str:
    return f"channel-{msg.channel}-{msg.sender_id}"


async def route_inbound(msg: InboundMessage) -> ChannelReply:
    """Normalize one inbound message into a kernel action and describe the outcome."""
    text = msg.text.strip()
    if not text:
        return ChannelReply("Empty message — send /help for commands.")
    if text.startswith("/"):
        return await _route_command(msg, text)
    return _file_to_inbox(msg, text)


async def _route_command(msg: InboundMessage, text: str) -> ChannelReply:
    parts = text.split(maxsplit=2)
    command = parts[0].lower()

    if command in ("/help", "/start"):
        return ChannelReply(HELP_TEXT)
    if command == "/skill":
        if len(parts) < 2:
            return ChannelReply("Usage: /skill <name> <input>")
        return await _run_skill(msg, parts[1], parts[2] if len(parts) > 2 else "")
    if command in ("/approve", "/reject"):
        if len(parts) < 2:
            return ChannelReply(f"Usage: {command} <thread-id-prefix>")
        return await _resolve(parts[1], approved=(command == "/approve"))
    if command == "/pending":
        return _pending_reply()
    if command == "/status":
        return _status_reply()
    if command == "/skills":
        names = sorted(skill_registry.list_registered())
        return ChannelReply("Registered skills:\n" + "\n".join(names) if names else "No skills registered.")
    return ChannelReply(f"Unknown command {command}.\n\n{HELP_TEXT}")


async def _run_skill(msg: InboundMessage, skill_name: str, user_input: str) -> ChannelReply:
    result = await service.run_skill(
        skill_name,
        user_input,
        session_id_for(msg),
        triggered_by=f"channel:{msg.channel}",
    )
    status = result.get("status", "unknown")

    if status == "waiting_for_input":
        thread_id = result["thread_id"]
        short = thread_id[:8]
        draft = _draft_preview(thread_id)
        confidence = result.get("confidence_score")
        lines = [f"{skill_name} paused at the approval gate (thread {short})."]
        if confidence is not None:
            lines.append(f"Confidence: {confidence:.2f}")
        if draft:
            lines.append(f"\n{draft}")
        return ChannelReply(
            "\n".join(lines),
            actions=[("Approve", f"/approve {short}"), ("Reject", f"/reject {short}")],
        )
    if status in ("completed", "approved"):
        return ChannelReply(
            f"{skill_name} {status} — archived to {result.get('archive_path', '?')}"
        )
    if status in ("deferred_budget", "deferred_degraded", "budget_exceeded"):
        return ChannelReply(f"{skill_name} {status} — the kernel deferred or capped this run.")
    if status == "failed":
        return ChannelReply(f"{skill_name} failed: {result.get('error', 'unknown error')}")
    return ChannelReply(f"{skill_name} finished with status: {status}")


def _match_thread(prefix: str) -> list[str]:
    known = set(pending_threads.keys())
    known.update(row["thread_id"] for row in pending_store.list_all())
    return sorted(t for t in known if t.startswith(prefix))


async def _resolve(prefix: str, *, approved: bool) -> ChannelReply:
    matches = _match_thread(prefix)
    if not matches:
        return ChannelReply(f"No pending thread matches '{prefix}'. Try /pending.")
    if len(matches) > 1:
        shorts = ", ".join(t[:12] for t in matches)
        return ChannelReply(f"Ambiguous prefix '{prefix}' — matches: {shorts}")

    thread_id = matches[0]
    try:
        result = await service.resolve_approval(thread_id, approved)
    except ApprovalNotFound:
        return ChannelReply(f"Thread {thread_id[:8]} was already resolved.")
    except ApprovalUnavailable as exc:
        return ChannelReply(f"Cannot resume {thread_id[:8]}: {exc}")

    if result.get("status") == "terminated":
        return ChannelReply(f"Rejected — thread {thread_id[:8]} terminated.")
    return ChannelReply(
        f"Approved — thread {thread_id[:8]} finished, "
        f"archived to {result.get('archive_path', '?')}"
    )


def _draft_preview(thread_id: str) -> str:
    row = interrupt_table.get(thread_id)
    draft = ((row or {}).get("payload") or {}).get("draft", "")
    if len(draft) > _DRAFT_PREVIEW_CHARS:
        return draft[:_DRAFT_PREVIEW_CHARS] + "…"
    return draft


def _pending_reply() -> ChannelReply:
    if not pending_threads:
        return ChannelReply("Nothing waiting for approval.")
    lines = ["Waiting for approval:"]
    actions: list[tuple[str, str]] = []
    for thread_id, meta in pending_threads.items():
        short = thread_id[:8]
        lines.append(f"{short} — {meta['skill_name']}")
        if len(actions) < 6:  # keep button rows sane on small screens
            actions.append((f"Approve {short}", f"/approve {short}"))
            actions.append((f"Reject {short}", f"/reject {short}"))
    lines.append("\n/approve <id> or /reject <id>")
    return ChannelReply("\n".join(lines), actions=actions)


def _status_reply() -> ChannelReply:
    stats = telemetry.get_stats()
    lines = [
        f"Runs: {stats.get('total_runs', 0)} "
        f"({stats.get('success_rate', 0.0) * 100:.0f}% success)",
        f"Total cost: ${stats.get('total_cost', 0.0):.4f}",
        f"Pending approvals: {len(pending_threads)}",
    ]
    try:
        from core.llm.budget import get_budget_ledger

        snapshot = get_budget_ledger().snapshot()
        lines.append(
            f"Flash budget: {snapshot['flash_used']}/{snapshot['flash_limit']} today"
        )
    except Exception:  # budget ledger is gemini-specific; never break /status
        pass
    return ChannelReply("\n".join(lines))


def _file_to_inbox(msg: InboundMessage, text: str) -> ChannelReply:
    """Drop free text into 00-Inbox/ — the same ingress as a hand-written note.

    One file per message so each capture gets its own vault-watch trigger
    evaluation (per-path cooldowns would swallow appends to a shared daily
    note). Deterministic ingress code, so this writes directly rather than
    through the LLM-facing ObsidianClient whitelist.
    """
    inbox = settings.vault_path / "00-Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = f"-{msg.message_id}" if msg.message_id else ""
    path = inbox / f"{msg.channel}-{stamp}{suffix}.md"
    counter = 0
    while path.exists():
        counter += 1
        path = inbox / f"{msg.channel}-{stamp}{suffix}-{counter}.md"

    captured = datetime.now(timezone.utc).isoformat()
    path.write_text(
        f"---\nsource: {msg.channel}\nsender: \"{msg.sender_id}\"\n"
        f"captured: {captured}\n---\n\n{text}\n",
        encoding="utf-8",
    )
    rel = path.relative_to(settings.vault_path).as_posix()
    logger.info("Channel %s filed note %s", msg.channel, rel)
    return ChannelReply(f"Filed to {rel} — vault triggers will pick it up.")
