#!/usr/bin/env python3
"""Back-compat shim: ingest client renamed to agentmetry_ingest.py.
Stale global hooks keep working until re-bootstrapped."""
from __future__ import annotations
import runpy, sys
from pathlib import Path
_t = Path(__file__).with_name("agentmetry_ingest.py")
if not _t.is_file():
    sys.exit(0)
sys.argv[0] = str(_t)
runpy.run_path(str(_t), run_name="__main__")
