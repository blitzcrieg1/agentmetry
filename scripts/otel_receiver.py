#!/usr/bin/env python3
"""OTLP receiver for Claude Code's native telemetry. Moved into the package.

This is now `agentmetry otel`, and the code is
`apps/orchestrator/agentmetry/core/audit/otel_ingest.py`. This shim keeps the
prototype's flags working for anyone who wired it up before 0.9.0:

    python scripts/otel_receiver.py [--orchestrator URL] [--port 4318]
                                    [--keep-command] [--print-mapping]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "orchestrator"))

from agentmetry.core.audit import otel_ingest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--orchestrator", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--keep-command", action="store_true")
    parser.add_argument("--print-mapping", action="store_true")
    args = parser.parse_args()

    if args.print_mapping:
        for line in otel_ingest.mapping_lines():
            print(line)
        return 0
    orchestrator = (
        args.orchestrator or os.environ.get("AGENTMETRY_URL") or "http://127.0.0.1:8000"
    ).rstrip("/")
    os.environ["AGENTMETRY_URL"] = orchestrator
    if args.keep_command:
        os.environ["AGENTMETRY_LOG_COMMANDS"] = "1"
    return otel_ingest.serve(args.port or otel_ingest.default_port(), orchestrator)


if __name__ == "__main__":
    sys.exit(main())
