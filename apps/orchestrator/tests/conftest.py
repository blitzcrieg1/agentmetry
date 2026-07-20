"""Shared test guardrails."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch: pytest.MonkeyPatch):
    """Hermetic defaults — tests must not depend on operator .env secrets."""
    yield
