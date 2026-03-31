"""Facebook Messenger channel — Meta Graph API integration.

Receives messages via a webhook endpoint and sends replies
using the Meta Send API for Messenger.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any

from trio.channels.base import BaseChannel
from trio.core.bus import MessageBus, StreamChunk

logger = logging.getLogger(__name__)

MESSAGE_LIMIT = 2000  # Messenger message character limit
GRAPH_API_URL = "https://graph.facebook.com/v21.0"


class MessengerChannel(BaseChannel):
    """Facebook Messenger channel via Meta Graph API."""

    def __init__(self, bus: MessageBus, config: dict):
        super().__init__(name="messenger", bus=bus, config=config)
        self._page_id = config.get("page_id", "")
        self._access_token = config.get("access_token", "")
        self._verify_token = config.get("verify_token", "trio_verify")
        self._app_secret = config.get("app_secret", "")
        self._webhook_port = config.get("webhook_port", 8087)
        self._webhook_host = config.get("webhook_host", "127.0.0.1")
        self._app = None
        self._runner = None
        self._session = None
        self._stream_buffers: dict[str, str] = {}

    async def start(self) -> None:
        """Start the webhook server for incoming Messenger messages."""
        import aiohttp
        import aiohttp.web as web

        self._session = aiohttp.ClientSession()

        self._app = web.Application()
        self._app.router.add_get("/messenger/webhook", self._handle_verify)
        self._app.router.add_post("/messenger/webhook", self._handle_message)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._webhook_host, self._webhook_port)
        await site.start()
        logger.info(f"Messenger webhook listening on port {self._webhook_port}")

    async def stop(self) -> None:
        """Stop the webhook server and close HTTP session."""
        if self._runner:
            await self._runner.cleanup()
        if self._session:
            await self._session.close()

    async def _handle_verify(self, request):
        """Handle Meta webhook verification challenge."""
        import aiohttp.web as web

        mode = request.query.get("hub.mode")
        token = request.query.get("hub.verify_token")
        challenge = request.query.get("hub.challenge")

        if mode == "subscribe" and token == self._verify_token:
            logger.info("Messenger webhook verified")
            return web.Response(text=challenge)

        return web.Response(status=403, text="Verification failed")

    async def _handle_message(self, request):
        """Handle incoming Messenger webhook events."""
        import aiohttp.web as web

        try:
            body = await request.read()

            # Verify signature if app_secret is configured
            if self._app_secret:
                signature = request.headers.get("X-Hub-Signature-256", "")
                expected = "sha256=" + hmac.new(
                    self._app_secret.encode(),
                    body,
                    hashlib.sha256,
                ).hexdigest()
                if not hmac.compare_digest(signature, expected):
                    return web.Response(status=403, text="Invalid signature")

            data = json.loads(body)

            # Only process page events
            if data.get("object") != "page":
                return web.Response(text="EVENT_RECEIVED", status=200)

            for entry in data.get("entry", []):
                for messaging_event in entry.get("messaging", []):
                    message = messaging_event.get("message", {})
                    text = message.get("text", "").strip()

                    if not text:
                        continue

                    # Skip echo messages (our own sends)
                    if message.get("is_echo"):
                        continue

                    sender_id = messaging_event.get("sender", {}).get("id", "")
                    chat_id = sender_id  # Use sender PSID as conversation ID

                    await self.publish_inbound(
                        chat_id=chat_id,
                        user_id=sender_id,
                        content=text,
                    )

            return web.Response(text="EVENT_RECEIVED", status=200)

        except Exception as e:
            logger.error(f"Messenger webhook error: {e}")
            return web.Response(status=200, text="EVENT_RECEIVED")

    async def send_message(self, chat_id: str, content: str) -> None:
        """Send a message via the Messenger Send API."""
        if not self._session:
            logger.warning("Messenger: HTTP session not initialized")
            return

        # Split long messages
        chunks = self._split_message(content, MESSAGE_LIMIT)
        for chunk in chunks:
            url = f"{GRAPH_API_URL}/{self._page_id}/messages"
            payload = {
                "recipient": {"id": chat_id},
                "messaging_type": "RESPONSE",
                "message": {"text": chunk},
            }
            params = {"access_token": self._access_token}

            try:
                async with self._session.post(
                    url, json=payload, params=params
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(
                            f"Messenger send failed ({resp.status}): {body}"
                        )
            except Exception as e:
                logger.error(f"Messenger send error: {e}")

        self._stream_buffers.pop(chat_id, None)

    async def send_stream_chunk(self, chat_id: str, chunk: StreamChunk) -> None:
        """Buffer streaming chunks and send final message."""
        if chat_id not in self._stream_buffers:
            self._stream_buffers[chat_id] = ""

        self._stream_buffers[chat_id] = chunk.accumulated

        if chunk.is_final:
            final_text = self._stream_buffers.pop(chat_id, chunk.accumulated)
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
