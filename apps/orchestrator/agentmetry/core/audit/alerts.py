"""Alerting engine for high-severity audit events."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class AlertWebhookSink:
    """Fires webhooks (Slack/Discord) for high-severity events."""

    def __init__(self, url: str, *, timeout_seconds: float = 5.0) -> None:
        self._url = url
        self._timeout = timeout_seconds

    async def emit(self, canonical: dict[str, Any]) -> None:
        action = canonical.get("action", {})
        outcome = action.get("outcome")

        # Only fire on denied or error
        if outcome not in ("denied", "error"):
            return

        tool = canonical.get("tool", {})
        tool_name = tool.get("qualified", "unknown_tool")
        agent_name = canonical.get("agent", {}).get("skill_id") or canonical.get("source", {}).get("app", "unknown_agent")

        text = f"🚨 *Agentmetry Alert*\nAgent `{agent_name}` attempted to run `{tool_name}` but the action resulted in `{outcome}`."

        payload = {
            "text": text,
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": text
                    }
                }
            ]
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._url,
                    json=payload,
                    headers={"Content-Type": "application/json", "User-Agent": "Agentmetry-Alerts/1.0"},
                )
                response.raise_for_status()
        except Exception:
            logger.exception("Alert webhook POST failed → %s", self._url)
