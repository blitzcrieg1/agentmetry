"""Vault file watcher — syncs Obsidian changes to RAG and evaluates trigger rules."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from core.bus.bus import bus
from core.bus.events import VAULT_FILE_CHANGED
from core.config import settings
from core.kernel.scheduler import Priority, run_priority
from core.memory.rag_engine import RAGEngine

logger = logging.getLogger(__name__)


class VaultSyncHandler(FileSystemEventHandler):
    def __init__(self, rag: RAGEngine, loop: asyncio.AbstractEventLoop, vault_path: Path):
        self.rag = rag
        self.loop = loop
        self.vault_path = vault_path
        self._debounce: dict[str, asyncio.TimerHandle] = {}
        # Strong refs so in-flight index tasks are not garbage-collected.
        self._tasks: set[asyncio.Task] = set()

    def _schedule_reindex(self, path: str) -> None:
        if not path.endswith(".md"):
            return
        if ".system" in path.replace("\\", "/"):
            return

        def _do_index():
            self._debounce.pop(path, None)
            file_path = Path(path)

            async def _work():
                # Indexing is background; triggered runs re-tag as AUTONOMOUS.
                run_priority.set(Priority.MAINTENANCE)
                await self.rag.index_file(file_path)
                # Trigger evaluation is decoupled: the bus bridge reacts.
                bus.publish(VAULT_FILE_CHANGED, {
                    "absolute_path": str(file_path),
                    "vault_path": str(self.vault_path),
                })

            task = self.loop.create_task(_work())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        def _arm_timer():
            # Timer create/cancel must happen on the loop thread; watchdog
            # callbacks arrive on the observer thread.
            existing = self._debounce.get(path)
            if existing is not None:
                existing.cancel()
            self._debounce[path] = self.loop.call_later(2.0, _do_index)

        self.loop.call_soon_threadsafe(_arm_timer)
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
        run_priority.set(Priority.MAINTENANCE)
        if not settings.startup_vault_index:
            logger.info("Startup vault index skipped (BLACKBOX_STARTUP_VAULT_INDEX=false)")
            return
        try:
            count = await self.rag.index_vault()
            logger.info("Startup vault index: %d chunks indexed", count)
        except Exception as e:
            logger.warning("Initial vault index skipped: %s", e)

    def stop(self) -> None:
        if self.observer:
            self.observer.stop()
            self.observer.join()
            logger.info("Vault watcher stopped")
