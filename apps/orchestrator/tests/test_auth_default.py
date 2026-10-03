"""Authentication is on by default (pilot hardening items 8 and 13).

The API used to skip authentication unless AGENTMETRY_API_KEY was set, which on
a default install was always, and `doctor` called that "[OK] loopback only (no
API key needed)". Every local process, and any page that got a request
through, could read the trail, export the evidence pack, inject events and
close detections. The dashboard, when a key was set, carried it in its
JavaScript bundle.

conftest.py turns authentication off for the rest of the suite, so the
existing tests keep their meaning. Everything here turns it back on.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from agentmetry.core import api_token
from agentmetry.core.config import settings
from agentmetry.core.dashboard_session import CSRF_HEADER, SESSION_COOKIE, sessions

_DISPOSITION_URL = "/api/v1/audit/detections/disposition"
_LINK_URL = "/api/v1/auth/dashboard-link"


@pytest.fixture
def token_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "data" / "api-token"
    monkeypatch.setenv("AGENTMETRY_API_TOKEN_FILE", str(path))
    for name in ("AGENTMETRY_AUTH_DISABLED", "AGENTMETRY_API_KEY", "BLACKBOX_API_KEY", "AGENTMETRY_TOKEN_SHARED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "api_key", "")
    sessions.clear()
    yield path
    sessions.clear()


@pytest.fixture
def client(token_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "audit_db_path", tmp_path / "audit.db")
    monkeypatch.setattr(settings, "audit_export_path", tmp_path / "trail.jsonl")
    monkeypatch.setattr(settings, "detection_disposition_db_path", tmp_path / "disp.db")
    monkeypatch.setattr(settings, "audit_export_enabled", True)

    from agentmetry.core.audit.detection.disposition import reset_disposition_store
    from agentmetry.core.audit.trail_db import reset_trail_db

    reset_trail_db()
    reset_disposition_store()
    from agentmetry.api.main import app

    with TestClient(app) as test_client:
        yield test_client
    reset_trail_db()
    reset_disposition_store()


def _token(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _sign_in(client: TestClient, token: str, operator: str = "alex") -> None:
    resp = client.post(_LINK_URL, json={"operator": operator}, headers={"X-API-Key": token})
    assert resp.status_code == 200, resp.text
    signed = client.get(resp.json()["url"], follow_redirects=False)
    assert signed.status_code == 303


# --- the token ---------------------------------------------------------------


def test_the_first_start_creates_a_token(client: TestClient, token_file: Path):
    assert token_file.is_file(), "the lifespan must create the token before any hook asks"
    assert len(_token(token_file)) >= 32


def test_the_token_is_owner_only(client: TestClient, token_file: Path):
    if os.name != "nt":
        assert token_file.stat().st_mode & 0o077 == 0
    assert api_token.is_private(token_file) is not False


def test_an_existing_token_is_kept(token_file: Path):
    first = api_token.ensure_token()
    assert api_token.ensure_token() == first, "a restart must not invalidate every hook's token"


def test_a_shared_install_skips_the_owner_only_acl(token_file: Path, monkeypatch: pytest.MonkeyPatch):
    """The MSI service creates it; each developer's hook must be able to read it."""
    monkeypatch.setenv("AGENTMETRY_TOKEN_SHARED", "1")
    api_token.ensure_token()
    assert api_token.is_private(token_file) is None


# --- every route but health --------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/audit/tail"),
        ("GET", "/api/v1/audit/status"),
        ("GET", "/api/v1/audit/stats"),
        ("GET", "/api/v1/audit/export/evidence"),
        ("POST", "/api/v1/audit/ingest"),
        ("POST", _DISPOSITION_URL),
        ("POST", _LINK_URL),
    ],
)
def test_no_token_is_a_401(client: TestClient, method: str, path: str):
    assert client.request(method, path, json={}).status_code == 401


def test_every_route_in_the_schema_refuses_an_anonymous_caller(client: TestClient):
    """A route added later without the dependency fails here, not in a pilot."""
    import re

    from agentmetry.api.main import app

    public = {("GET", "/api/v1/health"), ("POST", "/api/v1/auth/logout")}
    for path, ops in app.openapi()["paths"].items():
        concrete = re.sub(r"\{[^}]+\}", "x", path)
        for method in ops:
            key = (method.upper(), path)
            status = client.request(method.upper(), concrete, json={}, follow_redirects=False).status_code
            if key in public:
                continue
            assert status == 401, f"{key} answered {status} with no credentials"


def test_health_stays_public(client: TestClient):
    assert client.get("/api/v1/health").status_code == 200


def test_the_token_is_accepted_as_a_header_or_a_bearer(client: TestClient, token_file: Path):
    token = _token(token_file)
    assert client.get("/api/v1/audit/tail", headers={"X-API-Key": token}).status_code == 200
    assert client.get("/api/v1/audit/tail", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_a_wrong_token_is_a_401(client: TestClient):
    assert client.get("/api/v1/audit/tail", headers={"X-API-Key": "guess"}).status_code == 401


def test_a_configured_key_wins_over_the_file(client: TestClient, token_file: Path, monkeypatch):
    """A fleet that distributes its own key must not also accept a local file."""
    file_token = _token(token_file)
    monkeypatch.setattr(settings, "api_key", "fleet-key")
    assert client.get("/api/v1/audit/tail", headers={"X-API-Key": file_token}).status_code == 401
    assert client.get("/api/v1/audit/tail", headers={"X-API-Key": "fleet-key"}).status_code == 200


def test_the_development_override_opens_the_api(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", True)
    assert client.get("/api/v1/audit/tail").status_code == 200


# --- WebSocket ---------------------------------------------------------------


def test_a_websocket_without_a_token_is_refused(client: TestClient):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/global") as ws:
            ws.receive_text()
    assert exc.value.code == 4401


def test_a_websocket_with_the_token_connects(client: TestClient, token_file: Path):
    with client.websocket_connect(f"/ws/global?token={_token(token_file)}"):
        pass


def test_a_dashboard_session_opens_a_websocket_from_a_loopback_page(client: TestClient, token_file: Path):
    _sign_in(client, _token(token_file))
    with client.websocket_connect("/ws/global", headers={"origin": "http://127.0.0.1:8000"}):
        pass


def test_a_foreign_page_cannot_ride_the_session_cookie_onto_a_websocket(client: TestClient, token_file: Path):
    from starlette.websockets import WebSocketDisconnect

    _sign_in(client, _token(token_file))
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/global", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_text()


# --- the dashboard sign-in ---------------------------------------------------


def test_the_sign_in_link_sets_an_httponly_strict_cookie(client: TestClient, token_file: Path):
    resp = client.post(_LINK_URL, json={"operator": "alex"}, headers={"X-API-Key": _token(token_file)})
    assert resp.json()["url"].startswith("/api/v1/auth/dashboard?code=")
    signed = client.get(resp.json()["url"], follow_redirects=False)
    cookie = signed.headers["set-cookie"].lower()
    assert SESSION_COOKIE in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert signed.headers["location"] == "/"


def test_a_sign_in_link_works_once(client: TestClient, token_file: Path):
    url = client.post(_LINK_URL, json={}, headers={"X-API-Key": _token(token_file)}).json()["url"]
    assert client.get(url, follow_redirects=False).status_code == 303
    assert client.get(url, follow_redirects=False).status_code == 401


def test_the_session_reads_without_the_token(client: TestClient, token_file: Path):
    _sign_in(client, _token(token_file))
    assert client.get("/api/v1/audit/tail").status_code == 200


def test_a_session_write_needs_the_csrf_header(client: TestClient, token_file: Path):
    _sign_in(client, _token(token_file))
    body = {"correlation_id": "s1", "rule_id": "credential-exfil", "status": "acknowledged"}
    assert client.post(_DISPOSITION_URL, json=body).status_code == 403


def test_a_dashboard_decision_is_recorded_under_the_signed_in_operator(client: TestClient, token_file: Path):
    """The body can claim anyone; the session says who it is."""
    _sign_in(client, _token(token_file), operator="alex")
    resp = client.post(
        _DISPOSITION_URL,
        json={"correlation_id": "s1", "rule_id": "credential-exfil", "status": "acknowledged", "decided_by": "mallory"},
        headers={CSRF_HEADER: "1"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["disposition"]["decided_by"] == "alex"


def test_a_token_caller_with_no_name_is_recorded_as_the_resolved_operator(client: TestClient, token_file: Path):
    from agentmetry.core.audit.run_context import resolve_operator

    resp = client.post(
        _DISPOSITION_URL,
        json={"correlation_id": "s1", "rule_id": "credential-exfil", "status": "acknowledged"},
        headers={"X-API-Key": _token(token_file)},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["disposition"]["decided_by"] == resolve_operator()[0]


def test_a_session_cannot_mint_more_sign_in_links(client: TestClient, token_file: Path):
    _sign_in(client, _token(token_file))
    assert client.post(_LINK_URL, json={}, headers={CSRF_HEADER: "1"}).status_code == 403


def test_logout_ends_the_session(client: TestClient, token_file: Path):
    _sign_in(client, _token(token_file))
    client.post("/api/v1/auth/logout", follow_redirects=False)
    client.cookies.clear()
    assert client.get("/api/v1/audit/tail").status_code == 401


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("", "/"),
        ("/detections", "/detections"),
        ("http://localhost:3000/", "http://localhost:3000/"),
        ("https://evil.example/", "/"),
        ("//evil.example/", "/"),
        ("javascript:alert(1)", "/"),
    ],
)
def test_the_landing_page_cannot_be_an_open_redirect(target: str, expected: str):
    from agentmetry.api.routes.auth import _safe_next

    assert _safe_next(target) == expected


# --- extensions --------------------------------------------------------------


def _bare_request(principal=None) -> Request:
    scope = {"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b"", "state": {}}
    request = Request(scope)
    if principal is not None:
        request.state.principal = principal
    return request


async def test_a_principal_an_extension_authenticated_is_not_rechecked(token_file: Path):
    """Enterprise per-host tokens are not the core key; refusing them breaks every enterprise caller."""
    from agentmetry.core.auth import require_api_key

    request = _bare_request(SimpleNamespace(operator_id="ops@example.eu"))
    await require_api_key(request, api_key=None)
    assert request.state.auth == ("extension", "ops@example.eu")


async def test_without_a_principal_the_core_still_refuses(token_file: Path):
    from fastapi import HTTPException

    from agentmetry.core.auth import require_api_key

    with pytest.raises(HTTPException) as exc:
        await require_api_key(_bare_request(), api_key=None)
    assert exc.value.status_code == 401


# --- the clients read the file -----------------------------------------------


def test_the_hook_presents_the_token_from_the_file(token_file: Path, monkeypatch):
    from agentmetry.hooks import ingest

    monkeypatch.setattr(ingest, "_read_repo_env", lambda _key: "")
    token = api_token.ensure_token()
    assert ingest._api_key() == token


def test_the_cli_presents_the_token_from_the_file(token_file: Path):
    from agentmetry.cli import _api_headers

    token = api_token.ensure_token()
    assert _api_headers() == {"X-API-Key": token}


def test_an_explicit_key_beats_the_file_for_clients(token_file: Path, monkeypatch):
    from agentmetry.cli import _api_headers

    api_token.ensure_token()
    monkeypatch.setenv("AGENTMETRY_API_KEY", "fleet-key")
    assert _api_headers() == {"X-API-Key": "fleet-key"}


# --- doctor ------------------------------------------------------------------


def _exposure(monkeypatch, host: str):
    from agentmetry.core.diagnostics.doctor import DoctorReport, _check_exposure

    monkeypatch.setenv("AGENTMETRY_HOST", host)
    report = DoctorReport()
    _check_exposure(report)
    return {f.code: f for f in report.findings}


def test_doctor_is_ok_with_the_token_on(token_file: Path, monkeypatch):
    findings = _exposure(monkeypatch, "127.0.0.1")
    assert findings["exposure"].severity == "ok"
    assert "api_token" in findings


def test_doctor_warns_when_auth_is_disabled_on_loopback(token_file: Path, monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", True)
    finding = _exposure(monkeypatch, "127.0.0.1")["exposure"]
    assert finding.severity == "warn"
    assert "DISABLED" in finding.message


def test_doctor_fails_when_auth_is_disabled_beyond_loopback(token_file: Path, monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", True)
    assert _exposure(monkeypatch, "0.0.0.0")["exposure"].severity == "fail"
