"""A rate limit on `POST /audit/ingest`, per source app and per session.

Ingest accepted events as fast as they arrived, so one runaway or
prompt-injected agent holding the ingest token could write without limit and
bury every other agent's events in the trail and the index (#312).

Two token buckets, one keyed by `source_app` and one by session, both have to
have room. Past either cap the route answers 429 and the hook spools the event
(it already spools on any HTTP error); the recorder's own drain replays the
spool every minute with the timestamps the hook stamped at capture. So a
legitimate burst is late by up to a minute, not lost, and the record of when
things happened is unchanged.

What this does not do, and says so: an agent running as the developer can write
the spool file directly, so the limit bounds how fast the API accepts work and
how much a flood can put through it, and makes throttling visible. It is not a
wall against the developer's own account; running the recorder under its own
account is (#313).
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone

#: Session buckets held at once. A flood that invents a fresh session id per
#: event cannot grow memory past this; the per-source bucket still caps it.
MAX_SESSION_BUCKETS = 10_000


@dataclass
class _Bucket:
    tokens: float
    stamp: float


@dataclass
class _Throttled:
    total: int = 0
    by_source: dict[str, int] = field(default_factory=dict)
    last_utc: str | None = None


class IngestLimiter:
    """Token buckets for ingest. A rate of 0 turns that bucket off."""

    def __init__(
        self,
        *,
        source_rate: float,
        source_burst: float,
        session_rate: float,
        session_burst: float,
        clock=time.monotonic,
    ) -> None:
        self._source_rate = max(0.0, source_rate)
        self._source_burst = max(1.0, source_burst)
        self._session_rate = max(0.0, session_rate)
        self._session_burst = max(1.0, session_burst)
        self._clock = clock
        self._sources: dict[str, _Bucket] = {}
        self._sessions: OrderedDict[str, _Bucket] = OrderedDict()
        self._throttled = _Throttled()
        self._lock = threading.Lock()

    def _refill(self, bucket: _Bucket, rate: float, burst: float, now: float) -> None:
        bucket.tokens = min(burst, bucket.tokens + (now - bucket.stamp) * rate)
        bucket.stamp = now

    def allow(self, source_app: str, session: str) -> bool:
        """Spend one event from both buckets, or neither. False means 429."""
        source = source_app or "unknown"
        now = self._clock()
        with self._lock:
            src = None
            if self._source_rate:
                src = self._sources.setdefault(source, _Bucket(self._source_burst, now))
                self._refill(src, self._source_rate, self._source_burst, now)
            ses = None
            if self._session_rate and session:
                ses = self._sessions.get(session)
                if ses is None:
                    ses = _Bucket(self._session_burst, now)
                    self._sessions[session] = ses
                    if len(self._sessions) > MAX_SESSION_BUCKETS:
                        self._sessions.popitem(last=False)
                else:
                    self._sessions.move_to_end(session)
                self._refill(ses, self._session_rate, self._session_burst, now)
            if (src is not None and src.tokens < 1) or (ses is not None and ses.tokens < 1):
                t = self._throttled
                t.total += 1
                t.by_source[source] = t.by_source.get(source, 0) + 1
                t.last_utc = datetime.now(timezone.utc).isoformat()
                return False
            if src is not None:
                src.tokens -= 1
            if ses is not None:
                ses.tokens -= 1
            return True

    def retry_after(self) -> int:
        """Seconds a refused sender should wait: enough for one token, at least 1."""
        rates = [r for r in (self._source_rate, self._session_rate) if r]
        return max(1, int(1 / min(rates)) if rates else 1)

    def snapshot(self) -> dict:
        """Throttling since the recorder started, for `/audit/status`."""
        with self._lock:
            t = self._throttled
            return {"total": t.total, "by_source": dict(t.by_source), "last_utc": t.last_utc}


_limiter: IngestLimiter | None = None


def get_limiter() -> IngestLimiter:
    """The process-wide limiter, built from settings on first use."""
    global _limiter
    if _limiter is None:
        from agentmetry.core.config import settings

        _limiter = IngestLimiter(
            source_rate=settings.audit_ingest_source_rate,
            source_burst=settings.audit_ingest_source_burst,
            session_rate=settings.audit_ingest_session_rate,
            session_burst=settings.audit_ingest_session_burst,
        )
    return _limiter


def reset_limiter() -> None:
    """Drop the limiter so the next request rebuilds it from settings (tests)."""
    global _limiter
    _limiter = None
