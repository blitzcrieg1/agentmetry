"""Best-effort desktop notifications."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def notify(title: str, message: str) -> None:
    try:
        from plyer import notification

        notification.notify(title=title, message=message[:256], timeout=8)
    except Exception as exc:
        logger.debug("Toast notification skipped: %s", exc)
