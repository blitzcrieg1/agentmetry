"""Who is running the agent, as the operating system says. Standard library only.

The hook imports this on every tool call, inside the agent's own process, so it
must not pull in pydantic or settings (#171 is about exactly that cost). The
orchestrator imports it too, as a fallback, and that is why it lives under
`core` rather than `hooks`.

This answers "which account", not "which person", and it is a claim, not a
proof: anything that can set an environment variable can change it. Making a
fleet trail attributable rather than asserted is per-host signing, a separate
piece of work. What this removes is the constant: before it, every event on
every machine said the operator was `local`.
"""

from __future__ import annotations

import getpass
import os
from collections.abc import Mapping

#: What hooks up to 0.9.0 sent for every event. Read as "not stated", never as
#: a name, so an old hook in the field does not pin its events to a constant.
LEGACY_PLACEHOLDER = "local"

#: What the hook says about how it knew, on the wire in `operator.source`.
CONFIGURED = "configured"  # AGENTMETRY_OPERATOR_ID, set by somebody on purpose
OS = "os"                  # the account the capture process ran as

#: Where a recorded id came from, in `initiator.operator_source`. The prefix is
#: the point: `hook_*` and `client` are claims a capture surface made, and
#: anyone holding the ingest key can make them. `orchestrator_*` the recorder
#: resolved itself.
HOOK_CONFIGURED = "hook_configured"
HOOK_OS = "hook_os"
CLIENT = "client"  # asserted without saying how
ORCHESTRATOR_CONFIGURED = "orchestrator_configured"
ORCHESTRATOR_OS = "orchestrator_os"  # the recorder's own account; under a fleet service, not the developer
DEFAULT = "default"  # nothing resolved

RECORDED_SOURCES = frozenset({
    HOOK_CONFIGURED, HOOK_OS, CLIENT, ORCHESTRATOR_CONFIGURED, ORCHESTRATOR_OS, DEFAULT,
})


def os_operator() -> str:
    """The account this process runs as, domain-qualified where there is a domain.

    On Windows `CORP\\jdoe` and a local `jdoe` are different people on a fleet,
    so the domain is kept. A local account's `USERDOMAIN` is the machine's own
    name, which adds nothing, so it is dropped. Elsewhere `getpass.getuser()`.

    Empty when nothing can be resolved. Never raises: the hook runs inside the
    agent's tool path and must not be the reason a tool call fails.
    """
    if os.name == "nt":
        account = windows_account(os.environ)
        if account:
            return account
    try:
        return getpass.getuser().strip()
    except Exception:  # noqa: BLE001 - getpass raises OSError, KeyError or ImportError by platform
        return ""


def windows_account(environ: Mapping[str, str]) -> str:
    """`DOMAIN\\user` for a domain or Entra account, bare `user` for a local one."""
    user = str(environ.get("USERNAME", "")).strip()
    if not user:
        return ""
    domain = str(environ.get("USERDOMAIN", "")).strip()
    machine = str(environ.get("COMPUTERNAME", "")).strip()
    if domain and domain.upper() != machine.upper():
        return f"{domain}\\{user}"
    return user


def stated(value: object) -> str:
    """An id somebody actually stated, or empty.

    Empty for nothing, and for `local`, whether a hook sent it or a `.env` says
    it. Both `.env.example` files shipped `AGENTMETRY_OPERATOR_ID=local` up to
    0.9.1 and both installers copied it, so on an installed machine `local` in
    the config is the old placeholder, not a choice. Read as configured, it
    overrode the OS account and every event said `local` again.
    """
    text = str(value or "").strip()
    return "" if text == LEGACY_PLACEHOLDER else text
