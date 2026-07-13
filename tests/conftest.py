"""Pytest path setup for repo-root backend tests."""

from __future__ import annotations

import sys
from pathlib import Path

_ORCH = Path(__file__).resolve().parents[1] / "apps" / "orchestrator"
if str(_ORCH) not in sys.path:
    sys.path.insert(0, str(_ORCH))
