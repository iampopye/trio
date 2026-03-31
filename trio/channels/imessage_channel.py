"""iMessage channel — macOS only via AppleScript + sqlite3 polling."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import logging
import platform
import sqlite3
import subprocess  # nosec B404
from pathlib import Path
from typing import Any

from trio.channels.base import BaseChannel
from trio.core.bus import MessageBus, StreamChunk

logger = logging.getLogger(__name__)

CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"


class IMessageChannel(BaseChannel):
    """iMessage channel via AppleScript (send) and sqlite3 (receive).

    macOS only. Raises RuntimeError on other platforms.
    """

    def __init__(self, bus: MessageBus, config: dict):
        super().__init__(name="imessage", bus=bus, config=config)
        if platform.system() != "Darwin":
            raise RuntimeError("iMessage channel is only available on macOS")
        self._poll_interval = config.get("poll_interval", 5)
        self._last_rowid: int = 0
        self._running = False
        self._poll_task = None

    async def start(self) -> None:
        """Start polling the Messages database for new messages."""
        if not CHAT_DB.exists():
            raise FileNotFoundError(
                f"iMessage database not found: {CHAT_DB}. "
                "Grant Full Disk Access to your terminal in System Settings."
            )

        # Get latest rowid to avoid replaying history
        self._last_rowid = self._get_latest_rowid()
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("iMessage channel started (polling)")

    async def stop(self) -> None:
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass  # nosec B110 — intentional silent fallback

    def _get_latest_rowid(self) -> int:
        """Get the most recent message ROWID."""
        try:
            conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
            cursor = conn.execute("SELECT MAX(ROWID) FROM message")
            row = cursor.fetchone()
            conn.close()
            return row[0] or 0
        except Exception as e:
            logger.error(f"iMessage DB read error: {e}")
            return 0

    async def _poll_loop(self) -> None:
        """Poll the Messages database for new incoming messages."""
        while self._running:
            try:
                new_messages = await asyncio.to_thread(self._fetch_new_messages)
                for msg in new_messages:
                    rowid, sender, text = msg
                    if text and sender:
                        await self.publish_inbound(
                            chat_id=sender,
                            user_id=sender,
                            content=text,
                        )
                    self._last_rowid = max(self._last_rowid, rowid)
            except Exception as e:
                logger.error(f"iMessage poll error: {e}")

            await asyncio.sleep(self._poll_interval)

    def _fetch_new_messages(self) -> list[tuple[int, str, str]]:
        """Fetch messages newer than last_rowid from chat.db."""
        try:
            conn = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
            cursor = conn.execute(
                """
                SELECT m.ROWID, h.id, m.text
                FROM message m
                LEFT JOIN handle h ON m.handle_id = h.ROWID
                WHERE m.ROWID > ?
                  AND m.is_from_me = 0
                  AND m.text IS NOT NULL
                  AND m.text != ''
                ORDER BY m.ROWID ASC
                """,
                (self._last_rowid,),
            )
            results = cursor.fetchall()
            conn.close()
            return results
        except Exception as e:
            logger.error(f"iMessage fetch error: {e}")
            return []

    async def send_message(self, chat_id: str, content: str) -> None:
        """Send an iMessage via AppleScript."""
        # Escape for AppleScript
        escaped = content.replace("\\", "\\\\").replace('"', '\\"')

        script = (
            f'tell application "Messages"\n'
            f'  set targetService to 1st account whose service type = iMessage\n'
            f'  set targetBuddy to participant "{chat_id}" of targetService\n'
            f'  send "{escaped}" to targetBuddy\n'
            f"end tell"
        )

        try:
            await asyncio.to_thread(
                subprocess.run,  # nosec B603 B607
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as e:
            logger.error(f"iMessage send failed: {e}")

    async def send_stream_chunk(self, chat_id: str, chunk: StreamChunk) -> None:
        """iMessage doesn't support editing — buffer until final."""
        if chunk.is_final:
            await self.send_message(chat_id, chunk.accumulated)
