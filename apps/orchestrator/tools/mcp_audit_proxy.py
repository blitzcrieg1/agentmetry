#!/usr/bin/env python3
"""Compatibility alias. The proxy moved to `agentmetry.hooks.mcp_proxy`.

MCP configs on developer machines name this file by absolute path, and they
are not ours to rewrite. So the path stays and forwards, the same way
`scripts/agentmetry_ingest.py` does. New configs should use
`agentmetry mcp-proxy -- <server command>`, which works without a checkout.

`sys.modules` is rebound rather than re-exported so that this name and
`agentmetry.hooks.mcp_proxy` are one module object: a test or an operator
patching an internal patches the code that actually runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from agentmetry.hooks import mcp_proxy as _proxy
except ImportError:  # pragma: no cover - a checkout with nothing installed
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from agentmetry.hooks import mcp_proxy as _proxy

if __name__ == "__main__":
    sys.exit(_proxy.main())
else:
    sys.modules[__name__] = _proxy
