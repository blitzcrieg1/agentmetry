"""Kernel scheduler: interactive callers jump the queue; budget refuses background."""

from __future__ import annotations

import asyncio

import pytest

from core.kernel.scheduler import BudgetExhausted, Priority, TokenScheduler, run_priority


async def _grab(sched: TokenScheduler, priority: Priority, tag: str, order: list[str]):
    token = run_priority.set(priority)
    try:
        await sched.acquire("flash")
        order.append(tag)
    finally:
        run_priority.reset(token)


class AllowingLedger:
    def autonomous_allowed(self) -> bool:
        return True


async def test_interactive_preempts_queued_background(monkeypatch: pytest.MonkeyPatch):
    import core.kernel.scheduler as kernel

    # Never consult the real data/budget.db — its state depends on the machine.
    monkeypatch.setattr(kernel, "get_budget_ledger", lambda: AllowingLedger())
    sched = TokenScheduler(intervals={"flash": 0.10})
    order: list[str] = []

    await _grab(sched, Priority.INTERACTIVE, "first", order)  # consumes slot; lane now pacing

    background = asyncio.create_task(_grab(sched, Priority.MAINTENANCE, "background", order))
    await asyncio.sleep(0.02)  # background is queued first...
    interactive = asyncio.create_task(_grab(sched, Priority.INTERACTIVE, "interactive", order))
    await asyncio.gather(background, interactive)
    await sched.shutdown()

    # ...but the pacing wait happens before dequeue, so interactive wins the grant.
    assert order == ["first", "interactive", "background"]


async def test_pacing_interval_enforced():
    sched = TokenScheduler(intervals={"flash": 0.15})
    loop = asyncio.get_running_loop()
    start = loop.time()
    await sched.acquire("flash")
    await sched.acquire("flash")
    assert loop.time() - start >= 0.15
    await sched.shutdown()


async def test_background_refused_at_reserve(monkeypatch: pytest.MonkeyPatch):
    import core.kernel.scheduler as kernel

    class ExhaustedLedger:
        def autonomous_allowed(self) -> bool:
            return False

    monkeypatch.setattr(kernel, "get_budget_ledger", lambda: ExhaustedLedger())
    sched = TokenScheduler(intervals={"flash": 0.0})

    token = run_priority.set(Priority.AUTONOMOUS)
    try:
        with pytest.raises(BudgetExhausted):
            await sched.acquire("flash")
    finally:
        run_priority.reset(token)

    # Interactive is never budget-blocked at the kernel...
    await sched.acquire("flash")
    # ...and the embed lane has no Flash budget admission at all.
    token = run_priority.set(Priority.MAINTENANCE)
    try:
        await sched.acquire("embed")
    finally:
        run_priority.reset(token)
    await sched.shutdown()


async def test_explicit_priority_override(monkeypatch: pytest.MonkeyPatch):
    import core.kernel.scheduler as kernel

    class ExhaustedLedger:
        def autonomous_allowed(self) -> bool:
            return False

    monkeypatch.setattr(kernel, "get_budget_ledger", lambda: ExhaustedLedger())
    sched = TokenScheduler(intervals={"flash": 0.0})

    # Context says INTERACTIVE, but an explicit MAINTENANCE override is refused.
    with pytest.raises(BudgetExhausted):
        await sched.acquire("flash", priority=Priority.MAINTENANCE)
    await sched.shutdown()


async def test_cancelled_waiter_does_not_burn_slot():
    sched = TokenScheduler(intervals={"flash": 0.10})
    order: list[str] = []

    await _grab(sched, Priority.INTERACTIVE, "first", order)

    doomed = asyncio.create_task(_grab(sched, Priority.INTERACTIVE, "doomed", order))
    await asyncio.sleep(0.02)
    doomed.cancel()
    # INTERACTIVE so this test never consults the real budget ledger.
    survivor = asyncio.create_task(_grab(sched, Priority.INTERACTIVE, "survivor", order))

    with pytest.raises(asyncio.CancelledError):
        await doomed
    await survivor
    await sched.shutdown()

    assert order == ["first", "survivor"]
