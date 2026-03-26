"""Reddit channel — Reddit bot using PRAW (Python Reddit API Wrapper).

Polls for new mentions and DMs, and replies via the Reddit API.
"""

import asyncio
import logging
from typing import Any

from trio.channels.base import BaseChannel
from trio.core.bus import MessageBus, StreamChunk

logger = logging.getLogger(__name__)

MESSAGE_LIMIT = 10000  # Reddit comment character limit


class RedditChannel(BaseChannel):
    """Reddit bot channel via PRAW."""

    def __init__(self, bus: MessageBus, config: dict):
        super().__init__(name="reddit", bus=bus, config=config)
        self._client_id = config.get("client_id", "")
        self._client_secret = config.get("client_secret", "")
        self._username = config.get("username", "")
        self._password = config.get("password", "")
        self._user_agent = config.get("user_agent", "trio-ai bot v1.0")
        self._poll_interval = config.get("poll_interval", 30)  # seconds
        self._subreddits = config.get("subreddits", [])  # Optional: monitor specific subs
        self._reddit = None
        self._running = False
        self._stream_buffers: dict[str, str] = {}
        self._reply_targets: dict[str, Any] = {}  # chat_id -> praw object to reply to

    async def start(self) -> None:
        """Start the Reddit bot and begin polling."""
        try:
            import praw
        except ImportError:
            raise ImportError(
                "praw required. Install: pip install trio-ai[reddit]"
            )

        self._reddit = praw.Reddit(
            client_id=self._client_id,
            client_secret=self._client_secret,
            username=self._username,
            password=self._password,
            user_agent=self._user_agent,
        )

        self._running = True
        logger.info(f"Reddit: logged in as u/{self._username}")

        # Start polling in background
        asyncio.create_task(self._poll_mentions())
        asyncio.create_task(self._poll_dms())

    async def stop(self) -> None:
        """Stop polling."""
        self._running = False

    async def _poll_mentions(self) -> None:
        """Poll for username mentions in comments."""
        if not self._reddit:
            return

        loop = asyncio.get_event_loop()
        seen_ids: set[str] = set()

        # Initial load: mark existing mentions as seen
        try:
            inbox = await loop.run_in_executor(
                None, lambda: list(self._reddit.inbox.mentions(limit=25))
            )
            for item in inbox:
                seen_ids.add(item.id)
        except Exception as e:
            logger.error(f"Reddit: failed to load initial mentions: {e}")

        while self._running:
            try:
                mentions = await loop.run_in_executor(
                    None, lambda: list(self._reddit.inbox.mentions(limit=25))
                )

                for mention in mentions:
                    if mention.id in seen_ids:
                        continue
                    seen_ids.add(mention.id)

                    body = mention.body.strip()
                    if not body:
                        continue

                    chat_id = f"mention_{mention.id}"
                    user_id = str(mention.author) if mention.author else "unknown"

                    # Store the comment object for replying
                    self._reply_targets[chat_id] = mention

                    await self.publish_inbound(
                        chat_id=chat_id,
                        user_id=user_id,
                        content=body,
                        subreddit=str(mention.subreddit) if mention.subreddit else "",
                        permalink=mention.permalink if hasattr(mention, "permalink") else "",
                    )

            except Exception as e:
                logger.error(f"Reddit mentions poll error: {e}")

            await asyncio.sleep(self._poll_interval)

    async def _poll_dms(self) -> None:
        """Poll for direct messages."""
        if not self._reddit:
            return

        loop = asyncio.get_event_loop()
        seen_ids: set[str] = set()

        # Initial load: mark existing DMs as seen
        try:
            messages = await loop.run_in_executor(
                None, lambda: list(self._reddit.inbox.messages(limit=25))
            )
            for msg in messages:
                seen_ids.add(msg.id)
        except Exception as e:
            logger.error(f"Reddit: failed to load initial DMs: {e}")

        while self._running:
            try:
                messages = await loop.run_in_executor(
                    None, lambda: list(self._reddit.inbox.messages(limit=25))
                )

                for msg in messages:
                    if msg.id in seen_ids:
                        continue
                    seen_ids.add(msg.id)

                    body = msg.body.strip()
                    if not body:
                        continue

                    chat_id = f"dm_{msg.id}"
                    user_id = str(msg.author) if msg.author else "unknown"

                    # Store the message object for replying
                    self._reply_targets[chat_id] = msg

                    await self.publish_inbound(
                        chat_id=chat_id,
                        user_id=user_id,
                        content=body,
                        subject=msg.subject if hasattr(msg, "subject") else "",
                    )

            except Exception as e:
                logger.error(f"Reddit DM poll error: {e}")

            await asyncio.sleep(self._poll_interval)

    async def send_message(self, chat_id: str, content: str) -> None:
        """Reply to a Reddit mention or DM."""
        if not self._reddit:
            logger.warning("Reddit: client not initialized")
            return

        target = self._reply_targets.pop(chat_id, None)
        if not target:
            logger.warning(f"Reddit: no reply target for {chat_id}")
            return

        loop = asyncio.get_event_loop()

        # Split long messages
        chunks = self._split_message(content, MESSAGE_LIMIT)

        try:
            # Reply to the first chunk
            await loop.run_in_executor(
                None, lambda: target.reply(chunks[0])
            )

            # If there are additional chunks, reply to the original again
            # (Reddit doesn't support editing well in this context)
            for chunk in chunks[1:]:
                await loop.run_in_executor(
                    None, lambda c=chunk: target.reply(c)
                )

        except Exception as e:
            logger.error(f"Reddit reply error: {e}")

        self._stream_buffers.pop(chat_id, None)

    async def send_stream_chunk(self, chat_id: str, chunk: StreamChunk) -> None:
        """Buffer streaming chunks and send final message.

        Reddit does not support message editing for bot replies efficiently,
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
