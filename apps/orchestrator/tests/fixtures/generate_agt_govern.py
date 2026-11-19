"""Capture FileAuditSink fixtures using AGT commit f85abe1.

Run with a separate AGT installation and an empty output directory.
The fixed HMAC key is for these synthetic fixtures only.
"""

import json
import sys
from pathlib import Path

from agentmesh.governance.approval import AutoRejectApproval
from agentmesh.governance.audit import AuditLog
from agentmesh.governance.audit_backends import FileAuditSink
from agentmesh.governance.govern import govern

KEY = b"agentmetry-synthetic-agt-fixture-key"
POLICY = """
apiVersion: governance.toolkit/v1
name: fixture-policy
default_action: allow
rules:
  - name: fixture-rule
    condition: "action.type == 'write'"
    action: %s
"""


def capture(output: Path) -> None:
    invoked = []

    def harmless_tool(action: str) -> str:
        invoked.append(action)
        return "synthetic result"

    for name, action in (("decisions", "deny"), ("approval", "require_approval")):
        path = output / f"agt_govern_{name}.jsonl"
        wrapped = govern(
            harmless_tool,
            policy=POLICY % action,
            agent_id="fixture-agent",
            audit_file=str(path),
            audit_secret_key=KEY,
            approval_handler=AutoRejectApproval("Synthetic approval rejected"),
            on_deny=lambda decision: decision.action,
        )
        if action == "deny":
            assert wrapped(action="read") == "synthetic result"
        assert wrapped(action="write") == "deny"
        assert FileAuditSink(path, secret_key=KEY).verify_integrity()[0]
    assert invoked == ["read"]

    live = output / "agt_govern_rotation_second.jsonl"
    sink = FileAuditSink(live, secret_key=KEY, max_file_size=1)
    audit = AuditLog(sink=sink)
    for verdict in ("allow", "deny"):
        audit.log("policy_evaluation", "fixture-agent", "read", outcome=verdict, policy_decision=verdict)
    first, = output.glob("agt_govern_rotation_second.*.jsonl")
    first.rename(output / "agt_govern_rotation_first.jsonl")
    for path in output.glob("agt_govern_rotation_*.jsonl"):
        assert FileAuditSink(path, secret_key=KEY).verify_integrity()[0]
        assert json.loads(path.read_text(encoding="utf-8"))["previous_hash"] == ""


if __name__ == "__main__":
    directory = Path(sys.argv[1]).resolve()
    if not directory.is_dir() or any(directory.iterdir()):
        raise SystemExit("Use an empty output directory for a fresh fixture capture.")
    capture(directory)
