#!/usr/bin/env python3
"""Agentmetry demo, from a clean clone.

The demo lives in the package now, as `agentmetry demo`, because a `pip
install` does not ship this directory. This wrapper stays so a clone, and
`scripts/make_demo_gif.py`, keep working without installing anything:

    python scripts/demo.py                   # classic credential-exfil chain
    python scripts/demo.py --scenario hf     # HF July 2026 agentic patterns
    python scripts/demo.py --scenario all    # both
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "orchestrator"))

from agentmetry.demo import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
