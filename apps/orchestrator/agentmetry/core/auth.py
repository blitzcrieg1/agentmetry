"""API authentication: required by default (pilot hardening item 8).

Every route but health requires one of:

* the per-install token (`core/api_token.py`), or AGENTMETRY_API_KEY when set,
  as `X-API-Key` or `Authorization: Bearer`;
* a dashboard session cookie (`core/dashboard_session.py`), where a request
  that changes state must also carry `X-Agentmetry-Request: 1`;
* a principal an extension already authenticated (Agentmetry Enterprise's
  per-host tokens), which the core defers to rather than re-checking against
  its own key.

The API used to skip authentication whenever AGENTMETRY_API_KEY was unset,
which on a default install was always.

AGENTMETRY_AUTH_DISABLED=1 restores that for development: no token is created
or required. An AGENTMETRY_API_KEY that is explicitly set is still enforced,
because somebody configured it on purpose.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlparse

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from agentmetry.core import api_token
from agentmetry.core.config import settings
from agentmetry.core.dashboard_session import CSRF_HEADER, SESSION_COOKIE, sessions

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def auth_is_disabled() -> bool:
    return bool(getattr(settings, "auth_disabled", False)) or api_token.auth_disabled()


def effective_key() -> str:
    """The key requests must present, or empty when nothing is enforced."""
    configured = settings.api_key.strip()
    if configured:
        return configured
    if auth_is_disabled():
        return ""
    return api_token.ensure_token()


def _token_matches(token: str | None, key: str) -> bool:
    """Constant-time compare so the key can't be recovered a byte at a time.

    A plain `==` short-circuits on the first differing byte, leaking the key's
    prefix through response timing to anyone who can reach the endpoint.
    `compare_digest` runs in time independent of where the mismatch is.
    """
    return bool(key) and secrets.compare_digest(token or "", key)


def _presented_token(request: Request, header_value: str | None) -> str | None:
    if header_value:
        return header_value
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    request: Request,
    api_key: str | None = Security(_api_key_header),
) -> None:
    """Authenticate the request; record how on `request.state.auth`."""
    if getattr(request.state, "principal", None) is not None:
        # An extension authenticated this request with its own, stronger
        # credential (Enterprise per-host tokens). Re-checking it against the
        # core key would refuse every enterprise caller.
        request.state.auth = ("extension", getattr(request.state.principal, "operator_id", ""))
        return

    key = effective_key()
    if not key:
        request.state.auth = ("disabled", "")
        return

    if _token_matches(_presented_token(request, api_key), key):
        request.state.auth = ("token", "")
        return

    operator = sessions.operator(request.cookies.get(SESSION_COOKIE))
    if operator is not None:
        if request.method.upper() not in _SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
            raise HTTPException(status_code=403, detail="dashboard writes need the X-Agentmetry-Request header")
        request.state.auth = ("session", operator)
        return

    raise HTTPException(status_code=401, detail="Invalid or missing API key")


def verify_ws_token(query_token: str | None, request: Request) -> bool:
    """Authenticate a WebSocket: token in the query or headers, or a dashboard session."""
    if getattr(request.state, "principal", None) is not None:
        return True
    key = effective_key()
    if not key:
        return True
    token = query_token or request.headers.get("X-API-Key") or _presented_token(request, None)
    if _token_matches(token, key):
        return True
    if sessions.operator(request.cookies.get(SESSION_COOKIE)) is None:
        return False
    # A cookie rides along on any WebSocket the browser opens, so the page
    # opening it must be one of ours: loopback origins only.
    return urlparse(request.headers.get("origin", "")).hostname in ("localhost", "127.0.0.1", "::1")
