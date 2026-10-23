"""The ingest-only token: it posts events, and it does nothing else (#302).

Codex's default Windows sandbox runs hooks as its own local accounts, which
could not read the full API token, so every Codex event was refused and lost.
The fix gives those accounts a second credential that the ingest route alone
accepts. These tests hold both halves: it works where it must, and it is
refused everywhere it must not reach.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentmetry.core import api_token
from agentmetry.core.config import settings
from agentmetry.core.dashboard_session import sessions
from agentmetry.core.diagnostics import doctor, hook_coverage

_EVENT = {
    "source_app": "codex",
    "event_type": "tool_called",
    "correlation_id": "ingest-token-test",
    "tool": {"qualified": "shell.run", "server": "shell", "input_hash": "0" * 64},
}


@pytest.fixture
def tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    full = tmp_path / "data" / "api-token"
    ingest = tmp_path / "data" / "ingest-token"
    monkeypatch.setenv("AGENTMETRY_API_TOKEN_FILE", str(full))
    monkeypatch.setenv("AGENTMETRY_INGEST_TOKEN_FILE", str(ingest))
    for name in ("AGENTMETRY_AUTH_DISABLED", "AGENTMETRY_API_KEY", "BLACKBOX_API_KEY", "AGENTMETRY_TOKEN_SHARED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "api_key", "")
    sessions.clear()
    yield full, ingest
    sessions.clear()


@pytest.fixture
def client(tokens, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "audit_db_path", tmp_path / "audit.db")
    monkeypatch.setattr(settings, "audit_export_path", tmp_path / "trail.jsonl")
    monkeypatch.setattr(settings, "detection_disposition_db_path", tmp_path / "disp.db")
    monkeypatch.setattr(settings, "audit_export_enabled", True)
    monkeypatch.setattr(settings, "audit_ingest_enabled", True)

    from agentmetry.core.audit.detection.disposition import reset_disposition_store
    from agentmetry.core.audit.trail_db import reset_trail_db

    reset_trail_db()
    reset_disposition_store()
    from agentmetry.api.main import app

    with TestClient(app) as test_client:
        yield test_client


def _key(path: Path) -> dict[str, str]:
    return {"X-API-Key": path.read_text(encoding="utf-8").strip()}


# --- the suite itself ---------------------------------------------------------------


def test_no_test_can_reach_the_real_token_files(tmp_path_factory):
    """The first run of this change wrote an ingest token into the real data
    directory, and the live hooks switched to it. conftest now isolates both."""
    base = tmp_path_factory.getbasetemp().resolve()
    assert api_token.token_path().resolve().is_relative_to(base)
    assert api_token.ingest_token_path().resolve().is_relative_to(base)


# --- the recorder mints it -----------------------------------------------------


def test_the_recorder_mints_an_ingest_token_distinct_from_the_full_one(client, tokens):
    full, ingest = tokens
    client.get("/api/v1/audit/status", headers=_key(full))
    assert ingest.is_file()
    assert ingest.read_text(encoding="utf-8").strip() != api_token.read_token(full)


def test_an_existing_ingest_token_is_kept(tokens):
    """Enterprise writes a host-bound one; the core must not replace it."""
    _, ingest = tokens
    api_token.write_ingest_token("provisioned-by-enterprise", ingest)
    assert api_token.ensure_ingest_token(ingest) == "provisioned-by-enterprise"


def test_minting_twice_returns_the_same_token(tokens):
    _, ingest = tokens
    assert api_token.ensure_ingest_token(ingest) == api_token.ensure_ingest_token(ingest)


# --- what it may do, and what it may not ---------------------------------------


def test_the_ingest_token_posts_an_event(client, tokens):
    _, ingest = tokens
    assert client.post("/api/v1/audit/ingest", json=_EVENT, headers=_key(ingest)).status_code == 200


def test_the_full_token_still_posts_an_event(client, tokens):
    full, _ = tokens
    assert client.post("/api/v1/audit/ingest", json=_EVENT, headers=_key(full)).status_code == 200


def test_a_wrong_token_is_still_refused_on_ingest(client):
    resp = client.post("/api/v1/audit/ingest", json=_EVENT, headers={"X-API-Key": "not-a-token"})
    assert resp.status_code == 401


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("get", "/api/v1/audit/tail"),
        ("get", "/api/v1/audit/status"),
        ("get", "/api/v1/audit/export/evidence"),
        ("get", "/api/v1/audit/detections/dispositions/all"),
        ("post", "/api/v1/audit/detections/disposition"),
    ],
)
def test_the_ingest_token_reaches_nothing_else(client, tokens, method, url):
    """A sandboxed agent that reads this token can add events, never read or triage them."""
    _, ingest = tokens
    client.post("/api/v1/audit/ingest", json=_EVENT, headers=_key(ingest))
    kwargs = {"json": {"correlation_id": "x", "rule_id": "y", "status": "false_positive", "note": "n"}} if method == "post" else {}
    resp = getattr(client, method)(url, headers=_key(ingest), **kwargs)
    assert resp.status_code == 401, f"{method.upper()} {url} accepted the ingest-only token"


def test_bearer_form_works_too(client, tokens):
    _, ingest = tokens
    token = ingest.read_text(encoding="utf-8").strip()
    resp = client.post("/api/v1/audit/ingest", json=_EVENT, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


# --- the hook ---------------------------------------------------------------------


def test_the_selftest_reads_the_trail_with_the_full_token(tokens, monkeypatch):
    """The hook prefers the ingest token for posting; reading needs the full one."""
    from agentmetry.hooks import ingest as hook

    full, ingest_path = tokens
    monkeypatch.setattr(hook, "_read_repo_env", lambda _key: "")
    full_token = api_token.ensure_token(full)
    api_token.ensure_ingest_token(ingest_path)
    seen: dict[str, str] = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"events": []}'

    def fake_urlopen(req, timeout):
        seen.update(req.headers)
        return _Resp()

    monkeypatch.setattr(hook, "_urlopen", fake_urlopen)
    hook._get_tail("codex")
    assert seen.get("X-api-key") == full_token
    assert hook._api_key() != full_token


# --- granting Codex's sandbox accounts ----------------------------------------


def test_the_codex_installer_grants_only_the_ingest_token(tokens, monkeypatch):
    from agentmetry.core.audit import hook_bootstrap

    _, ingest = tokens
    calls: list[tuple[Path, list[str]]] = []
    monkeypatch.setattr(api_token, "codex_sandbox_accounts", lambda: ["CodexSandboxOffline", "CodexSandboxOnline"])
    monkeypatch.setattr(api_token, "grant_read", lambda path, accounts: calls.append((path, accounts)) or accounts)
    granted = hook_bootstrap.grant_codex_sandbox_ingest()
    assert granted == ["CodexSandboxOffline", "CodexSandboxOnline"]
    assert calls == [(ingest, ["CodexSandboxOffline", "CodexSandboxOnline"])]
    assert ingest.is_file()


def test_no_sandbox_accounts_means_nothing_is_granted_or_written(tokens, monkeypatch):
    from agentmetry.core.audit import hook_bootstrap

    _, ingest = tokens
    monkeypatch.setattr(api_token, "codex_sandbox_accounts", lambda: [])
    monkeypatch.setattr(api_token, "grant_read", lambda *a: pytest.fail("granted with no accounts"))
    assert hook_bootstrap.grant_codex_sandbox_ingest() == []
    assert not ingest.exists()


@pytest.mark.skipif(os.name != "nt", reason="the Windows ACL path")
def test_grant_read_asks_icacls_for_read_only(tmp_path, monkeypatch):
    import subprocess

    target = tmp_path / "ingest-token"
    target.write_text("t", encoding="utf-8")
    seen: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert api_token.grant_read(target, ["CodexSandboxOffline"]) == ["CodexSandboxOffline"]
    assert seen == [["icacls", str(target), "/grant", "CodexSandboxOffline:R"]]


@pytest.mark.skipif(os.name != "nt", reason="the Windows ACL path")
def test_readable_by_reads_the_acl(tmp_path, monkeypatch):
    import subprocess

    out = (
        f"{tmp_path}\\ingest-token HOST\\CodexSandboxOffline:(R)\n"
        "                           HOST\\someone:(F)\n"
    )
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, out, ""))
    assert api_token.readable_by(tmp_path / "ingest-token", ["CodexSandboxOffline", "CodexSandboxOnline"]) == [
        "CodexSandboxOffline"
    ]


# --- doctor -------------------------------------------------------------------------


def _report_with_codex_covered() -> doctor.DoctorReport:
    report = doctor.DoctorReport()
    report.hooks = {"codex": hook_coverage.COVERED}
    return report


def _codex_findings(report: doctor.DoctorReport):
    return [f for f in report.findings if f.code == "codex_sandbox"]


def test_doctor_fails_when_the_sandbox_has_no_token_to_read(tokens, monkeypatch):
    monkeypatch.setattr(api_token, "codex_sandbox_accounts", lambda: ["CodexSandboxOffline"])
    report = _report_with_codex_covered()
    doctor._check_codex_sandbox(report)
    [finding] = _codex_findings(report)
    assert finding.severity == "fail" and "lost" in finding.message


def test_doctor_fails_when_the_sandbox_cannot_read_it(tokens, monkeypatch):
    _, ingest = tokens
    api_token.ensure_ingest_token(ingest)
    monkeypatch.setattr(api_token, "codex_sandbox_accounts", lambda: ["CodexSandboxOffline"])
    monkeypatch.setattr(api_token, "readable_by", lambda path, accounts: [])
    report = _report_with_codex_covered()
    doctor._check_codex_sandbox(report)
    [finding] = _codex_findings(report)
    assert finding.severity == "fail" and "CodexSandboxOffline" in finding.message


def test_doctor_is_ok_once_the_sandbox_can_read_it(tokens, monkeypatch):
    _, ingest = tokens
    api_token.ensure_ingest_token(ingest)
    monkeypatch.setattr(api_token, "codex_sandbox_accounts", lambda: ["CodexSandboxOffline"])
    monkeypatch.setattr(api_token, "readable_by", lambda path, accounts: list(accounts))
    report = _report_with_codex_covered()
    doctor._check_codex_sandbox(report)
    [finding] = _codex_findings(report)
    assert finding.severity == "ok"


def test_doctor_says_nothing_where_codex_is_not_recorded(tokens, monkeypatch):
    monkeypatch.setattr(api_token, "codex_sandbox_accounts", lambda: pytest.fail("checked accounts needlessly"))
    report = doctor.DoctorReport()
    report.hooks = {"codex": hook_coverage.UNCOVERED}
    doctor._check_codex_sandbox(report)
    assert _codex_findings(report) == []
