"""Daily Gemini Flash budget ledger.

The free tier allows ~20 generateContent requests per day. This ledger counts
successful calls per UTC day so autonomous triggers can defer before the quota
is gone, keeping a reserve for interactive use. Manual runs are never blocked
here — a real 429 still flips degraded mode.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from core.config import settings

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class BudgetLedger:
    def __init__(self, db_path: str | Path | None = None):
        path = Path(db_path) if db_path else _DATA_DIR / "budget.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = Lock()
        with self._lock, self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS daily_usage ("
                "day TEXT PRIMARY KEY, flash_calls INTEGER NOT NULL DEFAULT 0)"
            )

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def record_flash_call(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO daily_usage (day, flash_calls) VALUES (?, 1) "
                "ON CONFLICT(day) DO UPDATE SET flash_calls = flash_calls + 1",
                (self._today(),),
            )

    def flash_calls_today(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT flash_calls FROM daily_usage WHERE day = ?", (self._today(),)
            ).fetchone()
        return int(row[0]) if row else 0

    def remaining_today(self) -> int:
        return max(0, settings.gemini_flash_daily_limit - self.flash_calls_today())

    def autonomous_allowed(self) -> bool:
        """Autonomous runs pause once only the interactive reserve is left."""
        return self.remaining_today() > settings.gemini_flash_interactive_reserve

    def snapshot(self) -> dict[str, Any]:
        used = self.flash_calls_today()
        return {
            "day": self._today(),
            "flash_used": used,
            "flash_limit": settings.gemini_flash_daily_limit,
            "flash_remaining": max(0, settings.gemini_flash_daily_limit - used),
            "interactive_reserve": settings.gemini_flash_interactive_reserve,
            "autonomous_allowed": self.autonomous_allowed(),
        }


_ledger: BudgetLedger | None = None


def get_budget_ledger() -> BudgetLedger:
    global _ledger
    if _ledger is None:
        _ledger = BudgetLedger()
    return _ledger
