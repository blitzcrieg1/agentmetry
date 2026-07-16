"""Agentmetry listener for CrewAI.

Records every tool a Crew executes into the local Agentmetry trail, so a Crew
running in production leaves the same auditable record an IDE agent does: MITRE
ATT&CK tags, DLP scanning, hashed arguments, and correlated sequence detections.

Usage (one import, then instantiate once at startup):

    from agentmetry_crewai import AgentmetryListener

    agentmetry = AgentmetryListener()      # must stay referenced for its lifetime

    crew = Crew(agents=[...], tasks=[...])
    crew.kickoff()

Each Crew run becomes one correlation_id, so `credential-exfil` and friends fire
across a whole Crew rather than a single tool call.

Config (env):
    AGENTMETRY_AUDIT_INGEST_URL   default http://127.0.0.1:8000
    AGENTMETRY_API_KEY            optional, sent as X-API-Key
    AGENTMETRY_CREWAI_LOG_ARGS    1 = send tool args as evidence (see below)

By default tool arguments are hashed, never sent: the ingest API hashes what it
receives, but the safest thing is not to transmit them at all. Set
AGENTMETRY_CREWAI_LOG_ARGS=1 to send them, which is what enables content-based
detection (a read of ~/.ssh/id_rsa upgrading to Credential Access T1552.004).
Secrets are scrubbed before transmission either way.

Requires: crewai >= 1.0 (the crewai.events bus). Apache-2.0.
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
from typing import Any

try:
    from crewai.events import (  # type: ignore[import-not-found]
        BaseEventListener,
        CrewKickoffCompletedEvent,
        CrewKickoffFailedEvent,
        CrewKickoffStartedEvent,
        ToolUsageErrorEvent,
        ToolUsageFinishedEvent,
        ToolUsageStartedEvent,
    )
except ImportError as exc:  # pragma: no cover - depends on the host project
    raise ImportError(
        "agentmetry_crewai requires crewai>=1.0 with the crewai.events bus. "
        "Install it with: pip install crewai"
    ) from exc

_SOURCE_APP = "crewai"
_DEFAULT_URL = "http://127.0.0.1:8000"

# Mirrors core/audit/redaction.py. Duplicated on purpose: this file is meant to
# be droppable into a CrewAI project without installing Agentmetry itself.
_SECRET_PATTERNS = (
    ("authorization", "bearer "),
    ("api_key", ""),
    ("apikey", ""),
    ("password", ""),
    ("secret", ""),
    ("token", ""),
)


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
            lowered = str(k).lower()
            if any(marker in lowered for marker, _ in _SECRET_PATTERNS):
                out[k] = "***"
            else:
                out[k] = _scrub(v)
        return out
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, str) and value.lower().startswith("bearer "):
        return "Bearer ***"
    return value


def _args_to_dict(tool_args: Any) -> dict[str, Any]:
    if isinstance(tool_args, dict):
        return tool_args
    if isinstance(tool_args, str):
        try:
            parsed = json.loads(tool_args)
            return parsed if isinstance(parsed, dict) else {"input": tool_args}
        except (ValueError, TypeError):
            return {"input": tool_args}
    return {"input": str(tool_args)}


def _hash_args(args: dict[str, Any]) -> str:
    try:
        canonical = json.dumps(args, sort_keys=True, default=str)
    except (TypeError, ValueError):
        canonical = str(args)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AgentmetryListener(BaseEventListener):
    """Streams CrewAI tool executions to a local Agentmetry instance.

    Failures are swallowed by design. An audit sink that can crash the Crew it is
    observing is worse than no audit sink, so a dead collector degrades to a
    single stderr warning and the Crew runs on.
    """

    def __init__(self, *, ingest_url: str | None = None, quiet: bool = False) -> None:
        # Every attribute must be set BEFORE super().__init__(): CrewAI's
        # BaseEventListener.__init__ immediately calls self.setup_listeners(),
        # so anything assigned after this point does not exist yet from the
        # perspective of that call.
        self._url = ingest_url or _ingest_url()
        self._quiet = quiet
        self._api_key = os.environ.get("AGENTMETRY_API_KEY", "").strip()
        self._log_args = _truthy("AGENTMETRY_CREWAI_LOG_ARGS")
        self._correlation_id = f"crew-{uuid.uuid4().hex[:12]}"
        self._warned = False
        super().__init__()

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
                    "The Crew continues; events for this run are not being recorded.",
                    file=sys.stderr,
                )

    def _emit(self, event_type: str, **extra: Any) -> None:
        payload: dict[str, Any] = {
            "source_app": _SOURCE_APP,
            "event_type": event_type,
            "correlation_id": self._correlation_id,
            "session_id": self._correlation_id,
            "timestamp_utc": _utc_now(),
            "adapter": "crewai_listener",
            # A Crew runs unattended, which is precisely the signal the detection
            # engine keys on for autonomous-unapproved-write.
            "triggered_by": "crewai",
        }
        payload.update(extra)
        self._post(payload)

    def _tool_payload(self, event: Any) -> dict[str, Any]:
        args = _scrub(_args_to_dict(getattr(event, "tool_args", {})))
        tool_name = str(getattr(event, "tool_name", "") or "unknown")
        tool: dict[str, Any] = {
            "qualified": f"crewai.{tool_name}",
            "server": "crewai",
            "input_hash": _hash_args(args),
        }
        if self._log_args:
            # Arguments are what let MITRE upgrade a generic read to Credential
            # Access, and what the DLP engine scans. Opt-in.
            tool["arguments"] = args
        return {"tool": tool}

    # --- listener registration ---------------------------------------------

    def setup_listeners(self, crewai_event_bus: Any) -> None:  # noqa: D102
        @crewai_event_bus.on(CrewKickoffStartedEvent)
        def _on_crew_started(source: Any, event: Any) -> None:
            self._correlation_id = f"crew-{uuid.uuid4().hex[:12]}"
            self._emit(
                "session_start",
                skill_id=str(getattr(event, "crew_name", "") or "crew"),
            )

        @crewai_event_bus.on(ToolUsageStartedEvent)
        def _on_tool_started(source: Any, event: Any) -> None:
            self._emit(
                "approval_request",
                outcome="pending",
                reason="crewai:tool_started",
                **self._tool_payload(event),
            )

        @crewai_event_bus.on(ToolUsageFinishedEvent)
        def _on_tool_finished(source: Any, event: Any) -> None:
            self._emit(
                "tool_called",
                outcome="success",
                reason=str(getattr(event, "agent_role", "") or ""),
                **self._tool_payload(event),
            )

        @crewai_event_bus.on(ToolUsageErrorEvent)
        def _on_tool_error(source: Any, event: Any) -> None:
            self._emit(
                "tool_failed",
                outcome="error",
                reason=str(getattr(event, "error", ""))[:500],
                **self._tool_payload(event),
            )

        @crewai_event_bus.on(CrewKickoffCompletedEvent)
        def _on_crew_completed(source: Any, event: Any) -> None:
            self._emit("session_end", outcome="success")

        @crewai_event_bus.on(CrewKickoffFailedEvent)
        def _on_crew_failed(source: Any, event: Any) -> None:
            self._emit(
                "session_end",
                outcome="error",
                reason=str(getattr(event, "error", ""))[:500],
            )
