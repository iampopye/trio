"""Async MessageBus — decouples channels from agent loop."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class InboundMessage:
    """Message from a channel to the agent."""
    channel: str          # "discord", "telegram", "signal", "cli"
    chat_id: str          # Platform-specific chat/user ID
    user_id: str          # Platform-specific user ID
    content: str          # Text content
    media: list[dict] = field(default_factory=list)  # Images, voice, etc.
    metadata: dict = field(default_factory=dict)      # Platform-specific extras
    timestamp: float = field(default_factory=time.time)

    @property
    def session_key(self) -> str:
        return f"{self.channel}:{self.chat_id}"


@dataclass
class OutboundMessage:
    """Message from agent to a channel."""
    channel: str
    chat_id: str
    content: str
    is_streaming: bool = False
    is_final: bool = True
    metadata: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class StreamChunk:
    """A streaming chunk for real-time response delivery."""
    channel: str
    chat_id: str
    chunk: str
    accumulated: str     # Full text so far
    is_final: bool = False
    metadata: dict = field(default_factory=dict)


class MessageBus:
    """Async message routing between channels and agent.

    Architecture:
        Channel → inbound_queue → AgentLoop
        AgentLoop → outbound_queue → ChannelManager → Channel
    """

    def __init__(self):
        self._inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self._outbound: asyncio.Queue[OutboundMessage | StreamChunk] = asyncio.Queue()
        self._running = True

    async def publish_inbound(self, message: InboundMessage) -> None:
        """Channel publishes a user message."""
        await self._inbound.put(message)

    async def consume_inbound(self, timeout: float = 1.0) -> InboundMessage | None:
        """Agent loop consumes the next inbound message."""
        try:
            return await asyncio.wait_for(self._inbound.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def publish_outbound(self, message: OutboundMessage | StreamChunk) -> None:
        """Agent publishes a response or stream chunk."""
        await self._outbound.put(message)

    async def consume_outbound(self, timeout: float = 1.0) -> OutboundMessage | StreamChunk | None:
        """ChannelManager consumes the next outbound message."""
        try:
            return await asyncio.wait_for(self._outbound.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def stop(self) -> None:
        self._running = False

    @property
    def inbound_pending(self) -> int:
        return self._inbound.qsize()

    @property
    def outbound_pending(self) -> int:
        return self._outbound.qsize()
