"""Helpers for accumulating LLM token usage in graph state."""

from __future__ import annotations

from typing import Any

from core.llm.client import call_llm
from core.llm.errors import CostBudgetExceeded
from core.llm.types import LLMResult


def max_cost_for_state(state: dict[str, Any]) -> float | None:
    cfg = state.get("skill_config") or {}
    raw = cfg.get("max_cost_per_run")
    if raw is None:
        return None
    value = float(raw)
    return value if value > 0 else None


def assert_cost_budget(state: dict[str, Any]) -> None:
    """Block the next LLM step when accumulated cost already hit the cap."""
    max_cost = max_cost_for_state(state)
    if max_cost is None:
        return
    cost = float(state.get("cost", 0.0))
    if cost >= max_cost:
        raise CostBudgetExceeded(cost, max_cost)


def merge_llm_usage(state: dict[str, Any], llm: LLMResult) -> dict[str, Any]:
    """Record usage truthfully — never raises.

    Enforcement lives in the pre-step gate (assert_cost_budget): raising here
    would discard a result that was already paid for and leave the overshoot
    unrecorded in state. Either way the cap overshoots by at most one call;
    this way the run keeps the output and the ledger keeps the truth.
    """
    providers = list(state.get("llm_providers") or [])
    if llm.provider and llm.provider not in providers:
        providers.append(llm.provider)
    return {
        "input_tokens": state.get("input_tokens", 0) + llm.usage.input_tokens,
        "output_tokens": state.get("output_tokens", 0) + llm.usage.output_tokens,
        "cost": float(state.get("cost", 0.0)) + llm.usage.cost,
        "llm_providers": providers,
    }


async def graph_call_llm(
    state: dict[str, Any],
    prompt: str,
    *,
    system: str = "",
    node: str = "",
) -> tuple[LLMResult, dict[str, Any]]:
    """Pre-step budget gate + LLM call + post-step usage merge."""
    assert_cost_budget(state)
    llm = await call_llm(
        prompt,
        system,
        session_id=state.get("session_id", ""),
        node=node,
    )
    return llm, merge_llm_usage(state, llm)
