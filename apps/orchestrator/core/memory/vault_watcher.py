"""Vault file watcher — syncs Obsidian changes to RAG and evaluates trigger rules."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from core.config import settings
from core.memory.rag_engine import RAGEngine
from core.scheduler.triggers import evaluate_vault_triggers

logger = logging.getLogger(__name__)


class VaultSyncHandler(FileSystemEventHandler):
    def __init__(self, rag: RAGEngine, loop: asyncio.AbstractEventLoop, vault_path: Path):
        self.rag = rag
        self.loop = loop
        self.vault_path = vault_path
        self._debounce: dict[str, asyncio.TimerHandle] = {}

    def _schedule_reindex(self, path: str) -> None:
        if not path.endswith(".md"):
            return
        if ".system" in path.replace("\\", "/"):
            return

        if path in self._debounce:
            self._debounce[path].cancel()

        def _do_index():
            file_path = Path(path)

            async def _work():
                await self.rag.index_file(file_path)
                await evaluate_vault_triggers(file_path, self.vault_path)

            asyncio.run_coroutine_threadsafe(_work(), self.loop)

        handle = self.loop.call_later(2.0, _do_index)
        self._debounce[path] = handle
        logger.info("Vault change detected: %s — scheduling index + triggers", path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._schedule_reindex(event.src_path)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._schedule_reindex(event.src_path)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory or not event.src_path.endswith(".md"):
            return
        file_path = Path(event.src_path)
        try:
            rel_path = str(file_path.relative_to(self.vault_path))
        except ValueError:
            return

        async def _remove():
            await self.rag.remove_file(rel_path)

        asyncio.run_coroutine_threadsafe(_remove(), self.loop)


class VaultWatcher:
    def __init__(self, vault_path: Path | None = None):
        self.vault_path = vault_path or settings.vault_path
        self.rag = RAGEngine(vault_path=self.vault_path)
        self.observer: Observer | None = None

    async def start(self) -> None:
        loop = asyncio.get_event_loop()
        handler = VaultSyncHandler(self.rag, loop, Path(self.vault_path))
        self.observer = Observer()
        self.observer.schedule(handler, str(self.vault_path), recursive=True)
        self.observer.start()
        logger.info("Vault watcher started on %s", self.vault_path)

        asyncio.create_task(self._initial_index())

    async def _initial_index(self) -> None:
        try:
            count = await self.rag.index_vault()
            logger.info("Initial vault index: %d chunks", count)
        except Exception as e:
            logger.warning("Initial vault index skipped: %s", e)

    def stop(self) -> None:
        if self.observer:
            self.observer.stop()
            self.observer.join()
            logger.info("Vault watcher stopped")
