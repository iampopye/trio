"""WhatsApp channel — WhatsApp Business Cloud API via webhook."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import logging
from typing import Any

from trio.channels.base import BaseChannel
from trio.core.bus import MessageBus, StreamChunk

logger = logging.getLogger(__name__)

MESSAGE_LIMIT = 4096


class WhatsAppChannel(BaseChannel):
    """WhatsApp Business Cloud API channel via aiohttp webhook."""

    def __init__(self, bus: MessageBus, config: dict):
        super().__init__(name="whatsapp", bus=bus, config=config)
        self._phone_number_id = config.get("phone_number_id", "")
        self._access_token = config.get("access_token", "")
        self._verify_token = config.get("verify_token", "trio_verify")
        self._webhook_port = config.get("webhook_port", 8080)
        self._webhook_host = config.get("webhook_host", "127.0.0.1")
        self._app = None
        self._runner = None
        self._stream_buffers: dict[str, str] = {}

    async def start(self) -> None:
        """Start the webhook server."""
        import aiohttp.web as web

        self._app = web.Application()
        self._app.router.add_get("/webhook", self._handle_verify)
        self._app.router.add_post("/webhook", self._handle_message)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._webhook_host, self._webhook_port)
        await site.start()
        logger.info(f"WhatsApp webhook listening on port {self._webhook_port}")

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    async def _handle_verify(self, request):
        """Handle WhatsApp webhook verification challenge."""
        import aiohttp.web as web

        mode = request.query.get("hub.mode")
        token = request.query.get("hub.verify_token")
        challenge = request.query.get("hub.challenge")

        if mode == "subscribe" and token == self._verify_token:
            return web.Response(text=challenge)
        return web.Response(status=403, text="Forbidden")

    async def _handle_message(self, request):
        """Handle incoming WhatsApp messages."""
        import aiohttp.web as web

        try:
            data = await request.json()
        except Exception:
            return web.Response(status=400)

        # Parse WhatsApp Cloud API payload
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for message in value.get("messages", []):
                    if message.get("type") == "text":
                        sender = message.get("from", "")
                        text = message.get("text", {}).get("body", "")
                        if text:
                            await self.publish_inbound(
                                chat_id=sender,
                                user_id=sender,
                                content=text,
                            )

        return web.Response(status=200, text="OK")

    async def send_message(self, chat_id: str, content: str) -> None:
        """Send a message via WhatsApp Cloud API."""
        import aiohttp

        url = f"https://graph.facebook.com/v18.0/{self._phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

        # Split long messages
        chunks = self._split_message(content, MESSAGE_LIMIT)
        async with aiohttp.ClientSession() as session:
            for chunk in chunks:
                payload = {
                    "messaging_product": "whatsapp",
                    "to": chat_id,
                    "type": "text",
                    "text": {"body": chunk},
                }
                try:
                    async with session.post(url, json=payload, headers=headers) as resp:
                        if resp.status != 200:
                            body = await resp.text()
                            logger.error(f"WhatsApp send failed ({resp.status}): {body}")
                except Exception as e:
                    logger.error(f"WhatsApp send error: {e}")

    async def send_stream_chunk(self, chat_id: str, chunk: StreamChunk) -> None:
        """WhatsApp doesn't support message editing — buffer until final."""
        if chunk.is_final:
            await self.send_message(chat_id, chunk.accumulated)

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
