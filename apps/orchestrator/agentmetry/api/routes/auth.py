"""Dashboard sign-in (pilot hardening items 8 and 13).

`agentmetry dashboard` calls POST /auth/dashboard-link with the API token and
opens the URL it returns. That URL exchanges a one-time code for an HttpOnly,
SameSite=Strict session cookie, so the browser is signed in without ever
holding the key.
"""

from __future__ import annotations

from urllib.parse import urlparse

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


def _safe_next(target: str) -> str:
    """Where to land after sign-in: this origin, or a loopback dev server.

    Anything else would turn the sign-in link into an open redirect.
    """
    if not target:
        return "/"
    if target.startswith("/") and not target.startswith("//"):
        return target
    parsed = urlparse(target)
    if parsed.scheme in ("http", "https") and parsed.hostname in _LOOPBACK:
        return target
    return "/"


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
