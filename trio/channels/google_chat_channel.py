"""Google Chat channel — Google Chat API via webhook + service account."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import logging
from typing import Any

from trio.channels.base import BaseChannel
from trio.core.bus import MessageBus, StreamChunk

logger = logging.getLogger(__name__)

MESSAGE_LIMIT = 4096


class GoogleChatChannel(BaseChannel):
    """Google Chat bot via webhook server and Chat API."""

    def __init__(self, bus: MessageBus, config: dict):
        super().__init__(name="google_chat", bus=bus, config=config)
        self._service_account_file = config.get("service_account_file", "")
        self._webhook_port = config.get("webhook_port", 8090)
        self._webhook_host = config.get("webhook_host", "127.0.0.1")
        self._runner = None
        self._credentials = None
        self._spaces: dict[str, str] = {}  # chat_id → space_name

    async def start(self) -> None:
        """Start the Google Chat webhook server."""
        import aiohttp.web as web

        # Initialize credentials if service account provided
        if self._service_account_file:
            try:
                from google.oauth2 import service_account

                self._credentials = service_account.Credentials.from_service_account_file(
                    self._service_account_file,
                    scopes=["https://www.googleapis.com/auth/chat.bot"],
                )
            except ImportError:
                raise ImportError(
                    "google-auth required. Install: pip install trio-ai[google_chat]"
                )
            except Exception as e:
                logger.error(f"Google Chat credentials error: {e}")

        app = web.Application()
        app.router.add_post("/google-chat", self._handle_event)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._webhook_host, self._webhook_port)
        await site.start()
        logger.info(f"Google Chat webhook listening on port {self._webhook_port}")

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    async def _handle_event(self, request):
        """Handle incoming Google Chat events."""
        import aiohttp.web as web

        try:
            data = await request.json()
        except Exception:
            return web.Response(status=400)

        event_type = data.get("type", "")

        if event_type == "MESSAGE":
            message = data.get("message", {})
            text = message.get("argumentText", "") or message.get("text", "")
            sender = message.get("sender", {})
            user_id = sender.get("name", "unknown")
            space = data.get("space", {})
            space_name = space.get("name", "")
            chat_id = space_name

            # Store space reference
            self._spaces[chat_id] = space_name

            if text.strip():
                await self.publish_inbound(
                    chat_id=chat_id,
                    user_id=user_id,
                    content=text.strip(),
                )

        elif event_type == "ADDED_TO_SPACE":
            logger.info(f"Google Chat: added to space {data.get('space', {}).get('name')}")

        # Respond with empty JSON (acknowledgement)
        return web.json_response({})

    async def send_message(self, chat_id: str, content: str) -> None:
        """Send a message via Google Chat API."""
        if not self._credentials:
            logger.warning("Google Chat: no credentials configured")
            return

        try:
            from googleapiclient.discovery import build
            import google.auth.transport.requests

            # Refresh credentials
            request = google.auth.transport.requests.Request()
            self._credentials.refresh(request)

            service = build("chat", "v1", credentials=self._credentials)

            # Truncate if needed
            text = content[:MESSAGE_LIMIT] if len(content) > MESSAGE_LIMIT else content

            service.spaces().messages().create(
                parent=chat_id,
                body={"text": text},
            ).execute()

        except Exception as e:
            logger.error(f"Google Chat send failed: {e}")

    async def send_stream_chunk(self, chat_id: str, chunk: StreamChunk) -> None:
        """Buffer until final — Google Chat has limited edit support."""
        if chunk.is_final:
            await self.send_message(chat_id, chunk.accumulated)
