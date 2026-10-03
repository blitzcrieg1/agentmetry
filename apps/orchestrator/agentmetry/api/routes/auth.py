"""Dashboard sign-in (pilot hardening items 8 and 13).

`agentmetry dashboard` calls POST /auth/dashboard-link with the API token and
opens the URL it returns. That URL exchanges a one-time code for an HttpOnly,
SameSite=Strict session cookie, so the browser is signed in without ever
holding the key.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from agentmetry.core.auth import require_api_key
from agentmetry.core.dashboard_session import (
    CODE_SECONDS,
    SESSION_COOKIE,
    SESSION_SECONDS,
    sessions,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_LOOPBACK = ("localhost", "127.0.0.1", "::1")


class DashboardLinkBody(BaseModel):
    operator: str = ""


#: A same-origin path: no backslash, no second leading slash, no percent
#: escapes. Browsers read `/\evil.example` as `//evil.example`, which is why a
#: "starts with one slash" check was an open redirect.
_SAFE_PATH = re.compile(r"/(?:[A-Za-z0-9._~-][A-Za-z0-9._~/-]*)?")
_SAFE_QUERY = re.compile(r"[A-Za-z0-9._~=&+-]*")


def _safe_next(target: str) -> str:
    """Where to land after sign-in: this origin, or a loopback dev server.

    Anything else would turn the sign-in link into an open redirect. The
    result is rebuilt from validated parts, never passed through: the host
    comes from this module's own loopback list and the port is an integer.
    """
    try:
        parsed = urlsplit(target or "")
        port = parsed.port
    except ValueError:
        return "/"
    path = parsed.path or "/"
    if not _SAFE_PATH.fullmatch(path) or not _SAFE_QUERY.fullmatch(parsed.query) or parsed.fragment:
        return "/"
    suffix = path + (f"?{parsed.query}" if parsed.query else "")
    if not parsed.scheme and not parsed.netloc:
        return suffix
    host = next((h for h in _LOOPBACK if h == parsed.hostname), None)
    if parsed.scheme not in ("http", "https") or host is None or parsed.username or parsed.password:
        return "/"
    scheme = "https" if parsed.scheme == "https" else "http"
    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority += f":{int(port)}"
    return f"{scheme}://{authority}{suffix}"


@router.post("/dashboard-link")
async def dashboard_link(body: DashboardLinkBody, request: Request, _: None = Depends(require_api_key)):
    """A one-time sign-in link. Needs the token itself, not a session."""
    kind, _who = getattr(request.state, "auth", ("", ""))
    if kind == "session":
        raise HTTPException(status_code=403, detail="a dashboard session cannot mint sign-in links")
    if not body.operator.strip():
        from agentmetry.core.audit.run_context import resolve_operator

        operator = resolve_operator()[0]
    else:
        operator = body.operator.strip()
    code = sessions.issue_code(operator)
    return {"url": f"/api/v1/auth/dashboard?code={code}", "expires_in": CODE_SECONDS}


@router.get("/dashboard")
async def dashboard_sign_in(request: Request, code: str = "", next: str = ""):  # noqa: A002
    session_id = sessions.redeem(code)
    if session_id is None:
        raise HTTPException(status_code=401, detail="sign-in link expired or already used; run `agentmetry dashboard`")
    resp = RedirectResponse(_safe_next(next), status_code=303)
    resp.set_cookie(
        SESSION_COOKIE, session_id, max_age=SESSION_SECONDS, httponly=True,
        samesite="strict", secure=request.url.scheme == "https", path="/",
    )
    return resp


@router.post("/logout")
async def dashboard_logout(request: Request):
    sessions.revoke(request.cookies.get(SESSION_COOKIE))
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp
