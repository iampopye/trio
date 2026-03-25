"""Simple cron-like task scheduler for trio.

Supports periodic tasks defined in config.json:
    "cron": {
        "tasks": [
            {"name": "daily_summary", "schedule": "0 9 * * *", "action": "Send a daily summary"}
        ]
    }
"""

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class CronTask:
    """A scheduled task."""

    def __init__(self, name: str, interval_seconds: int, callback: Callable[[], Coroutine]):
        self.name = name
        self.interval = interval_seconds
        self.callback = callback
        self.last_run: float = 0
        self.enabled = True

    async def maybe_run(self) -> bool:
        """Run if enough time has passed. Returns True if ran."""
        if not self.enabled:
            return False
        now = time.time()
        if now - self.last_run >= self.interval:
            try:
                await self.callback()
                self.last_run = now
                logger.info(f"Cron task '{self.name}' completed")
                return True
            except Exception as e:
                logger.error(f"Cron task '{self.name}' failed: {e}")
        return False


class Scheduler:
    """Simple periodic task scheduler."""

    def __init__(self):
        self._tasks: list[CronTask] = []
        self._running = True

    def add_task(self, name: str, interval_seconds: int, callback: Callable[[], Coroutine]) -> None:
        self._tasks.append(CronTask(name, interval_seconds, callback))

    async def run(self) -> None:
        """Run the scheduler loop. Checks tasks every 60 seconds."""
        logger.info(f"Scheduler started with {len(self._tasks)} tasks")
        while self._running:
            for task in self._tasks:
                await task.maybe_run()
            await asyncio.sleep(60)

    def stop(self) -> None:
        self._running = False
