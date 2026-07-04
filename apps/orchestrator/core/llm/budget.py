"""Daily Gemini Flash budget ledger.

Google counts every generateContent request toward RPD/RPM — including 429
failures and retries. This ledger mirrors that so autonomous deferral aligns
with the real quota. Manual runs are never blocked here; a 429 still trips
degraded mode.

Usage is tracked per model — switching from gemini-2.5-flash to flash-lite
starts a fresh counter matching Google's separate RPD pools.
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
                "day TEXT NOT NULL, model TEXT NOT NULL, "
                "flash_calls INTEGER NOT NULL DEFAULT 0, "
                "PRIMARY KEY (day, model))"
            )
            self._migrate_legacy_schema()

    def _migrate_legacy_schema(self) -> None:
        """Upgrade day-only rows from older builds to per-model keys."""
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(daily_usage)").fetchall()
        }
        if "model" in cols:
            return
        self._conn.execute(
            "CREATE TABLE daily_usage_v2 ("
            "day TEXT NOT NULL, model TEXT NOT NULL, "
            "flash_calls INTEGER NOT NULL DEFAULT 0, "
            "PRIMARY KEY (day, model))"
        )
        self._conn.execute(
            "INSERT INTO daily_usage_v2 (day, model, flash_calls) "
            "SELECT day, 'gemini-2.5-flash', flash_calls FROM daily_usage"
        )
        self._conn.execute("DROP TABLE daily_usage")
        self._conn.execute("ALTER TABLE daily_usage_v2 RENAME TO daily_usage")

    def _model(self) -> str:
        return settings.gemini_model

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def record_flash_call(self) -> None:
        """Record one generateContent HTTP attempt (success or rate-limited)."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO daily_usage (day, model, flash_calls) VALUES (?, ?, 1) "
                "ON CONFLICT(day, model) DO UPDATE SET flash_calls = flash_calls + 1",
                (self._today(), self._model()),
            )

    def flash_calls_today(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT flash_calls FROM daily_usage WHERE day = ? AND model = ?",
                (self._today(), self._model()),
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
            "model": self._model(),
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
