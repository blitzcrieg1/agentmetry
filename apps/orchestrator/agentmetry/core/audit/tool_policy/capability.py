"""Where a policy `ask` reaches a human as a prompt, per agent and hook.

An ask the agent ignores is an allow. Every vendor that does not recognise the
ask value treats the hook as having said nothing, and the tool runs. That is the
worst way for this control to fail, because the operator wrote a rule asking
for a human and got no human and no block.

So the default for every agent and hook is that an ask is NOT honoured, and the
hook enforces it as deny. Only the pairs below, each checked against the
vendor's published hook documentation, are trusted to show a real prompt.

Deliberately absent, because their documentation says they do not honour it:

  Cursor preToolUse       "accepted by the schema but not enforced today"
  any PermissionRequest   Claude Code's schema takes allow|deny only

Absent because nobody has checked: every other agent and hook. That includes
Qwen, Qoder, CodeBuddy and Kimi, which speak Claude Code's hook protocol and so
receive the same encoding, but whose vendors have not been verified to honour an
ask. A pair is added here when somebody has read that vendor's documentation,
not because the protocol looks compatible.

Pure stdlib on purpose. The hook imports this on every tool call, and #171 is
about what the hook already pays to import.
"""

from __future__ import annotations

ASK_HONOURED: frozenset[tuple[str, str]] = frozenset(
    {
        # Claude Code: hookSpecificOutput.permissionDecision = "ask".
        ("claude", "PreToolUse"),
        # Cursor: permission = "ask" returns a prompt on these two only.
        ("cursor", "beforeShellExecution"),
        ("cursor", "beforeMCPExecution"),
    }
)


def ask_honoured(source_app: str, hook_name: str) -> bool:
    """True only where an ask is known to reach a human."""
    return (str(source_app).lower(), hook_name) in ASK_HONOURED
