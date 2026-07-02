"""Vault file watcher — syncs Obsidian changes to Qdrant in real time."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from core.config import settings
from core.memory.rag_engine import RAGEngine

logger = logging.getLogger(__name__)


class VaultSyncHandler(FileSystemEventHandler):
    def __init__(self, rag: RAGEngine, loop: asyncio.AbstractEventLoop):
        self.rag = rag
        self.loop = loop
        self._debounce: dict[str, asyncio.TimerHandle] = {}

    def _schedule_reindex(self, path: str) -> None:
        if not path.endswith(".md"):
            return
        if ".system" in path:
            return

        if path in self._debounce:
            self._debounce[path].cancel()

        def _do_index():
            asyncio.run_coroutine_threadsafe(self.rag.index_vault(), self.loop)

        handle = self.loop.call_later(2.0, _do_index)
        self._debounce[path] = handle
        logger.info("Vault change detected: %s — scheduling reindex", path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._schedule_reindex(event.src_path)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._schedule_reindex(event.src_path)


class VaultWatcher:
    def __init__(self, vault_path: Path | None = None):
        self.vault_path = vault_path or settings.vault_path
        self.rag = RAGEngine(vault_path=self.vault_path)
        self.observer: Observer | None = None

    async def start(self) -> None:
        loop = asyncio.get_event_loop()
        handler = VaultSyncHandler(self.rag, loop)
        self.observer = Observer()
        self.observer.schedule(handler, str(self.vault_path), recursive=True)
        self.observer.start()
        logger.info("Vault watcher started on %s", self.vault_path)

        # Index in background — don't block API startup
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
