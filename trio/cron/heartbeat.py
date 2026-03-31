"""Heartbeat daemon — periodically reads HEARTBEAT.md and sends tasks to agent.

Integrates with :class:`trio.cron.daemon.TrioDaemon` for background execution.
Logs tick results to a dedicated heartbeat log file.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from trio.core.bus import InboundMessage, MessageBus
from trio.core.config import get_workspace_dir

logger = logging.getLogger(__name__)


class HeartbeatDaemon:
    """Reads ``~/.trio/workspace/HEARTBEAT.md`` on a configurable interval.

    Sends the checklist content as an :class:`InboundMessage` to the bus so
    the LLM can autonomously decide whether to act on any items.

    Parameters
    ----------
    bus:
        The shared :class:`MessageBus`.
    config:
        Full trio config dict (uses ``config["heartbeat"]``).
    log_path:
        Optional path for a dedicated heartbeat log file.  When running
        inside :class:`~trio.cron.daemon.TrioDaemon`, the daemon passes
        ``~/.trio/daemon/heartbeat.log``.
    """

    def __init__(
        self,
        bus: MessageBus,
        config: dict,
        log_path: Path | None = None,
    ):
        self.bus = bus

        hb_config = config.get("heartbeat", {})
        self._enabled = hb_config.get("enabled", False)
        self._interval = hb_config.get("interval_seconds", 300)
        self._notify_channel = hb_config.get("notify_channel", "")

        self._running = False
        self._task: asyncio.Task | None = None
        self._tick_count = 0
        self._last_tick: datetime | None = None
        self._last_result: str = ""

        # Dedicated heartbeat log file (append mode)
        self._hb_logger: logging.Logger | None = None
        if log_path is not None:
            self._hb_logger = logging.getLogger("trio.heartbeat.file")
            self._hb_logger.propagate = False
            handler = logging.FileHandler(str(log_path), encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s: %(message)s",
            ))
            self._hb_logger.addHandler(handler)
            self._hb_logger.setLevel(logging.INFO)

    @property
    def heartbeat_path(self) -> Path:
        return get_workspace_dir() / "HEARTBEAT.md"

    @property
    def interval(self) -> int:
        """Current interval in seconds (can be updated at runtime)."""
        return self._interval

    @interval.setter
    def interval(self, value: int) -> None:
        self._interval = max(10, value)  # floor at 10 s

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the heartbeat loop."""
        if not self._enabled:
            logger.debug("Heartbeat daemon disabled")
            return

        if not self.heartbeat_path.exists():
            self.heartbeat_path.write_text(
                "# Heartbeat Checklist\n\n"
                "<!-- trio reads this file periodically and acts on items below -->\n\n"
                "- [ ] Example: check if disk space is low\n"
                "- [ ] Example: summarize unread emails\n",
                encoding="utf-8",
            )
            logger.info("Created heartbeat template: %s", self.heartbeat_path)

        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "Heartbeat daemon started (interval: %ds, file: %s)",
            self._interval,
            self.heartbeat_path,
        )
        self._log_hb("Heartbeat started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        """Stop the heartbeat loop gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._log_hb("Heartbeat stopped")
        logger.info("Heartbeat daemon stopped")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """Main heartbeat loop — tick, sleep, repeat."""
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Heartbeat tick error: %s", exc)
                self._log_hb("ERROR: %s", exc)
                self._last_result = f"error: {exc}"
            await asyncio.sleep(self._interval)

    async def _tick(self) -> None:
        """Read HEARTBEAT.md and send unchecked items to the agent."""
        if not self.heartbeat_path.exists():
            self._last_result = "file not found"
            return

        content = self.heartbeat_path.read_text(encoding="utf-8").strip()
        if not content:
            self._last_result = "empty file"
            return

        # Only send if there are unchecked items
        if "- [ ]" not in content:
            self._last_result = "no unchecked items"
            logger.debug("Heartbeat: no unchecked items, skipping")
            self._log_hb("Tick #%d: no unchecked items", self._tick_count + 1)
            self._tick_count += 1
            self._last_tick = datetime.now()
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

        self._tick_count += 1
        self._last_tick = datetime.now()
        self._last_result = "sent to agent"

        logger.info("Heartbeat: sent checklist to agent (tick #%d)", self._tick_count)
        self._log_hb(
            "Tick #%d: sent checklist to agent (%d unchecked items)",
            self._tick_count,
            content.count("- [ ]"),
        )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def status(self) -> dict:
        """Return heartbeat status info (used by daemon health checks)."""
        return {
            "enabled": self._enabled,
            "running": self._running,
            "interval_seconds": self._interval,
            "heartbeat_file": str(self.heartbeat_path),
            "file_exists": self.heartbeat_path.exists(),
            "tick_count": self._tick_count,
            "last_tick": self._last_tick.isoformat() if self._last_tick else None,
            "last_result": self._last_result,
            "notify_channel": self._notify_channel or "(none)",
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log_hb(self, msg: str, *args) -> None:
        """Write to the dedicated heartbeat log file, if configured."""
        if self._hb_logger:
            self._hb_logger.info(msg, *args)
