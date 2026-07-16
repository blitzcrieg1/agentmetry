# DRAFT. NOT EVALUATED.
#
# Agentmetry does not run OPA today. This file is the target for the
# policy-as-code work listed under "Exploring" in ROADMAP.md. The rules
# actually applied at runtime are the small built-in set in
# apps/orchestrator/core/audit/policy.py, which is off by default.
#
# Nothing here affects behaviour. Do not read it as a shipped feature.

package agentmetry.authz

import future.keywords.in

default allow = false

# By default, we allow execution unless a tool is explicitly restricted
allow {
    not is_restricted_tool
}

# Example restricted tools
restricted_tools := {"kubectl.exec", "aws.iam.delete_user", "shell.rm"}

is_restricted_tool {
    input.tool.qualified in restricted_tools
}

# Even restricted tools can be allowed if they carry a successful human approval
allow {
    is_restricted_tool
    input.action.type == "approval_response"
    input.action.outcome == "success"
}
