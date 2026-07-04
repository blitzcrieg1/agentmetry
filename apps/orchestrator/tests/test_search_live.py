"""Opt-in live check for the search driver — proves real bytes move.

Skipped by default (mocked coverage lives in test_search_driver.py). Run with a
real key to satisfy the go/no-go "driver proven live" criterion:

    set BLACKBOX_LIVE_TESTS=1
    set SERPER_API_KEY=...        (or TAVILY_API_KEY)
    pytest -q tests/test_search_live.py
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

_LIVE = os.environ.get("BLACKBOX_LIVE_TESTS") == "1"
_HAS_KEY = bool(os.environ.get("SERPER_API_KEY") or os.environ.get("TAVILY_API_KEY"))

pytestmark = pytest.mark.skipif(
    not (_LIVE and _HAS_KEY),
    reason="live test — set BLACKBOX_LIVE_TESTS=1 and SERPER_API_KEY/TAVILY_API_KEY",
)

_SERVER = Path(__file__).resolve().parents[1] / "tools" / "search_server.py"


def _load_server():
    spec = importlib.util.spec_from_file_location("search_server_live", _SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_search_web_returns_real_results():
    server = _load_server()
    out = server.search_web("korean snail mucin wholesale supplier", count=3)
    assert out and out != "(no results)"
    assert "http" in out  # every result carries a URL
