#!/usr/bin/env python3
"""Compatibility shim. The implementation moved to `agentmetry.hooks.ingest`.

Every hook installed on a developer machine names this file by absolute path
inside `~/.cursor/hooks.json`, `~/.claude/settings.json` and the rest. Those
configs are not ours to rewrite on somebody's machine, and a rename that
silently stopped capture would be the worst failure this project has. So the
path stays and forwards.

The move itself was not cosmetic. Living only in `scripts/` meant capture
existed only where the git repository existed, which is why an MSI install had
a running recorder no hook could reach. See the module docstring.

## Why this aliases rather than re-exports

`from ... import *` skips underscore names and would produce a second module
object holding copies. Anything that reached past the public surface, a test
monkeypatching `_spool_path` or an operator poking at internals, would then
patch the copy while the real code kept using the original. Rebinding
`sys.modules` means `agentmetry_ingest` and `agentmetry.hooks.ingest` are the
same object, so the two can never disagree about anything.

New code should import `agentmetry.hooks.ingest` directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from agentmetry.hooks import ingest as _ingest
except ImportError:  # pragma: no cover - only on a checkout with nothing installed
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "orchestrator"))
    from agentmetry.hooks import ingest as _ingest

if __name__ == "__main__":
    sys.exit(_ingest.main())
else:
    # Hand callers the real module. Rebinding __main__ would be a different and
    # much worse trick, hence the branch.
    sys.modules[__name__] = _ingest
