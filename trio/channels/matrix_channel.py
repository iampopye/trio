"""Matrix channel — matrix-nio integration for Matrix/Element rooms.

Connects to a Matrix homeserver using the matrix-nio library.
Receives messages from joined rooms and sends replies back.
"""

import asyncio
import logging
from typing import Any

from trio.channels.base import BaseChannel
from trio.core.bus import MessageBus, StreamChunk

logger = logging.getLogger(__name__)

MESSAGE_LIMIT = 65536  # Matrix has a generous message limit


class MatrixChannel(BaseChannel):
    """Matrix/Element channel via matrix-nio."""

    def __init__(self, bus: MessageBus, config: dict):
        super().__init__(name="matrix", bus=bus, config=config)
        self._client = None
        self._homeserver_url = config.get("homeserver_url", "https://matrix.org")
        self._user_id = config.get("user_id", "")
        self._access_token = config.get("access_token", "")
        self._stream_buffers: dict[str, str] = {}

    async def start(self) -> None:
        """Start the Matrix client and begin syncing."""
        try:
            from nio import AsyncClient, MatrixRoom, RoomMessageText
        except ImportError:
            raise ImportError(
                "matrix-nio required. Install: pip install trio-ai[matrix]"
            )

        self._client = AsyncClient(self._homeserver_url, self._user_id)
        self._client.access_token = self._access_token

        # Store reference to nio types for callbacks
        _RoomMessageText = RoomMessageText
        _MatrixRoom = MatrixRoom

        async def message_callback(room: _MatrixRoom, event: _RoomMessageText):
            # Ignore our own messages
            if event.sender == self._user_id:
                return

            content = event.body
            if not content:
                return

            chat_id = room.room_id
            user_id = event.sender

            await self.publish_inbound(
                chat_id=chat_id,
                user_id=user_id,
                content=content,
                room_name=room.display_name,
                author_name=room.user_name(event.sender) or event.sender,
            )

        self._client.add_event_callback(message_callback, RoomMessageText)

        # Do an initial sync to skip old messages
        logger.info(f"Matrix: connecting to {self._homeserver_url} as {self._user_id}")
        resp = await self._client.sync(timeout=10000, full_state=True)
        if hasattr(resp, "next_batch"):
            self._client.next_batch = resp.next_batch

        logger.info("Matrix: connected and syncing")

        # Start continuous sync in background
        asyncio.create_task(self._sync_loop())

    async def _sync_loop(self) -> None:
        """Continuously sync with the Matrix homeserver."""
        while self._client:
            try:
                await self._client.sync(timeout=30000)
            except Exception as e:
                logger.error(f"Matrix sync error: {e}")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """Disconnect from the Matrix homeserver."""
        if self._client:
            await self._client.close()
            self._client = None

    async def send_message(self, chat_id: str, content: str) -> None:
        """Send a message to a Matrix room."""
        if not self._client:
            logger.warning("Matrix: client not connected")
            return

        try:
            from nio import RoomSendResponse
        except ImportError:
            return

        # Split long messages if needed
        chunks = self._split_message(content, MESSAGE_LIMIT)
        for chunk in chunks:
            await self._client.room_send(
                room_id=chat_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": chunk,
                    "format": "org.matrix.custom.html",
                    "formatted_body": self._markdown_to_html(chunk),
                },
            )

        self._stream_buffers.pop(chat_id, None)

    async def send_stream_chunk(self, chat_id: str, chunk: StreamChunk) -> None:
        """Buffer streaming chunks and send final message.

        Matrix does not support message editing as easily as Discord,
        so we buffer and send only the final result.
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

    @staticmethod
    def _markdown_to_html(text: str) -> str:
        """Basic markdown to HTML conversion for Matrix formatted messages."""
        # Matrix supports a subset of HTML. For now, pass through as-is.
        # A full implementation would use a markdown parser.
        import html
        return html.escape(text).replace("\n", "<br>")
