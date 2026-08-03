"""Local policy checks for agent tool calls.

**This is not OPA.** It is a small built-in ruleset. Real OPA/Rego evaluation is
on the roadmap; `policies/opa/agent_rules.rego` is a draft for that work and is
NOT evaluated by this module.

Two design rules, both learned the hard way:

1. **Annotate, never rewrite.** A policy verdict is a separate fact from what
   actually happened. The previous version set `action.outcome = "denied"` on
   events that had *already executed* on the agent's machine, which put a lie in
   the audit trail: an incident responder would read "denied" for a tool that
   ran. It also blinded every detection rule that keys on `outcome == "success"`
   (a burst of `shell.rm` stopped firing `destructive-delete-burst` precisely
   because policy flagged it). The verdict now lands in its own `policy` block
   and `action` is left alone.

2. **This cannot block.** By the time an event reaches the ingest API the tool
   has already run. Real prevention has to happen in the hook process,
   pre-execution, the way DLP `block` mode does. The annotation records
   `enforced: false` so nobody mistakes it for enforcement.

Off by default (`AGENTMETRY_POLICY_ENABLED=1` to turn on): the ruleset below is
a hardcoded starting point, not something to impose on every operator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PolicyVerdict:
    allowed: bool
    rule_id: str = ""
    reason: str = ""


def _norm(name: str) -> str:
    """Fold a tool name the same way core.audit.mitre does.

    Exact string matching on `tool.qualified` was trivially evadable: a rule for
    "shell.rm" missed "shell.RM" and "shell_rm". Normalizing at least closes the
    spelling gap. It does NOT close the real gap (see module docstring): a shell
    tool running `rm -rf` under any name is still not caught here.
    """
    return name.lower().replace("_", "").replace("-", "")


# Tools that should not run unattended. Deliberately tiny: this is a default,
# not a policy language. The roadmap replaces it with real Rego.
_RESTRICTED: dict[str, str] = {
    _norm("kubectl.exec"): "restricted:kubectl-exec",
    _norm("aws.iam.delete_user"): "restricted:iam-delete-user",
    _norm("shell.rm"): "restricted:shell-rm",
}


def evaluate_policy(event: dict[str, Any]) -> PolicyVerdict:
    """Return a verdict for one canonical event. Never mutates the event."""
    tool = event.get("tool")
    qualified = str(tool.get("qualified") or "") if isinstance(tool, dict) else ""
    if not qualified:
        return PolicyVerdict(allowed=True)

    rule_id = _RESTRICTED.get(_norm(qualified))
    if rule_id is None:
        return PolicyVerdict(allowed=True)

    # A restricted tool is allowed when a human explicitly approved this action.
    action = event.get("action") or {}
    if action.get("type") == "approval_response" and action.get("outcome") == "success":
        return PolicyVerdict(allowed=True)

    return PolicyVerdict(
        allowed=False,
        rule_id=rule_id,
        reason=f"{qualified} is restricted and had no recorded human approval",
    )


def annotate(event: dict[str, Any]) -> None:
    """Attach a policy verdict to `event['policy']`, in place.

    Only writes when the verdict is a denial, and only ever touches the `policy`
    key. `action.outcome` stays whatever actually happened.
    """
    verdict = evaluate_policy(event)
    if verdict.allowed:
        return
    event["policy"] = {
        "decision": "deny",
        "rule_id": verdict.rule_id,
        "engine": "builtin",
        # This event already executed. We observed it; we did not stop it.
        "enforced": False,
        "reason": verdict.reason,
    }
