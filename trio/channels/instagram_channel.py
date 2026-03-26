"""Instagram channel — Instagram DM via Meta Graph API.

Receives direct messages via a webhook endpoint and sends replies
using the Meta Graph API (Instagram Messaging).
"""

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any

from trio.channels.base import BaseChannel
from trio.core.bus import MessageBus, StreamChunk

logger = logging.getLogger(__name__)

MESSAGE_LIMIT = 1000  # Instagram message character limit
GRAPH_API_URL = "https://graph.instagram.com/v21.0"


class InstagramChannel(BaseChannel):
    """Instagram DM channel via Meta Graph API."""

    def __init__(self, bus: MessageBus, config: dict):
        super().__init__(name="instagram", bus=bus, config=config)
        self._page_id = config.get("page_id", "")
        self._access_token = config.get("access_token", "")
        self._verify_token = config.get("verify_token", "trio_verify")
        self._app_secret = config.get("app_secret", "")
        self._webhook_port = config.get("webhook_port", 8086)
        self._app = None
        self._runner = None
        self._session = None
        self._stream_buffers: dict[str, str] = {}

    async def start(self) -> None:
        """Start the webhook server for incoming Instagram DMs."""
        import aiohttp
        import aiohttp.web as web

        self._session = aiohttp.ClientSession()

        self._app = web.Application()
        self._app.router.add_get("/instagram/webhook", self._handle_verify)
        self._app.router.add_post("/instagram/webhook", self._handle_message)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self._webhook_port)
        await site.start()
        logger.info(f"Instagram webhook listening on port {self._webhook_port}")

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
            logger.info("Instagram webhook verified")
            return web.Response(text=challenge)

        return web.Response(status=403, text="Verification failed")

    async def _handle_message(self, request):
        """Handle incoming Instagram DM webhook events."""
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

            # Process messaging events
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
                    chat_id = sender_id  # DMs use sender ID as conversation ID

                    await self.publish_inbound(
                        chat_id=chat_id,
                        user_id=sender_id,
                        content=text,
                    )

            return web.Response(text="EVENT_RECEIVED", status=200)

        except Exception as e:
            logger.error(f"Instagram webhook error: {e}")
            return web.Response(status=200, text="EVENT_RECEIVED")

    async def send_message(self, chat_id: str, content: str) -> None:
        """Send a DM via the Instagram Graph API."""
        if not self._session:
            logger.warning("Instagram: HTTP session not initialized")
            return

        # Split long messages
        chunks = self._split_message(content, MESSAGE_LIMIT)
        for chunk in chunks:
            url = f"{GRAPH_API_URL}/{self._page_id}/messages"
            payload = {
                "recipient": {"id": chat_id},
                "message": {"text": chunk},
            }
            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            }

            try:
                async with self._session.post(
                    url, json=payload, headers=headers
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(
                            f"Instagram send failed ({resp.status}): {body}"
                        )
            except Exception as e:
                logger.error(f"Instagram send error: {e}")

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
