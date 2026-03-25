"""Discord channel — discord.py integration with streaming message edits.

Extracted from BotServer's discord_bot.py with channel abstraction.
Keeps: streaming edits (0.6s), message splitting (2000 chars), typing indicators.
"""

import asyncio
import logging
import time
from typing import Any

from trio.channels.base import BaseChannel
from trio.core.bus import MessageBus, StreamChunk, OutboundMessage

logger = logging.getLogger(__name__)

MESSAGE_LIMIT = 2000
STREAM_EDIT_INTERVAL = 0.6


class DiscordChannel(BaseChannel):
    """Discord bot channel via discord.py."""

    def __init__(self, bus: MessageBus, config: dict):
        super().__init__(name="discord", bus=bus, config=config)
        self._bot = None
        self._token = config.get("token", "")
        self._active_messages: dict[str, Any] = {}  # chat_id → discord.Message
        self._last_edit_time: dict[str, float] = {}
        self._stream_buffers: dict[str, str] = {}

    async def start(self) -> None:
        """Start the Discord bot."""
        try:
            import discord
            from discord.ext import commands
        except ImportError:
            raise ImportError("discord.py required. Install: pip install trio-ai[discord]")

        intents = discord.Intents.default()
        intents.message_content = True
        self._bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

        @self._bot.event
        async def on_ready():
            logger.info(f"Discord connected as {self._bot.user}")

        @self._bot.event
        async def on_message(message):
            if message.author == self._bot.user:
                return
            if message.author.bot:
                return

            # Process commands or regular messages
            content = message.content.strip()
            if not content:
                return

            chat_id = str(message.channel.id)
            user_id = str(message.author.id)

            # Store channel reference for sending
            self._active_messages[f"channel_{chat_id}"] = message.channel

            await self.publish_inbound(
                chat_id=chat_id,
                user_id=user_id,
                content=content,
                author_name=str(message.author),
            )

        # Start bot in background
        asyncio.create_task(self._bot.start(self._token))

    async def stop(self) -> None:
        if self._bot:
            await self._bot.close()

    async def send_message(self, chat_id: str, content: str) -> None:
        """Send a complete message, splitting if needed."""
        channel = self._active_messages.get(f"channel_{chat_id}")
        if not channel:
            logger.warning(f"Discord: no channel reference for {chat_id}")
            return

        # Split long messages
        chunks = self._split_message(content, MESSAGE_LIMIT)
        for chunk in chunks:
            await channel.send(chunk)

        # Clean up streaming state
        self._active_messages.pop(chat_id, None)
        self._stream_buffers.pop(chat_id, None)

    async def send_stream_chunk(self, chat_id: str, chunk: StreamChunk) -> None:
        """Live-edit Discord message with streaming content."""
        channel = self._active_messages.get(f"channel_{chat_id}")
        if not channel:
            return

        if chat_id not in self._stream_buffers:
            self._stream_buffers[chat_id] = ""

        self._stream_buffers[chat_id] = chunk.accumulated

        if chunk.is_final:
            # Send final version
            msg = self._active_messages.get(chat_id)
            final_text = self._stream_buffers.pop(chat_id, chunk.accumulated)
            if msg:
                try:
                    if len(final_text) <= MESSAGE_LIMIT:
                        await msg.edit(content=final_text)
                    else:
                        # Delete streaming message, send split messages
                        await msg.delete()
                        for part in self._split_message(final_text, MESSAGE_LIMIT):
                            await channel.send(part)
                except Exception:
                    pass
            self._active_messages.pop(chat_id, None)
            return

        now = time.time()
        last_edit = self._last_edit_time.get(chat_id, 0)

        if now - last_edit < STREAM_EDIT_INTERVAL:
            return  # Rate limit

        text = self._stream_buffers[chat_id]
        if len(text) > MESSAGE_LIMIT:
            text = text[:MESSAGE_LIMIT - 3] + "..."

        if text.strip():
            msg = self._active_messages.get(chat_id)
            try:
                if msg is None:
                    msg = await channel.send(text + " ▌")
                    self._active_messages[chat_id] = msg
                else:
                    await msg.edit(content=text + " ▌")
                self._last_edit_time[chat_id] = now
            except Exception as e:
                logger.debug(f"Discord edit failed: {e}")

    def _split_message(self, text: str, limit: int) -> list[str]:
        """Split message at limit boundaries."""
        if len(text) <= limit:
            return [text]
        parts = []
        while text:
            if len(text) <= limit:
                parts.append(text)
                break
            # Try to split at newline
            split_pos = text.rfind("\n", 0, limit)
            if split_pos == -1 or split_pos < limit // 2:
                split_pos = limit
            parts.append(text[:split_pos])
            text = text[split_pos:].lstrip("\n")
        return parts
