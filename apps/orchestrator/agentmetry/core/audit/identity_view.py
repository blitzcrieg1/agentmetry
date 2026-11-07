"""The local dashboard's Identity page: which accounts coding agents report.

Everything here is a client claim read back from the trail. It says what an
agent reported, not who was at the keyboard, and an agent that reports nothing
is shown as unknown so that a blank never reads as clean.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from agentmetry.core.audit.personal_domains import account_kind

#: Sources that are not coding agents, so they say nothing about coverage.
_NOT_AGENTS = frozenset({"", "agentmetry", "unknown"})

#: Agents whose documented hook input has no account field. Reporting nothing is
#: expected for these, which is a different thing from one that should report.
_NO_DOCUMENTED_FIELD = frozenset({"copilot"})

_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}

_MAX_DETECTIONS_PER_ACCOUNT = 20
_MAX_ROWS = 200_000


def _account_key(domain: str, organization_id: str, account_id: str, user_id: str) -> tuple[str, ...]:
    """One row per domain. Only an account with no domain groups on its IDs."""
    if domain:
        return ("domain", domain)
    if organization_id:
        return ("organization", organization_id)
    return ("ids", account_id, user_id)


def _empty_account(domain: str, account_id: str, user_id: str) -> dict[str, Any]:
    return {
        "domain": domain,
        "organization_ids": set(),
        "account_id": account_id,
        "user_id": user_id,
        "emails": set(),
        "sources": set(),
        "agents": set(),
        "hosts": set(),
        "operators": set(),
        "sessions": set(),
        "events": 0,
        "detections": [],
        "first_seen": "",
        "last_seen": "",
    }


def _widen(record: dict[str, Any], timestamp: str) -> None:
    if timestamp and (not record["first_seen"] or timestamp < record["first_seen"]):
        record["first_seen"] = timestamp
    if timestamp and timestamp > record["last_seen"]:
        record["last_seen"] = timestamp


def _finish_account(record: dict[str, Any]) -> dict[str, Any]:
    detections = sorted(record["detections"], key=lambda d: d["timestamp_utc"], reverse=True)
    highest = max((d["severity"] for d in detections), key=lambda s: _SEVERITY_RANK.get(s, 0), default="")
    return {
        "kind": account_kind(record["domain"]),
        "domain": record["domain"],
        "organization_ids": sorted(record["organization_ids"]),
        "account_id": record["account_id"],
        "user_id": record["user_id"],
        "emails": sorted(record["emails"]),
        "sources": sorted(record["sources"]),
        "agents": sorted(record["agents"]),
        "hosts": sorted(record["hosts"]),
        "operators": sorted(record["operators"]),
        "sessions": len(record["sessions"]),
        "events": record["events"],
        "detection_count": len(detections),
        "highest_severity": highest,
        "detections": detections[:_MAX_DETECTIONS_PER_ACCOUNT],
        "first_seen": record["first_seen"],
        "last_seen": record["last_seen"],
    }


def _agent_state(with_account: int, last_had_account: bool, app: str) -> str:
    """Judged on the newest event, so an old gap does not outlive its cause."""
    if with_account == 0:
        return "no_documented_field" if app in _NO_DOCUMENTED_FIELD else "not_reported"
    return "reported" if last_had_account else "partial"


def build_identity_view(
    rows: Iterable[dict[str, Any]], *, days: int, truncated: bool = False
) -> dict[str, Any]:
    """Aggregate trail rows, oldest first, into accounts and agent coverage."""
    accounts: dict[tuple[str, ...], dict[str, Any]] = {}
    agents: dict[str, dict[str, Any]] = {}
    all_sessions: set[str] = set()
    sessions_with_account: set[str] = set()
    detections_without_account = 0

    for row in rows:
        app = str(row.get("source_app") or "")
        action = str(row.get("action_type") or "")
        adapter = str(row.get("adapter") or "")
        corr = str(row.get("correlation_id") or "")
        timestamp = str(row.get("timestamp_utc") or "")
        domain = str(row.get("domain") or "")
        organization_id = str(row.get("organization_id") or "")
        account_id = str(row.get("account_id") or "")
        user_id = str(row.get("user_id") or "")
        has_account = bool(domain or organization_id or account_id or user_id)
        is_detection = action == "detection"

        if app in _NOT_AGENTS and not has_account:
            continue
        # The recorder writes inferred approvals itself, so they have no account
        # to copy. Counting them would make every agent look partly unreported.
        if action == "heartbeat" or adapter.endswith("_inferred"):
            continue

        if corr:
            all_sessions.add(corr)

        if is_detection and not has_account:
            detections_without_account += 1

        if not is_detection:
            agent = agents.setdefault(
                app,
                {
                    "name": app,
                    "events": 0,
                    "events_since_first": 0,
                    "with_account": 0,
                    "last_seen": "",
                    "first_reported": "",
                    "last_had_account": False,
                },
            )
            agent["events"] += 1
            # Rows arrive oldest first, so this ends on the newest event.
            agent["last_had_account"] = has_account
            if timestamp > agent["last_seen"]:
                agent["last_seen"] = timestamp
            if has_account and not agent["first_reported"]:
                agent["first_reported"] = timestamp
            # Coverage counts from the first report, so events recorded before
            # this field existed do not read as an agent that stopped reporting.
            if agent["first_reported"]:
                agent["events_since_first"] += 1
                if has_account:
                    agent["with_account"] += 1

        if not has_account:
            continue

        if corr:
            sessions_with_account.add(corr)
        record = accounts.setdefault(
            _account_key(domain, organization_id, account_id, user_id),
            _empty_account(domain, account_id, user_id),
        )
        if organization_id:
            record["organization_ids"].add(organization_id)
        # A domain row can start from an agent that reports no IDs.
        record["account_id"] = record["account_id"] or account_id
        record["user_id"] = record["user_id"] or user_id
        record["events"] += 1
        record["agents"].add(app)
        _widen(record, timestamp)
        if corr:
            record["sessions"].add(corr)
        if row.get("account_source"):
            record["sources"].add(str(row["account_source"]))
        if row.get("host_id"):
            record["hosts"].add(str(row["host_id"]))
        if row.get("actor_id"):
            record["operators"].add(str(row["actor_id"]))
        # Only present when the operator turned on full email capture. One domain
        # can hold many people, so the row never implies they are the same one.
        if row.get("email"):
            record["emails"].add(str(row["email"]))
        if is_detection:
            record["detections"].append(
                {
                    "rule_id": str(row.get("rule_id") or ""),
                    "title": str(row.get("title") or ""),
                    "severity": str(row.get("action_outcome") or ""),
                    "correlation_id": corr,
                    "agent": app,
                    "timestamp_utc": timestamp,
                }
            )

    finished = [_finish_account(record) for record in accounts.values()]
    finished.sort(key=lambda a: (a["detection_count"], a["last_seen"]), reverse=True)
    agent_rows = [
        {
            "name": agent["name"],
            "events": agent["events"],
            "events_since_first_report": agent["events_since_first"],
            "events_with_account": agent["with_account"],
            "state": _agent_state(agent["with_account"], agent["last_had_account"], agent["name"]),
            "first_reported": agent["first_reported"],
            "last_seen": agent["last_seen"],
        }
        for agent in agents.values()
    ]
    agent_rows.sort(key=lambda a: a["name"])
    return {
        "enabled": True,
        "window_days": days,
        "truncated": truncated,
        "accounts": finished,
        "counts": {
            kind: sum(1 for account in finished if account["kind"] == kind)
            for kind in ("personal", "corporate", "unclassified")
        },
        "agents": agent_rows,
        "sessions": len(all_sessions),
        "sessions_without_account": len(all_sessions - sessions_with_account),
        "detections_without_account": detections_without_account,
    }


def identity_snapshot(days: int = 30) -> dict[str, Any]:
    """Read the trail index for the last `days` days and aggregate it."""
    from agentmetry.core.audit.trail_db import get_trail_db

    window = max(1, min(days, 90))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window)).isoformat()
    rows = get_trail_db().identity_rows(cutoff, limit=_MAX_ROWS + 1)
    truncated = len(rows) > _MAX_ROWS
    return build_identity_view(rows[:_MAX_ROWS], days=window, truncated=truncated)
