"""Execution context shared by API routes and autonomous triggers."""

from __future__ import annotations

from typing import Any

from core.config import settings
from core.graphs.registry import SkillRegistry
from core.memory.obsidian_client import ObsidianClient
from core.memory.rag_engine import RAGEngine
from core.kernel.interrupts import InterruptVectorTable
from core.telemetry.pending_store import PendingThreadStore
from core.telemetry.store import TelemetryStore

obsidian = ObsidianClient(settings.vault_path)
rag = RAGEngine(vault_path=settings.vault_path)
telemetry = TelemetryStore()
interrupt_table = InterruptVectorTable()
pending_store = PendingThreadStore()
skill_registry = SkillRegistry(obsidian)
pending_threads: dict[str, dict[str, Any]] = {}
