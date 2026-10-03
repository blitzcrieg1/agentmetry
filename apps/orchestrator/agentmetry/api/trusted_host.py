"""Refuse requests whose Host header is not this machine (pilot hardening item 9).

The orchestrator listens on loopback, and that is not enough on its own. A web
page the developer visits can make its own hostname resolve to 127.0.0.1 (DNS
rebinding) and then read the local API as same-origin, trail included, because
the browser believes it is talking to the attacker's site. The one thing that
gives it away is the Host header, which still names the attacker's domain.

So only loopback names and the names an operator configures are accepted:
`localhost`, `127.0.0.1`, `::1`, plus `AGENTMETRY_TRUSTED_HOSTS`
(comma-separated, `*` to disable the check). `mobile.bat` adds the LAN address
it detects.

Written as plain ASGI rather than Starlette's TrustedHostMiddleware because
that one fixes its list at startup, and this reads settings on each request so
a test or an edited `.env` takes effect.
"""

from __future__ import annotations

from typing import Any

LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})


def allowed_hosts() -> frozenset[str]:
    from agentmetry.core.config import settings

    configured = {h.strip().lower() for h in str(getattr(settings, "trusted_hosts", "")).split(",") if h.strip()}
    return LOOPBACK | frozenset(configured)


def host_of(header: str) -> str:
    """The hostname in a Host header, without the port, lowercased."""
    value = header.strip().lower()
    if value.startswith("["):  # [::1]:8000
        end = value.find("]")
        return value[1:end] if end > 0 else value
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


class TrustedHostMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        allowed = allowed_hosts()
        if "*" in allowed:
            return await self.app(scope, receive, send)
        header = ""
        for name, value in scope.get("headers") or []:
            if name == b"host":
                header = value.decode("latin-1")
                break
        if host_of(header) in allowed:
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            message = await receive()
            if message.get("type") == "websocket.connect":
                await send({"type": "websocket.close", "code": 1008})
            return None
        body = b"Invalid host header"
        await send({
            "type": "http.response.start", "status": 400,
            "headers": [(b"content-type", b"text/plain"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})
        return None
