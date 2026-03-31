"""LINE channel — LINE Messaging API via LINE Bot SDK.

Receives messages via a webhook endpoint and sends replies
using the LINE Messaging API.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import hashlib
import hmac
import base64
import json
import logging
from typing import Any

from trio.channels.base import BaseChannel
from trio.core.bus import MessageBus, StreamChunk

logger = logging.getLogger(__name__)

MESSAGE_LIMIT = 5000  # LINE text message character limit
LINE_API_URL = "https://api.line.me/v2/bot"


class LINEChannel(BaseChannel):
    """LINE messaging channel via LINE Bot SDK."""

    def __init__(self, bus: MessageBus, config: dict):
        super().__init__(name="line", bus=bus, config=config)
        self._channel_access_token = config.get("channel_access_token", "")
        self._channel_secret = config.get("channel_secret", "")
        self._webhook_port = config.get("webhook_port", 8088)
        self._app = None
        self._runner = None
        self._session = None
        self._stream_buffers: dict[str, str] = {}

    async def start(self) -> None:
        """Start the webhook server for incoming LINE messages."""
        import aiohttp
        import aiohttp.web as web

        self._session = aiohttp.ClientSession()

        self._app = web.Application()
        self._app.router.add_post("/line/webhook", self._handle_webhook)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self._webhook_port)
        await site.start()
        logger.info(f"LINE webhook listening on port {self._webhook_port}")

    async def stop(self) -> None:
        """Stop the webhook server and close HTTP session."""
        if self._runner:
            await self._runner.cleanup()
        if self._session:
            await self._session.close()

    def _verify_signature(self, body: bytes, signature: str) -> bool:
        """Verify the LINE webhook signature."""
        mac = hmac.new(
            self._channel_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        )
        expected = base64.b64encode(mac.digest()).decode("utf-8")
        return hmac.compare_digest(signature, expected)

    async def _handle_webhook(self, request):
        """Handle incoming LINE webhook events."""
        import aiohttp.web as web

        try:
            body = await request.read()
            signature = request.headers.get("X-Line-Signature", "")

            # Verify signature
            if self._channel_secret and not self._verify_signature(body, signature):
                logger.warning("LINE: invalid webhook signature")
                return web.Response(status=403, text="Invalid signature")

            data = json.loads(body)

            for event in data.get("events", []):
                event_type = event.get("type")

                if event_type != "message":
                    continue

                message = event.get("message", {})
                if message.get("type") != "text":
                    continue

                text = message.get("text", "").strip()
                if not text:
                    continue

                source = event.get("source", {})
                source_type = source.get("type", "user")

                # Determine chat_id based on source type
                if source_type == "group":
                    chat_id = source.get("groupId", "")
                elif source_type == "room":
                    chat_id = source.get("roomId", "")
                else:
                    chat_id = source.get("userId", "")

                user_id = source.get("userId", "")
                reply_token = event.get("replyToken", "")

                # Store reply token for immediate reply
                if reply_token:
                    self._stream_buffers[f"reply_{chat_id}"] = reply_token

                await self.publish_inbound(
                    chat_id=chat_id,
                    user_id=user_id,
                    content=text,
                    reply_token=reply_token,
                )

            return web.Response(text="OK", status=200)

        except Exception as e:
            logger.error(f"LINE webhook error: {e}")
            return web.Response(status=200, text="OK")

    async def send_message(self, chat_id: str, content: str) -> None:
        """Send a message via the LINE Messaging API.

        First tries to use the reply token (free), then falls back
        to the push message API.
        """
        if not self._session:
            logger.warning("LINE: HTTP session not initialized")
            return

        # Check for reply token first
        reply_token = self._stream_buffers.pop(f"reply_{chat_id}", None)

        # Split long messages
        chunks = self._split_message(content, MESSAGE_LIMIT)

        # Build LINE message objects
        messages = [{"type": "text", "text": chunk} for chunk in chunks[:5]]  # LINE max 5 messages per reply

        headers = {
            "Authorization": f"Bearer {self._channel_access_token}",
            "Content-Type": "application/json",
        }

        if reply_token:
            # Use reply API (free)
            url = f"{LINE_API_URL}/message/reply"
            payload = {
                "replyToken": reply_token,
                "messages": messages,
            }
        else:
            # Use push API (costs money)
            url = f"{LINE_API_URL}/message/push"
            payload = {
                "to": chat_id,
                "messages": messages,
            }

        try:
            async with self._session.post(
                url, json=payload, headers=headers
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(f"LINE send failed ({resp.status}): {body}")
                    # If reply failed, try push as fallback
                    if reply_token:
                        await self._push_message(chat_id, messages, headers)
        except Exception as e:
            logger.error(f"LINE send error: {e}")

        self._stream_buffers.pop(chat_id, None)

    async def _push_message(
        self, chat_id: str, messages: list[dict], headers: dict
    ) -> None:
        """Fallback: send via push API."""
        url = f"{LINE_API_URL}/message/push"
        payload = {"to": chat_id, "messages": messages}

        try:
            async with self._session.post(
                url, json=payload, headers=headers
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(f"LINE push failed ({resp.status}): {body}")
        except Exception as e:
            logger.error(f"LINE push error: {e}")

    async def send_stream_chunk(self, chat_id: str, chunk: StreamChunk) -> None:
        """Buffer streaming chunks and send final message."""
        buf_key = chat_id
        if buf_key not in self._stream_buffers:
            self._stream_buffers[buf_key] = ""

        self._stream_buffers[buf_key] = chunk.accumulated

        if chunk.is_final:
            final_text = self._stream_buffers.pop(buf_key, chunk.accumulated)
            await self.send_message(chat_id, final_text)

    def _split_message(self, text: str, limit: int) -> list[str]:
        """Split message at limit boundaries."""
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
