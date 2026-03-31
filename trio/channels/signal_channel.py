"""Signal channel — async signal-cli JSON-RPC integration.

Extracted from BotServer's signal_bot.py with channel abstraction.
Keeps: async JSON-RPC, group support, typing indicators, auto-reconnect.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import json
import logging
from typing import Any

from trio.channels.base import BaseChannel
from trio.core.bus import MessageBus, StreamChunk, OutboundMessage

logger = logging.getLogger(__name__)

MESSAGE_LIMIT = 4000


class SignalChannel(BaseChannel):
    """Signal bot channel via signal-cli JSON-RPC daemon."""

    def __init__(self, bus: MessageBus, config: dict):
        super().__init__(name="signal", bus=bus, config=config)
        self._phone = config.get("phone", "")
        self._host = config.get("host", "localhost")
        self._port = config.get("port", 7583)
        self._reader = None
        self._writer = None
        self._running = True
        self._request_id = 0
        self._stream_buffers: dict[str, str] = {}

    async def start(self) -> None:
        """Connect to signal-cli JSON-RPC daemon and start listening."""
        await self._connect()
        asyncio.create_task(self._listen_loop())
        logger.info(f"Signal channel connected ({self._host}:{self._port})")

    async def stop(self) -> None:
        self._running = False
        if self._writer:
            self._writer.close()

    async def _connect(self) -> None:
        """Connect to signal-cli daemon."""
        self._reader, self._writer = await asyncio.open_connection(
            self._host, self._port,
        )

    async def _listen_loop(self) -> None:
        """Listen for incoming messages from signal-cli."""
        while self._running:
            try:
                if self._reader is None:
                    await self._connect()

                line = await self._reader.readline()
                if not line:
                    logger.warning("Signal connection closed, reconnecting...")
                    await asyncio.sleep(5)
                    await self._connect()
                    continue

                data = json.loads(line.decode())
                await self._handle_signal_message(data)

            except (ConnectionError, OSError) as e:
                logger.warning(f"Signal connection error: {e}, reconnecting...")
                await asyncio.sleep(5)
                try:
                    await self._connect()
                except Exception:
                    pass  # nosec B110 — intentional silent fallback
            except json.JSONDecodeError:
                continue
            except Exception as e:
                logger.error(f"Signal listen error: {e}")
                await asyncio.sleep(1)

    async def _handle_signal_message(self, data: dict) -> None:
        """Process a message from signal-cli."""
        # signal-cli JSON-RPC format
        method = data.get("method", "")
        if method != "receive":
            return

        params = data.get("params", {})
        envelope = params.get("envelope", {})
        data_msg = envelope.get("dataMessage", {})

        message = data_msg.get("message", "")
        if not message:
            return

        source = envelope.get("source", "")
        group_info = data_msg.get("groupInfo", {})
        group_id = group_info.get("groupId", "")

        chat_id = group_id if group_id else source
        user_id = source

        await self.publish_inbound(
            chat_id=chat_id,
            user_id=user_id,
            content=message,
            is_group=bool(group_id),
            group_id=group_id,
        )

    async def send_message(self, chat_id: str, content: str) -> None:
        """Send a message via signal-cli JSON-RPC."""
        # Split long messages
        parts = self._split_message(content, MESSAGE_LIMIT)
        for part in parts:
            await self._signal_send(chat_id, part)

        self._stream_buffers.pop(chat_id, None)

    async def send_stream_chunk(self, chat_id: str, chunk: StreamChunk) -> None:
        """Signal doesn't support editing — buffer until final."""
        if chat_id not in self._stream_buffers:
            self._stream_buffers[chat_id] = ""

        self._stream_buffers[chat_id] = chunk.accumulated

        # Send typing indicator
        if not chunk.is_final:
            await self._send_typing(chat_id)
            return

        # Final — send the complete response
        final_text = self._stream_buffers.pop(chat_id, chunk.accumulated)
        await self.send_message(chat_id, final_text)

    async def _signal_send(self, recipient: str, message: str) -> None:
        """Send via signal-cli JSON-RPC."""
        if not self._writer:
            logger.error("Signal: not connected")
            return

        self._request_id += 1

        # Determine if group or direct message
        if len(recipient) > 20:  # Group IDs are long base64 strings
            request = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": "send",
                "params": {
                    "account": self._phone,
                    "groupId": recipient,
                    "message": message,
                },
            }
        else:
            request = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": "send",
                "params": {
                    "account": self._phone,
                    "recipient": [recipient],
                    "message": message,
                },
            }

        try:
            data = json.dumps(request) + "\n"
            self._writer.write(data.encode())
            await self._writer.drain()
        except Exception as e:
            logger.error(f"Signal send failed: {e}")

    async def _send_typing(self, recipient: str) -> None:
        """Send typing indicator."""
        if not self._writer:
            return

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "sendTyping",
            "params": {
                "account": self._phone,
                "recipient": [recipient] if len(recipient) <= 20 else [],
                "groupId": recipient if len(recipient) > 20 else "",
            },
        }

        try:
            data = json.dumps(request) + "\n"
            self._writer.write(data.encode())
            await self._writer.drain()
        except Exception:
            pass  # nosec B110 — intentional silent fallback

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
