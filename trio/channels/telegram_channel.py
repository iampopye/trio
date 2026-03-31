"""Telegram channel — pyTelegramBotAPI integration with streaming edits.

Extracted from BotServer's telegram_bot.py with channel abstraction.
Keeps: streaming edits (1.0s), message splitting (4000 chars), photo support.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import logging
import time
import threading
from typing import Any

from trio.channels.base import BaseChannel
from trio.core.bus import MessageBus, StreamChunk, OutboundMessage

logger = logging.getLogger(__name__)

MESSAGE_LIMIT = 4000
STREAM_EDIT_INTERVAL = 1.0


class TelegramChannel(BaseChannel):
    """Telegram bot channel via pyTelegramBotAPI."""

    def __init__(self, bus: MessageBus, config: dict):
        super().__init__(name="telegram", bus=bus, config=config)
        self._bot = None
        self._token = config.get("token", "")
        self._admin_id = config.get("admin_id", 0)
        self._active_messages: dict[str, Any] = {}  # chat_id → telegram message
        self._last_edit_time: dict[str, float] = {}
        self._stream_buffers: dict[str, str] = {}

    async def start(self) -> None:
        """Start the Telegram bot in a background thread."""
        try:
            import telebot
        except ImportError:
            raise ImportError("pyTelegramBotAPI required. Install: pip install trio-ai[telegram]")

        self._bot = telebot.TeleBot(self._token)
        bus = self.bus  # Capture for closure

        @self._bot.message_handler(func=lambda m: True)
        def handle_message(message):
            content = message.text or ""
            if not content:
                return

            chat_id = str(message.chat.id)
            user_id = str(message.from_user.id)

            # Run async publish in the event loop
            asyncio.run_coroutine_threadsafe(
                self.publish_inbound(
                    chat_id=chat_id,
                    user_id=user_id,
                    content=content,
                    username=message.from_user.username or "",
                    first_name=message.from_user.first_name or "",
                ),
                self._loop,
            )

        # Store event loop reference
        self._loop = asyncio.get_event_loop()

        # Start polling in background thread
        thread = threading.Thread(
            target=self._bot.infinity_polling,
            kwargs={"timeout": 30, "long_polling_timeout": 30},
            daemon=True,
        )
        thread.start()
        logger.info("Telegram bot started (polling)")

    async def stop(self) -> None:
        if self._bot:
            self._bot.stop_polling()

    async def send_message(self, chat_id: str, content: str) -> None:
        """Send a complete message to Telegram chat."""
        if not self._bot:
            return

        # Split long messages
        parts = self._split_message(content, MESSAGE_LIMIT)
        for part in parts:
            try:
                await asyncio.to_thread(
                    self._bot.send_message,
                    int(chat_id),
                    part,
                    parse_mode="Markdown",
                )
            except Exception:
                # Retry without markdown if parsing fails
                try:
                    await asyncio.to_thread(
                        self._bot.send_message,
                        int(chat_id),
                        part,
                    )
                except Exception as e:
                    logger.error(f"Telegram send failed: {e}")

        # Clean up streaming state
        self._active_messages.pop(chat_id, None)
        self._stream_buffers.pop(chat_id, None)

    async def send_stream_chunk(self, chat_id: str, chunk: StreamChunk) -> None:
        """Live-edit Telegram message with streaming content."""
        if not self._bot:
            return

        if chat_id not in self._stream_buffers:
            self._stream_buffers[chat_id] = ""

        self._stream_buffers[chat_id] = chunk.accumulated

        if chunk.is_final:
            msg = self._active_messages.get(chat_id)
            final_text = self._stream_buffers.pop(chat_id, chunk.accumulated)
            if msg:
                try:
                    if len(final_text) <= MESSAGE_LIMIT:
                        await asyncio.to_thread(
                            self._bot.edit_message_text,
                            final_text,
                            chat_id=int(chat_id),
                            message_id=msg.message_id,
                            parse_mode="Markdown",
                        )
                    else:
                        for part in self._split_message(final_text, MESSAGE_LIMIT):
                            await asyncio.to_thread(
                                self._bot.send_message, int(chat_id), part,
                            )
                except Exception:
                    pass  # nosec B110 — intentional silent fallback
            self._active_messages.pop(chat_id, None)
            return

        now = time.time()
        last_edit = self._last_edit_time.get(chat_id, 0)

        if now - last_edit < STREAM_EDIT_INTERVAL:
            return

        text = self._stream_buffers[chat_id]
        if len(text) > MESSAGE_LIMIT:
            text = text[:MESSAGE_LIMIT - 3] + "..."

        if text.strip():
            msg = self._active_messages.get(chat_id)
            try:
                if msg is None:
                    result = await asyncio.to_thread(
                        self._bot.send_message, int(chat_id), text + " ▌",
                    )
                    self._active_messages[chat_id] = result
                else:
                    await asyncio.to_thread(
                        self._bot.edit_message_text,
                        text + " ▌",
                        chat_id=int(chat_id),
                        message_id=msg.message_id,
                    )
                self._last_edit_time[chat_id] = now
            except Exception as e:
                logger.debug(f"Telegram edit failed: {e}")

    def _split_message(self, text: str, limit: int) -> list[str]:
        if len(text) <= limit:
            return [text]
        parts = []
        while text:
            if len(text) <= limit:
                parts.append(text)
                break
            split_pos = text.rfind("\n", 0, limit)
            if split_pos == -1 or split_pos < limit // 2:
                split_pos = limit
            parts.append(text[:split_pos])
            text = text[split_pos:].lstrip("\n")
        return parts
