"""Tests for the daily Gemini Flash budget ledger."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import settings
from core.llm.budget import BudgetLedger


@pytest.fixture
def ledger(tmp_path: Path) -> BudgetLedger:
    return BudgetLedger(tmp_path / "budget.db")


def test_counts_accumulate(ledger: BudgetLedger):
    assert ledger.flash_calls_today() == 0
    ledger.record_flash_call()
    ledger.record_flash_call()
    assert ledger.flash_calls_today() == 2


def test_each_api_attempt_counts_including_failures(ledger: BudgetLedger):
    """Google RPD includes 429s — ledger records every generateContent attempt."""
    for _ in range(3):
        ledger.record_flash_call()
    assert ledger.flash_calls_today() == 3


def test_day_rollover(ledger: BudgetLedger, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(BudgetLedger, "_today", staticmethod(lambda: "2026-07-03"))
    ledger.record_flash_call()
    assert ledger.flash_calls_today() == 1

    monkeypatch.setattr(BudgetLedger, "_today", staticmethod(lambda: "2026-07-04"))
    assert ledger.flash_calls_today() == 0
    ledger.record_flash_call()
    assert ledger.flash_calls_today() == 1


def test_autonomous_pauses_at_reserve(ledger: BudgetLedger, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "gemini_flash_daily_limit", 20)
    monkeypatch.setattr(settings, "gemini_flash_interactive_reserve", 8)

    for _ in range(11):
        ledger.record_flash_call()
    # 9 remaining > 8 reserve — still allowed.
    assert ledger.autonomous_allowed()

    ledger.record_flash_call()
    # 8 remaining == reserve — paused.
    assert not ledger.autonomous_allowed()
    assert ledger.remaining_today() == 8


def test_snapshot_shape(ledger: BudgetLedger, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "gemini_flash_daily_limit", 20)
    monkeypatch.setattr(settings, "gemini_flash_interactive_reserve", 8)
    ledger.record_flash_call()

    snap = ledger.snapshot()
    assert snap["flash_used"] == 1
    assert snap["flash_remaining"] == 19
    assert snap["autonomous_allowed"] is True


def test_persists_across_instances(tmp_path: Path):
    db = tmp_path / "budget.db"
    BudgetLedger(db).record_flash_call()
    assert BudgetLedger(db).flash_calls_today() == 1


def test_usage_isolated_per_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "budget.db"
    monkeypatch.setattr(settings, "gemini_model", "gemini-2.5-flash")
    BudgetLedger(db).record_flash_call()
    monkeypatch.setattr(settings, "gemini_model", "gemini-2.5-flash-lite")
    assert BudgetLedger(db).flash_calls_today() == 0
    BudgetLedger(db).record_flash_call()
    assert BudgetLedger(db).flash_calls_today() == 1
