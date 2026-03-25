"""Base channel interface and channel manager."""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

from trio.core.bus import InboundMessage, OutboundMessage, StreamChunk, MessageBus

logger = logging.getLogger(__name__)


class BaseChannel(ABC):
    """Abstract base for all chat platform channels.

    Each channel:
        - Converts platform events → InboundMessage → MessageBus
        - Receives OutboundMessage/StreamChunk from bus → sends to platform
    """

    def __init__(self, name: str, bus: MessageBus, config: dict):
        self.name = name
        self.bus = bus
        self.config = config

    @abstractmethod
    async def start(self) -> None:
        """Start the channel (connect to platform, begin listening)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel gracefully."""
        ...

    @abstractmethod
    async def send_message(self, chat_id: str, content: str) -> None:
        """Send a complete message to a chat."""
        ...

    async def send_stream_chunk(self, chat_id: str, chunk: StreamChunk) -> None:
        """Handle a streaming chunk. Default: buffer until final."""
        # Subclasses can override for live-editing (Discord, Telegram)
        if chunk.is_final:
            await self.send_message(chat_id, chunk.accumulated)

    async def publish_inbound(self, chat_id: str, user_id: str, content: str, **metadata) -> None:
        """Helper: publish an inbound message to the bus."""
        await self.bus.publish_inbound(InboundMessage(
            channel=self.name,
            chat_id=chat_id,
            user_id=user_id,
            content=content,
            metadata=metadata,
        ))


class ChannelManager:
    """Manages all active channels and routes outbound messages."""

    def __init__(self, bus: MessageBus):
        self.bus = bus
        self._channels: dict[str, BaseChannel] = {}
        self._running = True

    def register(self, channel: BaseChannel) -> None:
        self._channels[channel.name] = channel
        logger.info(f"Registered channel: {channel.name}")

    async def start_all(self) -> None:
        """Start all channels and begin routing outbound messages."""
        # Start each channel
        for channel in self._channels.values():
            try:
                await channel.start()
                logger.info(f"Channel '{channel.name}' started")
            except Exception as e:
                logger.error(f"Failed to start channel '{channel.name}': {e}")

        # Route outbound messages
        await self._route_outbound()

    async def stop_all(self) -> None:
        self._running = False
        for channel in self._channels.values():
            try:
                await channel.stop()
            except Exception:
                pass

    async def _route_outbound(self) -> None:
        """Consume outbound messages and route to correct channel."""
        while self._running:
            msg = await self.bus.consume_outbound(timeout=0.1)
            if msg is None:
                continue

            channel = self._channels.get(msg.channel)
            if channel is None:
                logger.warning(f"No channel '{msg.channel}' for outbound message")
                continue

            try:
                if isinstance(msg, StreamChunk):
                    await channel.send_stream_chunk(msg.chat_id, msg)
                elif isinstance(msg, OutboundMessage):
                    if msg.is_final:
                        await channel.send_message(msg.chat_id, msg.content)
                    # Non-final outbound messages are stream intermediates, skip
            except Exception as e:
                logger.error(f"Failed to route to '{msg.channel}': {e}")
