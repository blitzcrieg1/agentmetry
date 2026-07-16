"""Agentmetry recorder for OpenSRE.

Records every tool an SRE agent executes into the local Agentmetry trail. An SRE
agent runs against live infrastructure during an incident, with real
credentials, usually unattended and usually at the worst possible moment. That
is exactly the case where you want a flight recorder.

Usage: OpenSRE's Agent takes an ``on_runtime_event`` callback, so this is a
one-line wire-up.

    from agentmetry_opensre import AgentmetryRecorder

    agent = Agent(
        llm=...,
        tools=[...],
        on_runtime_event=AgentmetryRecorder(),
    )

If you already pass an ``on_runtime_event``, chain it:

    recorder = AgentmetryRecorder(chain_to=my_existing_callback)

Each agent run becomes one correlation_id, so sequence rules fire across the
whole incident-response run rather than a single tool call.

Config (env):
    AGENTMETRY_AUDIT_INGEST_URL     default http://127.0.0.1:8000
    AGENTMETRY_API_KEY              optional, sent as X-API-Key
    AGENTMETRY_OPENSRE_LOG_ARGS     1 = send tool args as evidence (see below)

Tool arguments are hashed and not transmitted by default. Set
AGENTMETRY_OPENSRE_LOG_ARGS=1 to send them, which enables content-based
detection (a read of ~/.aws/credentials upgrading to Credential Access
T1552.001) and DLP scanning. Secret-looking values are scrubbed either way.

Requires: opensre (core.events). Apache-2.0.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

_SOURCE_APP = "opensre"
_DEFAULT_URL = "http://127.0.0.1:8000"

_SECRET_MARKERS = ("authorization", "api_key", "apikey", "password", "secret", "token", "credential")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _ingest_url() -> str:
    base = os.environ.get("AGENTMETRY_AUDIT_INGEST_URL", _DEFAULT_URL).rstrip("/")
    return f"{base}/api/v1/audit/ingest"


def _scrub(value: Any) -> Any:
    """Mask obviously-secret values before anything leaves this process."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if any(m in str(k).lower() for m in _SECRET_MARKERS):
                out[k] = "***"
            else:
                out[k] = _scrub(v)
        return out
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, str) and value.lower().startswith("bearer "):
        return "Bearer ***"
    return value


def _hash_args(args: Any) -> str:
    try:
        canonical = json.dumps(args, sort_keys=True, default=str)
    except (TypeError, ValueError):
        canonical = str(args)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AgentmetryRecorder:
    """An OpenSRE ``RuntimeEventCallback`` that mirrors tool activity to Agentmetry.

    Duck-typed against ``core.events`` rather than importing it: OpenSRE events
    are frozen dataclasses with a ``type`` discriminator, so matching on that
    keeps this file droppable into a project without importing OpenSRE
    internals, and keeps it working if the union grows.

    Failures are swallowed by design. An audit sink that can crash the agent it
    observes, mid-incident, is worse than no audit sink.
    """

    def __init__(
        self,
        *,
        ingest_url: str | None = None,
        chain_to: Callable[[Any], None] | None = None,
        quiet: bool = False,
    ) -> None:
        self._url = ingest_url or _ingest_url()
        self._chain_to = chain_to
        self._quiet = quiet
        self._api_key = os.environ.get("AGENTMETRY_API_KEY", "").strip()
        self._log_args = _truthy("AGENTMETRY_OPENSRE_LOG_ARGS")
        self._correlation_id = f"sre-{uuid.uuid4().hex[:12]}"
        self._warned = False

    # --- transport ---------------------------------------------------------

    def _post(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        request = urllib.request.Request(self._url, data=body, headers=headers)
        try:
            urllib.request.urlopen(request, timeout=3).read()
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            if not self._warned and not self._quiet:
                self._warned = True
                print(
                    f"[agentmetry] audit sink unreachable at {self._url} ({exc}). "
                    "The agent continues; events for this run are not being recorded.",
                    file=sys.stderr,
                )

    def _emit(self, event_type: str, **extra: Any) -> None:
        payload: dict[str, Any] = {
            "source_app": _SOURCE_APP,
            "event_type": event_type,
            "correlation_id": self._correlation_id,
            "session_id": self._correlation_id,
            "timestamp_utc": _utc_now(),
            "adapter": "opensre_recorder",
            # An SRE agent runs unattended, which is what the detection engine
            # keys on for autonomous-unapproved-write.
            "triggered_by": "opensre",
        }
        payload.update(extra)
        self._post(payload)

    def _tool_payload(self, event: Any) -> dict[str, Any]:
        raw_args = getattr(event, "args", {}) or {}
        args = _scrub(raw_args if isinstance(raw_args, dict) else {"input": raw_args})
        tool_name = str(getattr(event, "tool_name", "") or "unknown")
        tool: dict[str, Any] = {
            "qualified": f"opensre.{tool_name}",
            "server": "opensre",
            "input_hash": _hash_args(args),
        }
        if self._log_args:
            tool["arguments"] = args
        return {"tool": tool}

    # --- the RuntimeEventCallback ------------------------------------------

    def __call__(self, event: Any) -> None:
        """OpenSRE calls this with every RuntimeEvent."""
        try:
            self._handle(event)
        except Exception as exc:  # never let auditing break the agent
            if not self._warned and not self._quiet:
                self._warned = True
                print(f"[agentmetry] recorder error, continuing: {exc}", file=sys.stderr)
        finally:
            # Stay a good citizen if the caller already had a callback.
            if self._chain_to is not None:
                self._chain_to(event)

    def _handle(self, event: Any) -> None:
        kind = getattr(event, "type", None)

        if kind == "agent_start":
            self._correlation_id = f"sre-{uuid.uuid4().hex[:12]}"
            self._emit("session_start")

        elif kind == "tool_execution_start":
            self._emit(
                "approval_request",
                outcome="pending",
                reason="opensre:tool_started",
                **self._tool_payload(event),
            )

        elif kind == "tool_execution_end":
            failed = bool(getattr(event, "is_error", False))
            self._emit(
                "tool_failed" if failed else "tool_called",
                outcome="error" if failed else "success",
                reason=(str(getattr(event, "result", ""))[:500] if failed else ""),
                **self._tool_payload(event),
            )

        elif kind == "agent_end":
            self._emit("session_end", outcome="success")
