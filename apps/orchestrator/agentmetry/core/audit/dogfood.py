"""Four green weeks: is the recorder actually being used, and answered?

The beta gate is four consecutive green dogfood weeks. It has never started, and
the reason is worth naming: there was no way to answer "was this week green?"
short of a twenty-minute manual checklist, so it never got asked.

A week is green on four counts, and each one exists because its absence is a
failure that looks like success:

* **Capture continuity.** Silence is indistinguishable from a quiet week. A
  recorder that was switched off produces exactly the same empty trail as a
  developer on holiday, and only the calendar knows which. Active days are
  counted so a gap has to be explained rather than assumed benign.
* **Chain integrity.** A trail that no longer verifies is not evidence.
* **Triage.** Detections raised and never answered mean the loop is running open.
  This is the count that separates a product being *used* from one merely being
  *installed*.
* **No spool backlog.** A spool that keeps growing means the orchestrator is not
  coming up, and the operator is looking at a healthy trail that is quietly
  missing sessions.

The verdict is deliberately harsh about capture gaps and deliberately lenient
about volume. A slow week is fine. A week the recorder missed is not.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

#: A working week, not seven days. Nobody should fail the gate for resting.
MIN_ACTIVE_DAYS = 3

#: Severities that must not be left unanswered.
MUST_TRIAGE = frozenset({"critical", "high"})

MARKER_NAME = "dogfood.json"


def marker_path() -> Path:
    from agentmetry.core.config import settings

    return Path(settings.audit_db_path).parent / MARKER_NAME


def read_marker() -> dict[str, Any] | None:
    path = marker_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# Files whose contents define what a detection means. A change to any of them
# changes what the gate is measuring, which is why the fingerprint covers whole
# sources rather than just the rule id list: today's two fixes changed severities
# and trait classification without adding or removing a single rule.
_RULESET_SOURCES = (
    "core/audit/detection/rules.py",
    "core/audit/detection/traits.py",
    "core/audit/detection/engine.py",
    "core/audit/mitre.py",
)


def _package_root() -> Path:
    """The `agentmetry` package directory. Fingerprinted paths are relative to it."""
    return Path(__file__).resolve().parents[2]


def ruleset_fingerprint() -> str:
    """A hash of everything that decides whether a detection fires, and how hard.

    The gate exists to produce a number worth quoting. Four green weeks measured
    against four different rulesets is not that number, and nothing was stopping
    it: three detection changes shipped into week one on the day the clock
    started, each one an improvement, and collectively they made the week
    meaningless.

    A promise to freeze the rules is the same kind of promise as an install
    command nobody runs. This makes the freeze checkable.

    Whole-file hashing is deliberately blunt. It flags a comment-only edit as a
    change, which is a small annoyance, and it cannot miss a real one, which is
    the point. Being told to look is cheap; a silently invalidated month is not.
    """
    digest = hashlib.sha256()
    root = _package_root()
    for rel in _RULESET_SOURCES:
        path = root / rel
        digest.update(rel.encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<unreadable>")

    # The YAML rules are ruleset too, and they are the half an operator is most
    # likely to edit without thinking of it as changing the product.
    try:
        from agentmetry.core.config import settings

        manifest = Path(settings.detection_rules_path)
        digest.update(b"detection-manifest")
        digest.update(manifest.read_bytes() if manifest.is_file() else b"<absent>")
    except Exception:
        digest.update(b"<manifest-unavailable>")

    return digest.hexdigest()


def start_clock(when: date | None = None, *, operator: str = "") -> dict[str, Any]:
    """Record the start of the dogfood period.

    Deliberately an explicit act rather than inferred from the first event. The
    gate is a commitment to watch for four weeks, and a commitment nobody made
    on a particular day is one nobody is keeping.

    The ruleset fingerprint is recorded here so the commitment includes what was
    being measured, not just when the measuring began.
    """
    marker = {
        "started_utc": (when or datetime.now(timezone.utc).date()).isoformat(),
        "operator": operator,
        "ruleset_fingerprint": ruleset_fingerprint(),
        "note": "Four consecutive green weeks. See core/audit/dogfood.py for what green means.",
    }
    path = marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
    return marker


@dataclass
class Week:
    index: int
    start: date
    end: date
    events: int = 0
    active_days: int = 0
    sessions: int = 0
    detections: int = 0
    untriaged: int = 0
    reasons: list[str] = field(default_factory=list)
    complete: bool = True

    @property
    def green(self) -> bool:
        return not self.reasons

    @property
    def verdict(self) -> str:
        if not self.complete:
            return "IN PROGRESS"
        return "GREEN" if self.green else "RED"


@dataclass
class DogfoodReport:
    started: date | None
    weeks: list[Week] = field(default_factory=list)
    chain_ok: bool = True
    chain_message: str = ""
    spooled: int = 0
    # False when the detection rules have changed since the clock started, which
    # means the weeks measured different products and cannot be added together.
    ruleset_frozen: bool = True

    @property
    def consecutive_green(self) -> int:
        """Green weeks in an unbroken run ending at the most recent complete week."""
        run = 0
        for week in self.weeks:
            if not week.complete:
                continue
            if week.green:
                run += 1
            else:
                run = 0
        return run

    @property
    def passed(self) -> bool:
        # A changed ruleset does not turn individual weeks red, because the
        # operator's behaviour that week was real and worth recording. It does
        # stop the run adding up to a pass, because four weeks measured against
        # four different rulesets is not four weeks of evidence about one
        # product.
        return self.consecutive_green >= 4 and self.ruleset_frozen

    def as_dict(self) -> dict[str, Any]:
        return {
            "started": self.started.isoformat() if self.started else None,
            "consecutive_green": self.consecutive_green,
            "required": 4,
            "passed": self.passed,
            "chain_ok": self.chain_ok,
            "chain_message": self.chain_message,
            "spooled": self.spooled,
            "ruleset_frozen": self.ruleset_frozen,
            "weeks": [
                {
                    "index": w.index,
                    "start": w.start.isoformat(),
                    "end": w.end.isoformat(),
                    "events": w.events,
                    "active_days": w.active_days,
                    "sessions": w.sessions,
                    "detections": w.detections,
                    "untriaged": w.untriaged,
                    "complete": w.complete,
                    "verdict": w.verdict,
                    "reasons": w.reasons,
                }
                for w in self.weeks
            ],
        }


def _week_bounds(start: date, index: int) -> tuple[date, date]:
    begin = start + timedelta(days=7 * index)
    return begin, begin + timedelta(days=6)


def assess(
    *,
    trail_db: Any | None = None,
    started: date | None = None,
    today: date | None = None,
) -> DogfoodReport:
    """Score every week since the clock started."""
    from agentmetry.core.audit.detection.disposition import get_disposition_store

    if trail_db is None:
        from agentmetry.core.audit.trail_db import get_trail_db

        trail_db = get_trail_db()

    marker = read_marker()
    if started is None and marker:
        started = date.fromisoformat(marker["started_utc"])

    report = DogfoodReport(started=started)
    # A marker written before fingerprints existed has nothing to compare, and
    # assuming it drifted would be inventing a failure. Absence is not evidence.
    recorded = (marker or {}).get("ruleset_fingerprint")
    if recorded:
        report.ruleset_frozen = recorded == ruleset_fingerprint()
    _attach_health(report)
    if started is None:
        return report

    now = today or datetime.now(timezone.utc).date()
    events = trail_db.read_between(
        datetime.combine(started, datetime.min.time(), timezone.utc).isoformat(),
        datetime.combine(now + timedelta(days=1), datetime.min.time(), timezone.utc).isoformat(),
    )

    store = get_disposition_store()
    total_weeks = max(1, ((now - started).days // 7) + 1)

    for index in range(total_weeks):
        begin, end = _week_bounds(started, index)
        week = Week(index=index + 1, start=begin, end=end, complete=end < now)

        days: set[str] = set()
        sessions: set[str] = set()
        for event in events:
            stamp = str(event.get("timestamp_utc") or "")[:10]
            if not stamp or not (begin.isoformat() <= stamp <= end.isoformat()):
                continue
            week.events += 1
            days.add(stamp)
            if event.get("correlation_id"):
                sessions.add(str(event["correlation_id"]))

            action = event.get("action") or {}
            if action.get("type") != "detection":
                continue
            detection = event.get("detection") or {}
            week.detections += 1
            if str(action.get("outcome") or "").lower() not in MUST_TRIAGE:
                continue
            current = store.get(
                str(event.get("correlation_id") or ""),
                str(detection.get("rule_id") or ""),
            )
            if current is None or current["status"] == "new":
                week.untriaged += 1

        week.active_days = len(days)
        week.sessions = len(sessions)

        if week.complete:
            if week.active_days < MIN_ACTIVE_DAYS:
                week.reasons.append(
                    f"only {week.active_days} active day(s); the recorder was not "
                    "running, or was not being used"
                )
            if week.untriaged:
                week.reasons.append(
                    f"{week.untriaged} critical/high detection(s) never dispositioned"
                )
        report.weeks.append(week)

    if not report.chain_ok:
        for week in report.weeks:
            week.reasons.append("trail chain does not verify")
    if report.spooled:
        for week in report.weeks[-1:]:
            week.reasons.append(
                f"{report.spooled} event(s) stuck in the hook spool; the "
                "orchestrator is not draining them"
            )
    return report


def _attach_health(report: DogfoodReport) -> None:
    from agentmetry.core.config import settings

    trail = Path(settings.audit_export_path)
    if trail.is_file():
        from agentmetry.core.audit.trail_chain import verify_trail_file

        result = verify_trail_file(trail)
        report.chain_ok = result.ok
        report.chain_message = result.message
    else:
        # No trail file is not a broken chain. On day one there is nothing to
        # verify, and failing the gate for that would make the first week
        # unpassable by construction. A week with no events is already caught by
        # the active-days check, which is the honest place for it.
        report.chain_ok = True
        report.chain_message = "no trail file yet"

    try:
        from agentmetry.core.audit.spool import read_spool, spool_path

        path = spool_path()
        if path.is_file():
            payloads, _dropped = read_spool(path)
            report.spooled = len(payloads)
    except Exception:
        report.spooled = 0


def render(report: DogfoodReport) -> str:
    if report.started is None:
        return (
            "Dogfood clock has not started.\n\n"
            "  Start it with:  agentmetry dogfood --start\n\n"
            "  Four consecutive green weeks is the beta gate. A week is green when\n"
            "  the recorder ran on at least three days, the trail chain verifies,\n"
            "  every critical or high detection was dispositioned, and no events\n"
            "  are stuck in the hook spool.\n"
        )

    lines = [
        f"Dogfood clock started {report.started.isoformat()}",
        "",
        f"  {'Week':<6}{'Dates':<26}{'Days':>5}{'Events':>9}{'Sessions':>10}"
        f"{'Detect':>8}{'Untriaged':>11}  Verdict",
    ]
    for week in report.weeks:
        lines.append(
            f"  {week.index:<6}"
            f"{week.start.isoformat()} to {week.end.isoformat():<7}"
            f"{week.active_days:>5}{week.events:>9}{week.sessions:>10}"
            f"{week.detections:>8}{week.untriaged:>11}  {week.verdict}"
        )
        for reason in week.reasons:
            lines.append(f"         - {reason}")

    lines += ["", f"  Consecutive green weeks: {report.consecutive_green} of 4"]
    if report.passed:
        lines.append("  Gate PASSED.")
    else:
        remaining = 4 - report.consecutive_green
        lines.append(f"  {remaining} more green week(s) needed.")

    if not report.ruleset_frozen:
        lines += [
            "",
            "  RULESET CHANGED since the clock started, so these weeks did not all",
            "  measure the same product and the run cannot pass. Land rule changes",
            "  and restart the clock: agentmetry dogfood --start --restart",
        ]

    if not report.chain_ok:
        lines.append(f"  Trail chain: BROKEN - {report.chain_message}")
    if report.spooled:
        lines.append(f"  Spool backlog: {report.spooled} event(s) pending replay")
    return "\n".join(lines) + "\n"
