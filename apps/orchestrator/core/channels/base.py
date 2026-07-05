"""Channel adapter contract.

Design rule: channels never call the LLM directly. Every inbound message is
normalized into an InboundMessage and routed through the same run_skill() /
resolve_approval() path used by the dashboard, Obsidian plugin, and vault
triggers — so IVT gates, audit, and budget admission apply identically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class InboundMessage:
    channel: str      # adapter name, e.g. "telegram"
    sender_id: str    # channel-native chat/user id (already allowlisted)
    text: str
    message_id: str = ""


@dataclass
class ChannelReply:
    text: str
    # (label, command) pairs. Channels that support buttons render them;
    # pressing one re-routes the command as if the operator typed it.
    actions: list[tuple[str, str]] = field(default_factory=list)


class ChannelAdapter(Protocol):
    name: str

    async def start(self) -> None: ...

    async def stop(self) -> None: ...
