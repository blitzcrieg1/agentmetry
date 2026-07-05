"""Telegram channel adapter — long-polling bot, allowlisted operator chats.

Reach without exposure: long polling means no public webhook, no open port,
works behind NAT on a Windows laptop. Only chat ids in the allowlist are
served; everything else is logged and dropped.

Outbound push closes the loop: approval gates raised by *any* surface
(vault triggers, cron, dashboard) land on the operator's phone with
Approve / Reject buttons, and autonomous runs report their completions.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from core.bus.bus import bus
from core.bus.events import RUN_COMPLETED, RUN_FAILED, RUN_WAITING
from core.channels.base import ChannelReply, InboundMessage
from core.channels.router import route_inbound
from core.config import settings
from core.execution.context import pending_threads

logger = logging.getLogger(__name__)

_POLL_TIMEOUT_S = 50
_ERROR_BACKOFF_S = 5
_MESSAGE_LIMIT = 4000  # Telegram hard limit is 4096


class TelegramChannel:
    name = "telegram"

    def __init__(
        self,
        token: str,
        allowed_chat_ids: set[str],
        api_base: str = "https://api.telegram.org",
    ):
        if not token:
            raise ValueError("Telegram channel needs a bot token")
        if not allowed_chat_ids:
            raise ValueError("Telegram channel needs at least one allowed chat id")
        self._base = f"{api_base}/bot{token}"
        self._allowed = {c.strip() for c in allowed_chat_ids if c.strip()}
        self._client: httpx.AsyncClient | None = None
        self._tasks: list[asyncio.Task] = []
        self._bus_sub = None

    @classmethod
    def from_settings(cls) -> TelegramChannel:
        chat_ids = {
            c.strip() for c in settings.telegram_allowed_chat_ids.split(",") if c.strip()
        }
        return cls(settings.telegram_bot_token, chat_ids)

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(_POLL_TIMEOUT_S + 10))
        self._bus_sub = bus.subscribe(
            "telegram-push",
            topics={RUN_WAITING, RUN_COMPLETED, RUN_FAILED},
            maxsize=256,
            drop_oldest=True,
        )
        self._tasks = [
            asyncio.create_task(self._poll_loop(), name="telegram-poll"),
            asyncio.create_task(self._push_loop(), name="telegram-push"),
        ]
        logger.info("Telegram channel started (%d allowed chat(s))", len(self._allowed))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks = []
        if self._bus_sub is not None:
            bus.unsubscribe(self._bus_sub)
            self._bus_sub = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # -- inbound ---------------------------------------------------------

    async def _poll_loop(self) -> None:
        offset: int | None = None
        while True:
            try:
                updates = await self._get_updates(offset)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Telegram poll error: %s", exc)
                await asyncio.sleep(_ERROR_BACKOFF_S)
                continue
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    await self._handle_update(update)
                except Exception:
                    logger.exception("Telegram update handling failed")

    async def _get_updates(self, offset: int | None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": _POLL_TIMEOUT_S,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        data = await self._api("getUpdates", payload)
        return data.get("result", [])

    async def _handle_update(self, update: dict[str, Any]) -> None:
        if "callback_query" in update:
            await self._handle_callback(update["callback_query"])
            return
        message = update.get("message") or {}
        text = message.get("text", "")
        chat_id = str((message.get("chat") or {}).get("id", ""))
        if not text or not chat_id:
            return
        if chat_id not in self._allowed:
            logger.warning("Telegram message from non-allowlisted chat %s dropped", chat_id)
            return
        reply = await route_inbound(InboundMessage(
            channel=self.name,
            sender_id=chat_id,
            text=text,
            message_id=str(message.get("message_id", "")),
        ))
        await self._send(chat_id, reply)

    async def _handle_callback(self, callback: dict[str, Any]) -> None:
        """Inline button press — its data is a command, routed like typed text."""
        chat_id = str(((callback.get("message") or {}).get("chat") or {}).get("id", ""))
        command = callback.get("data", "")
        # Always ack so the client stops its spinner, even for denied chats.
        await self._api("answerCallbackQuery", {"callback_query_id": callback["id"]})
        if not command or not chat_id:
            return
        if chat_id not in self._allowed:
            logger.warning("Telegram callback from non-allowlisted chat %s dropped", chat_id)
            return
        reply = await route_inbound(InboundMessage(
            channel=self.name, sender_id=chat_id, text=command,
        ))
        await self._send(chat_id, reply)

    # -- outbound --------------------------------------------------------

    async def _push_loop(self) -> None:
        """Bridge bus events to the operator's phone.

        Approval gates from non-channel surfaces are pushed with buttons;
        autonomous run outcomes are reported. Channel-initiated runs are
        excluded — the router already answered those synchronously.
        """
        assert self._bus_sub is not None
        own_prefix = f"channel-{self.name}-"
        while True:
            event = await self._bus_sub.get()
            try:
                if event.session_id.startswith(own_prefix):
                    continue
                if event.topic == RUN_WAITING:
                    await self._push_approval(event.payload)
                elif event.session_id.startswith("autonomous-"):
                    await self._push_outcome(event.topic, event.payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Telegram push failed: %s", exc)

    async def _push_approval(self, payload: dict[str, Any]) -> None:
        thread_id = payload.get("thread_id", "")
        short = thread_id[:8]
        skill = (pending_threads.get(thread_id) or {}).get("skill_name", "a skill")
        draft = payload.get("draft", "")
        if len(draft) > 700:
            draft = draft[:700] + "…"
        text = f"Approval needed — {skill} (thread {short})"
        if payload.get("confidence") is not None:
            text += f"\nConfidence: {payload['confidence']:.2f}"
        if draft:
            text += f"\n\n{draft}"
        reply = ChannelReply(
            text,
            actions=[("Approve", f"/approve {short}"), ("Reject", f"/reject {short}")],
        )
        await self._broadcast(reply)

    async def _push_outcome(self, topic: str, payload: dict[str, Any]) -> None:
        thread_id = payload.get("thread_id", "")
        if topic == RUN_COMPLETED:
            cost = (payload.get("metrics") or {}).get("cost", 0.0)
            text = (
                f"Autonomous run completed (thread {thread_id[:8]}) — "
                f"${cost:.4f}, archived to {payload.get('archive_path', '?')}"
            )
        else:
            text = (
                f"Autonomous run failed (thread {thread_id[:8]}): "
                f"{payload.get('error', 'unknown error')}"
            )
        await self._broadcast(ChannelReply(text))

    async def _broadcast(self, reply: ChannelReply) -> None:
        for chat_id in self._allowed:
            await self._send(chat_id, reply)

    async def _send(self, chat_id: str, reply: ChannelReply) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": reply.text[:_MESSAGE_LIMIT],
        }
        if reply.actions:
            rows = [reply.actions[i:i + 2] for i in range(0, len(reply.actions), 2)]
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": label, "callback_data": command[:64]} for label, command in row]
                    for row in rows
                ]
            }
        try:
            await self._api("sendMessage", payload)
        except Exception as exc:
            logger.warning("Telegram send to %s failed: %s", chat_id, exc)

    async def _api(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert self._client is not None, "channel not started"
        response = await self._client.post(f"{self._base}/{method}", json=payload)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok", False):
            raise RuntimeError(f"Telegram {method} error: {data.get('description', data)}")
        return data
