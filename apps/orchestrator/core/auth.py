"""Optional API key authentication for mutating endpoints."""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from core.config import settings


def _token_matches(token: str | None) -> bool:
    """Constant-time compare so the key can't be recovered a byte at a time.

    A plain `==` short-circuits on the first differing byte, leaking the shared
    key's prefix through response timing to anyone who can reach the endpoint.
    `compare_digest` runs in time independent of where the mismatch is.
    """
    return secrets.compare_digest(token or "", settings.api_key)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    request: Request,
    api_key: str | None = Security(_api_key_header),
) -> None:
    """Skip auth when AGENTMETRY_API_KEY is unset (local dev)."""
    if not settings.api_key:
        return

    token = api_key
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()

    if not _token_matches(token):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def verify_ws_token(query_token: str | None, request: Request) -> bool:
    """Validate WebSocket connection when AGENTMETRY_API_KEY is set."""
    if not settings.api_key:
        return True
    token = query_token
    if not token:
        token = request.headers.get("X-API-Key")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    return _token_matches(token)
