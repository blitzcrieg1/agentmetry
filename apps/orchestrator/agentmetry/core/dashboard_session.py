"""Browser sessions for the local dashboard (pilot hardening item 13).

The dashboard used to authenticate by compiling AGENTMETRY_API_KEY into its
JavaScript bundle (NEXT_PUBLIC_AGENTMETRY_API_KEY), so anyone who could load
the page, or read the static export on disk, had the key.

Now the browser never sees the key. `agentmetry dashboard`, which runs as the
user and can read the token file, asks the API for a one-time link. Opening it
exchanges the code for a session: a random id in an HttpOnly, SameSite=Strict
cookie, with only a SHA-256 of it kept here. A cookie-authenticated request
that changes state must also carry `X-Agentmetry-Request: 1`, a custom header
a cross-site form cannot send.

The session records the operator who ran `agentmetry dashboard`, and a
disposition made from the dashboard is recorded under that operator, whatever
the request body says.

Kept in memory: a restart signs the dashboard out, and `agentmetry dashboard`
signs it back in.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time

SESSION_COOKIE = "agm_dashboard"
CSRF_HEADER = "x-agentmetry-request"
CODE_SECONDS = 120
SESSION_SECONDS = 12 * 3600


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class DashboardSessions:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._codes: dict[str, tuple[str, float]] = {}
        self._sessions: dict[str, tuple[str, float]] = {}

    def issue_code(self, operator: str) -> str:
        code = secrets.token_urlsafe(24)
        with self._lock:
            self._codes[_digest(code)] = (operator, time.monotonic() + CODE_SECONDS)
        return code

    def redeem(self, code: str | None) -> str | None:
        """Exchange a one-time code for a session id. A code works once."""
        if not code:
            return None
        with self._lock:
            entry = self._codes.pop(_digest(code), None)
        if entry is None or entry[1] <= time.monotonic():
            return None
        session_id = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[_digest(session_id)] = (entry[0], time.monotonic() + SESSION_SECONDS)
        return session_id

    def operator(self, session_id: str | None) -> str | None:
        if not session_id:
            return None
        with self._lock:
            entry = self._sessions.get(_digest(session_id))
        if entry is None or entry[1] <= time.monotonic():
            return None
        return entry[0]

    def revoke(self, session_id: str | None) -> None:
        if session_id:
            with self._lock:
                self._sessions.pop(_digest(session_id), None)

    def clear(self) -> None:
        with self._lock:
            self._codes.clear()
            self._sessions.clear()


sessions = DashboardSessions()
