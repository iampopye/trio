"""Microsoft Teams channel — Bot Framework SDK via aiohttp webhook."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import logging
from typing import Any

from trio.channels.base import BaseChannel
from trio.core.bus import MessageBus, StreamChunk

logger = logging.getLogger(__name__)

MESSAGE_LIMIT = 28000  # Teams supports ~28KB


class TeamsChannel(BaseChannel):
    """Microsoft Teams bot via Bot Framework SDK."""

    def __init__(self, bus: MessageBus, config: dict):
        super().__init__(name="teams", bus=bus, config=config)
        self._app_id = config.get("app_id", "")
        self._app_password = config.get("app_password", "")
        self._webhook_port = config.get("webhook_port", 3978)
        self._webhook_host = config.get("webhook_host", "127.0.0.1")
        self._adapter = None
        self._runner = None
        self._conversations: dict[str, Any] = {}  # chat_id → conversation_ref
        self._stream_buffers: dict[str, str] = {}

    async def start(self) -> None:
        """Start the Bot Framework webhook server."""
        try:
            from botbuilder.core import (
                BotFrameworkAdapter,
                BotFrameworkAdapterSettings,
                TurnContext,
            )
            from botbuilder.schema import Activity, ActivityTypes
            import aiohttp.web as web
        except ImportError:
            raise ImportError(
                "botbuilder-core required. Install: pip install trio-ai[teams]"
            )

        settings = BotFrameworkAdapterSettings(self._app_id, self._app_password)
        self._adapter = BotFrameworkAdapter(settings)

        async def on_turn(turn_context: TurnContext):
            if turn_context.activity.type == ActivityTypes.message:
                text = turn_context.activity.text or ""
                chat_id = turn_context.activity.conversation.id
                user_id = turn_context.activity.from_property.id

                # Store conversation reference for proactive messaging
                self._conversations[chat_id] = TurnContext.get_conversation_reference(
                    turn_context.activity
                )

                if text.strip():
                    await self.publish_inbound(
                        chat_id=chat_id,
                        user_id=user_id,
                        content=text.strip(),
                    )

        async def handle_messages(request):
            body = await request.json()
            activity = Activity().deserialize(body)
            auth_header = request.headers.get("Authorization", "")
            response = await self._adapter.process_activity(
                activity, auth_header, on_turn
            )
            if response:
                return web.json_response(data=response.body, status=response.status)
            return web.Response(status=201)

        app = web.Application()
        app.router.add_post("/api/messages", handle_messages)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._webhook_host, self._webhook_port)
        await site.start()
        logger.info(f"Teams webhook listening on port {self._webhook_port}")

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    async def send_message(self, chat_id: str, content: str) -> None:
        """Send a message to a Teams conversation."""
        if not self._adapter:
            return

        conv_ref = self._conversations.get(chat_id)
        if not conv_ref:
            logger.warning(f"Teams: no conversation ref for {chat_id}")
            return

        try:
            from botbuilder.schema import Activity, ActivityTypes

            async def send_callback(turn_context):
                activity = Activity(
                    type=ActivityTypes.message,
                    text=content[:MESSAGE_LIMIT],
                )
                await turn_context.send_activity(activity)

            await self._adapter.continue_conversation(conv_ref, send_callback, self._app_id)
        except Exception as e:
            logger.error(f"Teams send failed: {e}")

    async def send_stream_chunk(self, chat_id: str, chunk: StreamChunk) -> None:
        """Teams supports message updating — live edit during streaming."""
        if chunk.is_final:
            await self.send_message(chat_id, chunk.accumulated)
