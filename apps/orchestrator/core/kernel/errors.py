"""Kernel-level errors."""

from __future__ import annotations


class BudgetExhausted(Exception):
    """Background work refused admission — only the interactive reserve remains."""
