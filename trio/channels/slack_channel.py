"""Slack channel — Socket Mode with live message editing."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import logging
import time
from typing import Any

from trio.channels.base import BaseChannel
from trio.core.bus import MessageBus, StreamChunk

logger = logging.getLogger(__name__)

MESSAGE_LIMIT = 4000
STREAM_EDIT_INTERVAL = 0.8


class SlackChannel(BaseChannel):
    """Slack bot via Socket Mode with streaming message edits."""

    def __init__(self, bus: MessageBus, config: dict):
        super().__init__(name="slack", bus=bus, config=config)
        self._bot_token = config.get("bot_token", "")
        self._app_token = config.get("app_token", "")
        self._client = None
        self._socket_handler = None
        self._active_messages: dict[str, dict] = {}  # chat_id → {ts, channel}
        self._last_edit_time: dict[str, float] = {}
        self._stream_buffers: dict[str, str] = {}
        self._bot_user_id: str = ""

    async def start(self) -> None:
        """Start the Slack Socket Mode connection."""
        try:
            from slack_sdk.web.async_client import AsyncWebClient
            from slack_sdk.socket_mode.aiohttp import SocketModeClient
            from slack_sdk.socket_mode.request import SocketModeRequest
            from slack_sdk.socket_mode.response import SocketModeResponse
        except ImportError:
            raise ImportError("slack-sdk required. Install: pip install trio-ai[slack]")

        self._client = AsyncWebClient(token=self._bot_token)

        # Get bot user ID
        auth = await self._client.auth_test()
        self._bot_user_id = auth.get("user_id", "")

        self._socket_handler = SocketModeClient(
            app_token=self._app_token,
            web_client=self._client,
        )

        async def handle_event(client, req: SocketModeRequest):
            await client.send_socket_mode_response(
                SocketModeResponse(envelope_id=req.envelope_id)
            )

            if req.type == "events_api":
                event = req.payload.get("event", {})
                if event.get("type") == "message" and "subtype" not in event:
                    user = event.get("user", "")
                    if user == self._bot_user_id:
                        return
                    text = event.get("text", "")
                    channel = event.get("channel", "")
                    if text and channel:
                        await self.publish_inbound(
                            chat_id=channel,
                            user_id=user,
                            content=text,
                        )

        self._socket_handler.socket_mode_request_listeners.append(handle_event)
        asyncio.create_task(self._socket_handler.connect())
        logger.info("Slack Socket Mode connected")

    async def stop(self) -> None:
        if self._socket_handler:
            await self._socket_handler.close()

    async def send_message(self, chat_id: str, content: str) -> None:
        """Send a complete message to a Slack channel."""
        if not self._client:
            return

        chunks = self._split_message(content, MESSAGE_LIMIT)
        for chunk in chunks:
            try:
                await self._client.chat_postMessage(channel=chat_id, text=chunk)
            except Exception as e:
                logger.error(f"Slack send failed: {e}")

        # Clean up streaming state
        self._active_messages.pop(chat_id, None)
        self._stream_buffers.pop(chat_id, None)

    async def send_stream_chunk(self, chat_id: str, chunk: StreamChunk) -> None:
        """Live-edit Slack message with streaming content."""
        if not self._client:
            return

        if chat_id not in self._stream_buffers:
            self._stream_buffers[chat_id] = ""

        self._stream_buffers[chat_id] = chunk.accumulated

        if chunk.is_final:
            msg_info = self._active_messages.get(chat_id)
            final_text = self._stream_buffers.pop(chat_id, chunk.accumulated)
            if msg_info:
                try:
                    if len(final_text) <= MESSAGE_LIMIT:
                        await self._client.chat_update(
                            channel=chat_id,
                            ts=msg_info["ts"],
                            text=final_text,
                        )
                    else:
                        # Delete streaming message, send split messages
                        await self._client.chat_delete(channel=chat_id, ts=msg_info["ts"])
                        for part in self._split_message(final_text, MESSAGE_LIMIT):
                            await self._client.chat_postMessage(channel=chat_id, text=part)
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
            msg_info = self._active_messages.get(chat_id)
            try:
                if msg_info is None:
                    resp = await self._client.chat_postMessage(
                        channel=chat_id, text=text + " ..."
                    )
                    self._active_messages[chat_id] = {
                        "ts": resp["ts"],
                        "channel": chat_id,
                    }
                else:
                    await self._client.chat_update(
                        channel=chat_id,
                        ts=msg_info["ts"],
                        text=text + " ...",
                    )
                self._last_edit_time[chat_id] = now
            except Exception as e:
                logger.debug(f"Slack edit failed: {e}")

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
