"""SMS channel — Twilio API integration for sending and receiving SMS.

Receives inbound SMS via a webhook endpoint and sends outbound SMS
via the Twilio REST API.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import logging
from typing import Any

from trio.channels.base import BaseChannel
from trio.core.bus import MessageBus, StreamChunk

logger = logging.getLogger(__name__)

MESSAGE_LIMIT = 1600  # SMS segment limit (Twilio concatenates, but keep reasonable)


class SMSChannel(BaseChannel):
    """SMS channel via Twilio API."""

    def __init__(self, bus: MessageBus, config: dict):
        super().__init__(name="sms", bus=bus, config=config)
        self._account_sid = config.get("account_sid", "")
        self._auth_token = config.get("auth_token", "")
        self._phone_number = config.get("phone_number", "")  # Twilio phone number
        self._webhook_port = config.get("webhook_port", 8085)
        self._webhook_host = config.get("webhook_host", "127.0.0.1")
        self._twilio_client = None
        self._app = None
        self._runner = None
        self._stream_buffers: dict[str, str] = {}

    async def start(self) -> None:
        """Start the webhook server for incoming SMS."""
        try:
            from twilio.rest import Client as TwilioClient
        except ImportError:
            raise ImportError(
                "twilio required. Install: pip install trio-ai[sms]"
            )

        import aiohttp.web as web

        self._twilio_client = TwilioClient(self._account_sid, self._auth_token)

        self._app = web.Application()
        self._app.router.add_post("/sms/webhook", self._handle_inbound)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._webhook_host, self._webhook_port)
        await site.start()
        logger.info(
            f"SMS webhook listening on port {self._webhook_port} "
            f"(Twilio number: {self._phone_number})"
        )

    async def stop(self) -> None:
        """Stop the webhook server."""
        if self._runner:
            await self._runner.cleanup()

    async def _handle_inbound(self, request):
        """Handle incoming SMS from Twilio webhook."""
        import aiohttp.web as web

        try:
            data = await request.post()
            body = data.get("Body", "").strip()
            from_number = data.get("From", "")

            if not body:
                return web.Response(
                    text='<Response></Response>',
                    content_type="application/xml",
                )

            # Use phone number as both chat_id and user_id
            chat_id = from_number
            user_id = from_number

            await self.publish_inbound(
                chat_id=chat_id,
                user_id=user_id,
                content=body,
                phone_number=from_number,
            )

            # Return empty TwiML response (we send replies asynchronously)
            return web.Response(
                text='<Response></Response>',
                content_type="application/xml",
            )

        except Exception as e:
            logger.error(f"SMS webhook error: {e}")
            return web.Response(
                text='<Response></Response>',
                content_type="application/xml",
                status=200,
            )

    async def send_message(self, chat_id: str, content: str) -> None:
        """Send an SMS message via Twilio."""
        if not self._twilio_client:
            logger.warning("SMS: Twilio client not initialized")
            return

        # Split long messages
        chunks = self._split_message(content, MESSAGE_LIMIT)
        for chunk in chunks:
            try:
                # Run Twilio API call in thread pool (it's synchronous)
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    lambda: self._twilio_client.messages.create(
                        body=chunk,
                        from_=self._phone_number,
                        to=chat_id,
                    ),
                )
            except Exception as e:
                logger.error(f"SMS send error to {chat_id}: {e}")

        self._stream_buffers.pop(chat_id, None)

    async def send_stream_chunk(self, chat_id: str, chunk: StreamChunk) -> None:
        """Buffer streaming chunks and send final message.

        SMS does not support editing, so we only send the final result.
        """
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
