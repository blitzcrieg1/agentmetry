"""Kernel token scheduler — priority-ordered, paced, budget-aware LLM admission.

Unifies the ad-hoc resource controls (quota.py pacing locks, per-run budget
pre-checks) into one grant queue per lane. Interactive callers win the next
grant over queued background work; pacing keeps the free-tier RPM limits.

Cooperative by design: priority decides who gets the *next* grant — an
in-flight LLM call is never preempted.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import IntEnum

from core.config import settings
from core.llm.budget import get_budget_ledger

logger = logging.getLogger(__name__)


class Priority(IntEnum):
    INTERACTIVE = 0    # dashboard-initiated runs, approval resumes
    AUTONOMOUS = 10    # vault triggers, cron skills
    MAINTENANCE = 20   # vault indexing, digests, health probes


# Set once per run/task; flows through LangGraph's async nodes automatically.
# Task-scoped: each asyncio task gets its own context copy, so a bare set()
# at the top of a task cannot leak into unrelated work.
run_priority: ContextVar[Priority] = ContextVar("run_priority", default=Priority.INTERACTIVE)


class BudgetExhausted(Exception):
    """Background work refused admission — only the interactive reserve remains."""


@dataclass
class _Lane:
    interval: float
    queue: asyncio.PriorityQueue = field(default_factory=asyncio.PriorityQueue)
    last_grant: float = float("-inf")
    worker: asyncio.Task | None = None


class TokenScheduler:
    def __init__(self, intervals: dict[str, float] | None = None):
        self._intervals = intervals or {
            "flash": settings.gemini_flash_min_interval_seconds,
            "embed": settings.gemini_embed_min_interval_seconds,
        }
        self._lanes: dict[str, _Lane] = {}
        self._seq = itertools.count()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bg_slots: asyncio.Semaphore | None = None

    async def acquire(self, lane: str = "flash", *, priority: Priority | None = None) -> None:
        """Block until it is this caller's turn on the lane, pacing included."""
        effective = priority if priority is not None else run_priority.get()

        # Admission: background work never eats the interactive Flash reserve.
        if lane == "flash" and effective >= Priority.AUTONOMOUS:
            if not get_budget_ledger().autonomous_allowed():
                raise BudgetExhausted(
                    "Flash budget at interactive reserve — background call refused"
                )

        state = self._lane(lane)
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        state.queue.put_nowait((int(effective), next(self._seq), future))
        try:
            await future
        except asyncio.CancelledError:
            future.cancel()  # worker skips cancelled grants without burning a slot
            raise

    @asynccontextmanager
    async def run_slot(self, priority: Priority | None = None):
        """Admit a run into the system.

        Interactive runs are admitted immediately — a human is never queued
        behind background work at the run level (per-call lane priority
        already orders the LLM grants). Background runs (triggers, cron,
        resumes) share a small pool so a trigger storm cannot fan out into
        unbounded concurrent graphs.
        """
        effective = priority if priority is not None else run_priority.get()
        if effective == Priority.INTERACTIVE:
            yield
            return
        self._ensure_loop()
        if self._bg_slots is None:
            self._bg_slots = asyncio.Semaphore(settings.kernel_background_run_limit)
        async with self._bg_slots:
            yield

    def _ensure_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            # Fresh event loop (process restart, tests): stale workers and
            # waiters belong to a dead loop and cannot be touched from here —
            # drop and rebuild.
            self._lanes.clear()
            self._bg_slots = None
            self._loop = loop

    def _lane(self, lane: str) -> _Lane:
        self._ensure_loop()
        if lane not in self._lanes:
            state = _Lane(interval=self._intervals.get(lane, 0.0))
            state.worker = asyncio.get_running_loop().create_task(
                self._grant_loop(lane, state)
            )
            self._lanes[lane] = state
        return self._lanes[lane]

    async def _grant_loop(self, lane: str, state: _Lane) -> None:
        while True:
            # Pace *before* dequeuing, so a high-priority caller arriving during
            # the pacing wait still wins the grant over earlier background work.
            wait = state.interval - (time.monotonic() - state.last_grant)
            if wait > 0:
                await asyncio.sleep(wait)
            priority, _seq, future = await state.queue.get()
            if future.cancelled():
                continue
            state.last_grant = time.monotonic()
            future.set_result(None)
            if priority >= Priority.AUTONOMOUS:
                logger.debug("Kernel grant [%s] to background caller", lane)

    async def shutdown(self) -> None:
        for state in self._lanes.values():
            if state.worker:
                state.worker.cancel()
        self._lanes.clear()
        self._bg_slots = None
        self._loop = None


_scheduler: TokenScheduler | None = None


def get_scheduler() -> TokenScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = TokenScheduler()
    return _scheduler
