"""Optional API key authentication for mutating endpoints."""

from __future__ import annotations

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from core.config import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    request: Request,
    api_key: str | None = Security(_api_key_header),
) -> None:
    """Skip auth when BLACKBOX_API_KEY is unset (local dev)."""
    if not settings.api_key:
        return

    token = api_key
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()

    if token != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def verify_ws_token(query_token: str | None, request: Request) -> bool:
    """Validate WebSocket connection when BLACKBOX_API_KEY is set."""
    if not settings.api_key:
        return True
    token = query_token
    if not token:
        token = request.headers.get("X-API-Key")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    return token == settings.api_key
