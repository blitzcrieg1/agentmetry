"""Who ran the agent (#168).

Every event this project wrote said the operator was `local`. Worse than the
issue described: the hook hardcoded `"operator_id": "local"` in twenty-four
payloads and the orchestrator kept any value a client sent, so a configured
AGENTMETRY_OPERATOR_ID never reached a single hook event. On the maintainer's
machine, with it configured, 2,620 of the last 3,761 hook events said `local`.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

from agentmetry.api.routes.audit import ExternalIngestBody
from agentmetry.core import operator_identity as oid
from agentmetry.core.audit import run_context
from agentmetry.core.audit.external import build_external_canonical
from agentmetry.core.config import settings
from agentmetry.hooks import ingest

HOOK_SOURCE = Path(ingest.__file__)


@pytest.fixture(autouse=True)
def _no_repo_env_operator(monkeypatch):
    """The checkout's own .env may set AGENTMETRY_OPERATOR_ID. Tests here say
    explicitly when one is configured."""
    real = ingest._read_repo_env
    monkeypatch.setattr(
        ingest, "_read_repo_env",
        lambda key: "" if key == "AGENTMETRY_OPERATOR_ID" else real(key),
    )


def _captured(payload: dict) -> dict:
    """Run a payload through the hook's post path, offline, and return it as sent."""
    def refuse(*_a, **_k):
        raise urllib.error.URLError("offline")

    original = ingest._urlopen
    ingest._urlopen = refuse
    try:
        ingest.post_ingest(payload, quiet=True, spool=False)
    finally:
        ingest._urlopen = original
    return payload


def _recorded(payload: dict) -> dict:
    """What the ingest route records for a body: validate, dump, canonicalise."""
    body = ExternalIngestBody(**payload).model_dump(exclude_none=True)
    return build_external_canonical(body)


def _claude_pre_tool_use() -> dict:
    return ingest.map_claude_hook("PreToolUse", {
        "hook_event_name": "PreToolUse",
        "session_id": "s-168",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
    })


# ------------------------------------------------------------- the OS account


@pytest.mark.parametrize("env,expected", [
    ({"USERNAME": "jdoe", "USERDOMAIN": "CORP", "COMPUTERNAME": "LAPTOP-1"}, "CORP\\jdoe"),
    ({"USERNAME": "jdoe", "USERDOMAIN": "AzureAD", "COMPUTERNAME": "LAPTOP-1"}, "AzureAD\\jdoe"),
    ({"USERNAME": "jdoe", "USERDOMAIN": "LAPTOP-1", "COMPUTERNAME": "LAPTOP-1"}, "jdoe"),
    ({"USERNAME": "jdoe", "USERDOMAIN": "laptop-1", "COMPUTERNAME": "LAPTOP-1"}, "jdoe"),
    ({"USERNAME": "jdoe"}, "jdoe"),
    ({"USERDOMAIN": "CORP"}, ""),
])
def test_a_windows_account_keeps_its_domain_and_drops_the_machine_name(env, expected):
    """`CORP\\jdoe` and a local `jdoe` are different people on a fleet."""
    assert oid.windows_account(env) == expected


def test_an_unresolvable_account_is_empty_not_an_exception(monkeypatch):
    """The hook runs in the agent's tool path. It must never be why a call fails."""
    def broken():
        raise OSError("no login name")

    monkeypatch.setattr(oid.getpass, "getuser", broken)
    monkeypatch.setattr(oid, "windows_account", lambda _env: "")
    assert oid.os_operator() == ""


def test_the_resolver_costs_the_hook_no_pydantic():
    """#171: the hook already pays for pydantic once. Identity must not add to it."""
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys, agentmetry.core.operator_identity; print('pydantic' in sys.modules)"],
        capture_output=True, text=True, timeout=60, check=True,
    )
    assert out.stdout.strip() == "False"


# --------------------------------------------------------------- precedence


@pytest.mark.parametrize("configured,client_id,client_source,expected", [
    ("", "CORP\\jdoe", "configured", ("CORP\\jdoe", "hook_configured")),
    ("svc-build", "CORP\\jdoe", "configured", ("CORP\\jdoe", "hook_configured")),
    ("svc-build", "CORP\\jdoe", "os", ("svc-build", "orchestrator_configured")),
    ("", "CORP\\jdoe", "os", ("CORP\\jdoe", "hook_os")),
    ("", "CORP\\jdoe", "", ("CORP\\jdoe", "client")),
    ("", "CORP\\jdoe", "orchestrator_os", ("CORP\\jdoe", "client")),
])
def test_precedence(monkeypatch, configured, client_id, client_source, expected):
    monkeypatch.setattr(settings, "operator_id", configured)
    assert run_context.resolve_operator(client_id, client_source) == expected


def test_nothing_stated_falls_back_to_the_recorders_own_account_and_says_so(monkeypatch):
    monkeypatch.setattr(run_context, "_orchestrator_os", lambda: "svc-agentmetry")
    assert run_context.resolve_operator() == ("svc-agentmetry", "orchestrator_os")


def test_nothing_at_all_is_local_labelled_default(monkeypatch):
    monkeypatch.setattr(run_context, "_orchestrator_os", lambda: "")
    assert run_context.resolve_operator() == ("local", "default")


def test_an_old_hooks_local_counts_as_not_stated(monkeypatch):
    """Hooks up to 0.9.0 send `local` for everything. It is not a name."""
    monkeypatch.setattr(run_context, "_orchestrator_os", lambda: "spiro")
    recorded = _recorded({
        "source_app": "claude", "event_type": "tool_called",
        "initiator": {"actor_type": "agent", "trigger": "manual", "operator_id": "local"},
    })
    assert recorded["actor"]["id"] == "spiro"
    assert recorded["initiator"]["operator_source"] == "orchestrator_os"


def test_an_initiator_the_orchestrator_built_keeps_its_label():
    """Re-resolving the recorder's own answer must not relabel it as a claim."""
    built = run_context.build_initiator("cron", ("svc-agentmetry", "orchestrator_os"))
    assert run_context.operator_from_payload({"initiator": built}) == (
        "svc-agentmetry", "orchestrator_os",
    )


# ----------------------------------------------------------------- the hook


def test_no_hook_payload_hardcodes_local_any_more():
    assert not re.findall(r'"operator_id":\s*"local"', HOOK_SOURCE.read_text(encoding="utf-8"))


def test_the_hook_stamps_the_os_account_when_nothing_is_configured():
    sent = _captured(_claude_pre_tool_use())
    assert sent["operator"] == {"id": oid.os_operator(), "source": "os"}
    assert sent["operator"]["id"], "this machine has an account; it must be recorded"


def test_the_hook_stamps_a_configured_id(monkeypatch):
    monkeypatch.setenv("AGENTMETRY_OPERATOR_ID", "jdoe@corp.example")
    sent = _captured(_claude_pre_tool_use())
    assert sent["operator"] == {"id": "jdoe@corp.example", "source": "configured"}


def test_a_spooled_event_keeps_the_account_that_captured_it(monkeypatch, tmp_path):
    """Stamped before spooling, for the same reason the timestamp is: a replay
    days later must not attribute the event to whoever is logged in then."""
    monkeypatch.setattr(ingest, "_spool_path", lambda: tmp_path / "hook-spool.jsonl")

    def refuse(*_a, **_k):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(ingest, "_urlopen", refuse)
    ingest.post_ingest(_claude_pre_tool_use(), quiet=True)
    spooled = json.loads((tmp_path / "hook-spool.jsonl").read_text(encoding="utf-8"))
    assert spooled["payload"]["operator"]["id"] == oid.os_operator()


# ------------------------------------------------------------ end to end


def test_a_fresh_install_no_longer_records_local():
    """The issue's acceptance test: nothing configured, a real hook payload, the
    real route model, the real canonicaliser."""
    recorded = _recorded(_captured(_claude_pre_tool_use()))
    assert recorded["actor"]["id"] == oid.os_operator()
    assert recorded["actor"]["id"] != "local"
    assert recorded["initiator"]["operator_id"] == oid.os_operator()
    assert recorded["initiator"]["operator_source"] == "hook_os"


def test_an_orchestrator_override_now_reaches_hook_events(monkeypatch):
    """It reached none before: every hook sent `local` and a client value won."""
    monkeypatch.setattr(settings, "operator_id", "svc-build")
    recorded = _recorded(_captured(_claude_pre_tool_use()))
    assert recorded["actor"]["id"] == "svc-build"
    assert recorded["initiator"]["operator_source"] == "orchestrator_configured"


def test_a_developers_own_configured_id_beats_the_orchestrators(monkeypatch):
    monkeypatch.setenv("AGENTMETRY_OPERATOR_ID", "jdoe@corp.example")
    monkeypatch.setattr(settings, "operator_id", "svc-build")
    recorded = _recorded(_captured(_claude_pre_tool_use()))
    assert recorded["actor"]["id"] == "jdoe@corp.example"
    assert recorded["initiator"]["operator_source"] == "hook_configured"


def test_an_event_with_no_initiator_is_attributed_too():
    """OTel tool results carry no initiator. They used to get the orchestrator's
    setting, or `local`; now they carry the account the receiver ran as."""
    recorded = _recorded(_captured({
        "source_app": "claude", "adapter": "otel", "event_type": "tool_called",
        "correlation_id": "s-168", "tool": {"qualified": "Bash", "server": "claude"},
    }))
    assert recorded["actor"]["id"] == oid.os_operator()


def test_a_triage_record_says_who_triaged():
    """`decided_by` was an empty string whenever nothing was configured."""
    from agentmetry.core.audit.detection.disposition import build_disposition_event

    event = build_disposition_event(correlation_id="s-168", rule_id="credential-exfil",
                                    status="resolved")
    assert event["disposition"]["decided_by"]
    assert event["actor"]["id"] == event["disposition"]["decided_by"]


# ---------------------------------------- the placeholder the examples shipped


REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("example", [".env.example", "apps/orchestrator/.env.example"])
def test_the_env_examples_ship_no_operator(example):
    """Both shipped `AGENTMETRY_OPERATOR_ID=local` up to 0.9.1, and both
    installers copy the example to `.env`, which pinned every installed
    machine's events to `local` and undid #168."""
    lines = (REPO_ROOT / example).read_text(encoding="utf-8").splitlines()
    values = [ln.split("=", 1)[1].strip() for ln in lines if ln.startswith("AGENTMETRY_OPERATOR_ID=")]
    assert values == [""], values


def test_an_installed_machine_with_the_old_placeholder_records_the_os_account(monkeypatch):
    """The state every installer-built machine is already in: `local` in the
    `.env` the hook reads and in the orchestrator's setting."""
    monkeypatch.setattr(ingest, "_read_repo_env",
                        lambda key: "local" if key == "AGENTMETRY_OPERATOR_ID" else "")
    monkeypatch.setattr(settings, "operator_id", "local")
    recorded = _recorded(_captured(_claude_pre_tool_use()))
    assert recorded["actor"]["id"] == oid.os_operator()
    assert recorded["initiator"]["operator_source"] == "hook_os"


def test_local_in_the_environment_is_not_a_configured_id(monkeypatch):
    monkeypatch.setenv("AGENTMETRY_OPERATOR_ID", "local")
    assert ingest._operator() == {"id": oid.os_operator(), "source": "os"}


def test_the_orchestrators_local_is_not_an_override(monkeypatch):
    monkeypatch.setattr(settings, "operator_id", "local")
    assert run_context.resolve_operator("CORP\\jdoe", "os") == ("CORP\\jdoe", "hook_os")


def test_a_real_configured_id_still_wins(monkeypatch):
    monkeypatch.setattr(settings, "operator_id", "svc-build")
    assert run_context.resolve_operator("CORP\\jdoe", "os") == ("svc-build", "orchestrator_configured")


def test_the_triage_cli_ignores_the_placeholder_too(monkeypatch):
    from agentmetry.cli import _triage_operator

    monkeypatch.setenv("AGENTMETRY_OPERATOR_ID", "local")
    assert _triage_operator() == oid.os_operator()
