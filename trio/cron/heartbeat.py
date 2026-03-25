"""Heartbeat daemon — periodically reads HEARTBEAT.md and sends tasks to agent."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from trio.core.bus import InboundMessage, MessageBus
from trio.core.config import get_workspace_dir

logger = logging.getLogger(__name__)


class HeartbeatDaemon:
    """Reads ~/.trio/workspace/HEARTBEAT.md on a configurable interval.

    Sends the checklist content as an InboundMessage to the bus so the
    LLM can autonomously decide whether to act on any items.
    """

    def __init__(self, bus: MessageBus, config: dict):
        self.bus = bus
        self._enabled = config.get("heartbeat", {}).get("enabled", False)
        self._interval = config.get("heartbeat", {}).get("interval_seconds", 300)
        self._notify_channel = config.get("heartbeat", {}).get("notify_channel", "")
        self._running = False
        self._task = None

    @property
    def heartbeat_path(self) -> Path:
        return get_workspace_dir() / "HEARTBEAT.md"

    async def start(self) -> None:
        """Start the heartbeat loop."""
        if not self._enabled:
            logger.debug("Heartbeat daemon disabled")
            return

        if not self.heartbeat_path.exists():
            # Create template
            self.heartbeat_path.write_text(
                "# Heartbeat Checklist\n\n"
                "<!-- trio reads this file periodically and acts on items below -->\n\n"
                "- [ ] Example: check if disk space is low\n"
                "- [ ] Example: summarize unread emails\n",
                encoding="utf-8",
            )
            logger.info(f"Created heartbeat template: {self.heartbeat_path}")

        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Heartbeat daemon started (interval: {self._interval}s)")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        """Main heartbeat loop."""
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"Heartbeat tick error: {e}")
            await asyncio.sleep(self._interval)

    async def _tick(self) -> None:
        """Read HEARTBEAT.md and send to agent if it has content."""
        if not self.heartbeat_path.exists():
            return

        content = self.heartbeat_path.read_text(encoding="utf-8").strip()
        if not content:
            return

        # Only send if there are unchecked items
        if "- [ ]" not in content:
            logger.debug("Heartbeat: no unchecked items, skipping")
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = (
            f"[Heartbeat {timestamp}] The following checklist needs attention:\n\n"
            f"{content}\n\n"
            "Review each unchecked item. Use available tools to complete tasks, "
            "then report what was done."
        )

        await self.bus.publish_inbound(InboundMessage(
            channel="heartbeat",
            chat_id="heartbeat",
            user_id="system",
            content=message,
            metadata={"source": "heartbeat_daemon"},
        ))
        logger.info("Heartbeat: sent checklist to agent")

    async def status(self) -> dict:
        """Return heartbeat status info."""
        return {
            "enabled": self._enabled,
            "running": self._running,
            "interval_seconds": self._interval,
            "heartbeat_file": str(self.heartbeat_path),
            "file_exists": self.heartbeat_path.exists(),
            "notify_channel": self._notify_channel or "(none)",
        }
