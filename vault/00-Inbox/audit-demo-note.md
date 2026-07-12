---
title: AgentAudit demo note
purpose: input for the audit_demo skill
---

This note exists only to give the `audit_demo` skill something to read.

Running the skill emits a governed `tool_called` event (vault_fs.read_note),
then pauses at the approval gate. Approve or reject to record the decision.

No customer data, no PII — safe to show on camera.
