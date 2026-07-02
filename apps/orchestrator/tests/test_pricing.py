"""Tests for Gemini cost estimation."""

from core.llm.pricing import cost_from_usage, estimate_cost


def test_flash_cost_positive():
    cost = estimate_cost("gemini-2.5-flash", 1000, 500)
    assert cost > 0


def test_cost_from_usage_uses_configured_model():
    cost = cost_from_usage(10_000, 2_000)
    assert cost > 0
