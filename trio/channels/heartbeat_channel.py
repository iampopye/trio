"""Heartbeat channel — virtual channel that logs agent responses to heartbeat tasks."""

import logging
from datetime import datetime
from pathlib import Path

from trio.channels.base import BaseChannel
from trio.core.bus import MessageBus, StreamChunk
from trio.core.config import get_memory_dir

logger = logging.getLogger(__name__)


class HeartbeatChannel(BaseChannel):
    """Virtual channel for heartbeat daemon responses.

    Logs all responses to ~/.trio/memory/heartbeat.log.
    Optionally forwards to a configured notify channel.
    """

    def __init__(self, bus: MessageBus, config: dict):
        super().__init__(name="heartbeat", bus=bus, config=config)
        self._notify_channel = config.get("heartbeat", {}).get("notify_channel", "")
        self._log_path = get_memory_dir() / "heartbeat.log"

    async def start(self) -> None:
        logger.info("Heartbeat channel started")

    async def stop(self) -> None:
        pass

    async def send_message(self, chat_id: str, content: str) -> None:
        """Log heartbeat response and optionally forward."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"\n[{timestamp}]\n{content}\n{'=' * 60}\n"

        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(log_entry)
            logger.info(f"Heartbeat response logged ({len(content)} chars)")
        except Exception as e:
            logger.error(f"Failed to write heartbeat log: {e}")

    async def send_stream_chunk(self, chat_id: str, chunk: StreamChunk) -> None:
        """Buffer until final."""
        if chunk.is_final:
            await self.send_message(chat_id, chunk.accumulated)
