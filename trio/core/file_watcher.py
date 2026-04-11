"""File watcher — observe workspace changes and notify the agent.

Lightweight polling-based file watcher (no external dependencies).
Detects file additions, modifications, and deletions in the workspace
and triggers callbacks. Used by the agent loop and (optionally) the
code-review-graph MCP server to keep its index in sync.

Usage:
    from trio.core.file_watcher import FileWatcher

    async def on_change(event):
        print(f"{event.kind}: {event.path}")

    watcher = FileWatcher(workspace_dir, on_change)
    await watcher.start()
    # ...
    await watcher.stop()
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# Files/directories to skip — these are noisy and not interesting
DEFAULT_IGNORE_PATTERNS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    ".trio", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "dist", "build", ".idea", ".vscode", ".DS_Store",
    "*.pyc", "*.pyo", "*.swp", "*.tmp", "*.log",
}


@dataclass
class FileEvent:
    """A single filesystem change event."""

    kind: str           # "added" | "modified" | "deleted"
    path: Path
    timestamp: float

    def __repr__(self) -> str:
        return f"FileEvent({self.kind}, {self.path.name})"


class FileWatcher:
    """Polling-based file watcher with debouncing.

    Suitable for small to medium workspaces (< 10k files). For larger
    workspaces, install `watchdog` and use the inotify-based watcher.
    """

    def __init__(
        self,
        root: Path,
        on_change: Callable[[FileEvent], Awaitable[None]],
        poll_interval: float = 2.0,
        ignore_patterns: set[str] | None = None,
        max_files: int = 10000,
    ):
        self.root = Path(root).resolve()
        self.on_change = on_change
        self.poll_interval = poll_interval
        self.ignore_patterns = ignore_patterns or DEFAULT_IGNORE_PATTERNS
        self.max_files = max_files

        self._snapshot: dict[Path, tuple[float, int]] = {}  # path → (mtime, size)
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the watcher in the background."""
        if self._task and not self._task.done():
            logger.warning("FileWatcher already running for %s", self.root)
            return

        if not self.root.exists():
            logger.error("Cannot watch non-existent path: %s", self.root)
            return

        self._snapshot = self._take_snapshot()
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            "FileWatcher started: %s (%d files indexed)",
            self.root,
            len(self._snapshot),
        )

    async def stop(self) -> None:
        """Stop the watcher."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("FileWatcher stopped: %s", self.root)

    def _should_ignore(self, path: Path) -> bool:
        """Check if a path matches any ignore pattern."""
        for part in path.parts:
            if part in self.ignore_patterns:
                return True
        # Check filename patterns (e.g. "*.pyc")
        name = path.name
        for pat in self.ignore_patterns:
            if pat.startswith("*") and name.endswith(pat[1:]):
                return True
        return False

    def _take_snapshot(self) -> dict[Path, tuple[float, int]]:
        """Walk the workspace and snapshot mtimes/sizes."""
        snapshot: dict[Path, tuple[float, int]] = {}
        count = 0
        try:
            for path in self.root.rglob("*"):
                if count >= self.max_files:
                    logger.warning(
                        "FileWatcher hit max_files=%d, ignoring further files",
                        self.max_files,
                    )
                    break
                if not path.is_file():
                    continue
                if self._should_ignore(path.relative_to(self.root)):
                    continue
                try:
                    stat = path.stat()
                    snapshot[path] = (stat.st_mtime, stat.st_size)
                    count += 1
                except OSError:
                    continue
        except Exception as e:
            logger.error("Error taking snapshot: %s", e)
        return snapshot

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                await asyncio.sleep(self.poll_interval)
                if not self._running:
                    break
                await self._check_changes()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("FileWatcher poll error: %s", e)

    async def _check_changes(self) -> None:
        """Compare current state to snapshot and emit events."""
        new_snapshot = self._take_snapshot()
        events: list[FileEvent] = []
        now = time.time()

        # Detect added/modified
        for path, (mtime, size) in new_snapshot.items():
            old = self._snapshot.get(path)
            if old is None:
                events.append(FileEvent("added", path, now))
            elif old != (mtime, size):
                events.append(FileEvent("modified", path, now))

        # Detect deleted
        for path in self._snapshot:
            if path not in new_snapshot:
                events.append(FileEvent("deleted", path, now))

        self._snapshot = new_snapshot

        # Dispatch events (limit to 50 per cycle to avoid spam)
        for event in events[:50]:
            try:
                await self.on_change(event)
            except Exception as e:
                logger.error("FileWatcher callback error: %s", e)

        if len(events) > 50:
            logger.warning(
                "FileWatcher truncated %d events to 50 (workspace too active)",
                len(events),
            )


async def watch_workspace_simple(
    root: Path,
    callback: Callable[[FileEvent], Awaitable[None]],
    poll_interval: float = 2.0,
) -> FileWatcher:
    """Convenience: start a watcher and return it."""
    watcher = FileWatcher(root, callback, poll_interval=poll_interval)
    await watcher.start()
    return watcher
