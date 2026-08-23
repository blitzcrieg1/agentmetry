"""Emit a Sigma rule per built-in sequence detection, into docs/integrations/sigma/.

Run from the orchestrator:

    .venv/Scripts/python.exe tools/generate_sigma_pack.py

## Why generated rather than written

The Sigma pack that already existed covers the recorder's own health: heartbeat
silence, degraded coverage, MCP schema drift, denial bursts. Useful, and none of
it is the product. The fifteen sequence detections, which are what a SOC would
actually route on, had no Sigma representation at all, so a Splunk or Sentinel
team wanting to alert on `credential-exfil` had to write the search themselves
from a schema document.

Hand-writing fifteen would put rule ids, severities and MITRE ids in a second
place that drifts from the first. So the metadata is harvested by replaying the
benchmark corpus through the real engine and reading the `Detection` objects it
emits. A severity that changes in `rules.py` changes here on the next run, and
`tests/test_sigma_pack.py` fails if somebody forgets to run it.

## The two the corpus cannot produce

`host-subagent-swarm-burst` is host-scoped and needs several sessions on one
host inside a window. `off-hours-activity` is opt-in behind
`AGENTMETRY_DETECT_OFF_HOURS` and needs an operator-set window. Neither has a
corpus case (issue #36), so both carry an explicit entry below.

That table is checked against `BUILTIN_RULE_IDS` rather than trusted: adding a
sixteenth rule without either a corpus case or an entry here fails this script,
rather than silently shipping fourteen rules in a pack that claims fifteen.
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path

from agentmetry.core.audit.detection.benchmark import DEFAULT_CORPUS_DIR
from agentmetry.core.audit.detection.engine import run_detections, run_host_detections
from agentmetry.core.audit.detection.rules import BUILTIN_RULE_IDS

OUT = Path(__file__).resolve().parents[2].parent / "docs" / "integrations" / "sigma"

# Sigma's `level` vocabulary happens to match ours one for one. Mapped
# explicitly anyway, so a new severity fails here rather than emitting a level
# no SIEM recognises.
_LEVEL = {"critical": "critical", "high": "high", "medium": "medium", "low": "low"}

# The two rules no corpus case can produce. Severity comes from
# docs/detection-rules.md, the same table the README renders.
_UNCOVERED: dict[str, dict] = {
    "host-subagent-swarm-burst": {
        "title": "Subagent swarm across sessions on one host",
        "severity": "high",
        "tactics": ["TA0002"],
        "techniques": ["T1059"],
        "note": "Host-scoped: needs several sessions on one host inside a window.",
    },
    "off-hours-activity": {
        "title": "Autonomous impact action outside business hours",
        "severity": "medium",
        "tactics": ["TA0040"],
        "techniques": ["T1485"],
        "note": "Opt-in behind AGENTMETRY_DETECT_OFF_HOURS with an operator-set window.",
    },
}


def _harvest() -> dict[tuple[str, str], dict]:
    """Replay the corpus and read the Detection objects the engine emits.

    Keyed on `(rule_id, severity)` rather than `rule_id`, because one rule id is
    deliberately two detections. `encoded-command-download` returns `critical`
    for remote code fetched and executed and `low` for local content piped into
    an interpreter, with a comment in `rules.py` saying the low one exists "so
    it stops drowning the criticals". A single Sigma `level` would either page
    on the quiet variant or stay silent on the loud one, so each severity gets
    its own rule and the selection pins `action.outcome`.
    """
    found: dict[tuple[str, str], dict] = {}
    for path in sorted(Path(DEFAULT_CORPUS_DIR).glob("*.jsonl")):
        events = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        for det in (*run_detections(events), *run_host_detections(events)):
            found.setdefault(
                (det.rule_id, det.severity),
                {
                    "title": det.title,
                    "severity": det.severity,
                    "tactics": sorted(set(det.tactic_ids)),
                    "techniques": sorted(set(det.technique_ids)),
                    "note": "",
                },
            )
    return found


def _stable_uuid(rule_id: str, severity: str = "") -> str:
    """A deterministic UUID, so regenerating does not churn every id.

    Sigma requires a UUID and consumers key on it, so running this twice must
    produce no diff. Severity joins the seed only for a split rule, which keeps
    the fourteen unsplit ids exactly where they are.
    """
    seed = f"agentmetry.sigma.{rule_id}" + (f".{severity}" if severity else "")
    return str(uuid.UUID(bytes=hashlib.sha256(seed.encode()).digest()[:16], version=5))


def _yaml(rule_id: str, meta: dict, *, split: bool) -> str:
    severity = meta["severity"]
    tags = [f"attack.{t.lower()}" for t in meta["tactics"] + meta["techniques"]]
    tag_lines = "\n".join(f"  - {t}" for t in tags) or "  []"
    note = f"\n  {meta['note']}" if meta.get("note") else ""
    outcome = f"\n    action.outcome: {severity}" if split else ""
    variant = (
        f"\n  This rule id emits more than one severity. This is the `{severity}`"
        " variant, pinned on `action.outcome`."
        if split
        else ""
    )
    return f"""title: Agentmetry - {meta["title"]}
id: {_stable_uuid(rule_id, severity if split else "")}
status: experimental
description: |
  Agentmetry sequence detection `{rule_id}` fired. The individual tool calls are
  ordinary; the order is the finding, and `detection.event_ids` names the exact
  events that produced it.{note}{variant}

  GENERATED by tools/generate_sigma_pack.py. Do not hand-edit: severity and
  MITRE ids are read from the rule engine, so an edit here is a claim that
  disagrees with the code.
references:
  - https://github.com/blitzcrieg1/agentmetry/blob/master/docs/detection-rules.md
author: Agentmetry
logsource:
  product: agentmetry
  service: audit
detection:
  selection:
    action.type: detection
    detection.rule_id: {rule_id}{outcome}
  condition: selection
falsepositives:
  - Legitimate automation that reproduces the sequence. Disposition it in the
    trail rather than deleting the rule, so the decision is recorded.
level: {_LEVEL[severity]}
tags:
{tag_lines}
"""


def main() -> int:
    harvested = _harvest()
    for rule_id, entry in _UNCOVERED.items():
        harvested.setdefault((rule_id, entry["severity"]), entry)

    covered = {rid for rid, _ in harvested}
    missing = sorted(BUILTIN_RULE_IDS - covered)
    if missing:
        print("No corpus case and no _UNCOVERED entry for: " + ", ".join(missing), file=sys.stderr)
        print("Add a corpus case (preferred, see issue #36) or an entry here.", file=sys.stderr)
        return 1

    extra = sorted(covered - BUILTIN_RULE_IDS)
    if extra:
        # A rule that fired in the corpus but is not built in means a YAML rule
        # leaked into the run, which would ship an operator's local rule as ours.
        print("Not a built-in rule: " + ", ".join(extra), file=sys.stderr)
        return 1

    severities: dict[str, set[str]] = {}
    for rid, sev in harvested:
        severities.setdefault(rid, set()).add(sev)

    OUT.mkdir(parents=True, exist_ok=True)
    for rule_id, severity in sorted(harvested):
        split = len(severities[rule_id]) > 1
        stem = rule_id.replace("-", "_") + (f"_{severity}" if split else "")
        (OUT / f"agentmetry_rule_{stem}.yml").write_text(
            _yaml(rule_id, harvested[(rule_id, severity)], split=split), encoding="utf-8"
        )

    split_ids = sorted(r for r, s in severities.items() if len(s) > 1)
    print(f"wrote {len(harvested)} Sigma rules for {len(BUILTIN_RULE_IDS)} rule ids -> {OUT}")
    if split_ids:
        print(f"  split by severity: {', '.join(split_ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
