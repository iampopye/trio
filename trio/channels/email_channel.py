"""Email channel — receive via IMAP, send via SMTP.

Polls an IMAP inbox for new emails and sends replies via SMTP.
Each email thread is treated as a separate conversation.
"""

import asyncio
import email
import email.utils
import imaplib
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any

from trio.channels.base import BaseChannel
from trio.core.bus import MessageBus, StreamChunk

logger = logging.getLogger(__name__)

MESSAGE_LIMIT = 50000  # Emails can be long


class EmailChannel(BaseChannel):
    """Email channel via IMAP (receive) and SMTP (send)."""

    def __init__(self, bus: MessageBus, config: dict):
        super().__init__(name="email", bus=bus, config=config)
        self._imap_host = config.get("imap_host", "")
        self._imap_port = config.get("imap_port", 993)
        self._smtp_host = config.get("smtp_host", "")
        self._smtp_port = config.get("smtp_port", 587)
        self._username = config.get("username", "")
        self._password = config.get("password", "")
        self._poll_interval = config.get("poll_interval", 30)  # seconds
        self._folder = config.get("folder", "INBOX")
        self._running = False
        self._imap = None
        self._stream_buffers: dict[str, str] = {}
        # Store email metadata for replies
        self._reply_metadata: dict[str, dict] = {}  # chat_id -> {from, subject, message_id}

    async def start(self) -> None:
        """Connect to IMAP and start polling for new emails."""
        self._running = True

        # Test IMAP connection
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, self._connect_imap)
            logger.info(
                f"Email channel: connected to IMAP {self._imap_host} as {self._username}"
            )
        except Exception as e:
            raise RuntimeError(f"Email IMAP connection failed: {e}")

        # Start polling
        asyncio.create_task(self._poll_inbox())

    async def stop(self) -> None:
        """Stop polling and disconnect."""
        self._running = False
        if self._imap:
            try:
                self._imap.logout()
            except Exception:
                pass
            self._imap = None

    def _connect_imap(self) -> None:
        """Connect to the IMAP server."""
        self._imap = imaplib.IMAP4_SSL(self._imap_host, self._imap_port)
        self._imap.login(self._username, self._password)
        self._imap.select(self._folder)

    async def _poll_inbox(self) -> None:
        """Poll for new unseen emails."""
        loop = asyncio.get_event_loop()
        seen_uids: set[str] = set()

        # Initial load: mark all existing emails as seen
        try:
            uids = await loop.run_in_executor(None, self._get_unseen_uids)
            seen_uids.update(uids)
            logger.info(f"Email: skipped {len(seen_uids)} existing unseen emails")
        except Exception as e:
            logger.error(f"Email: initial scan failed: {e}")

        while self._running:
            try:
                uids = await loop.run_in_executor(None, self._get_unseen_uids)

                for uid in uids:
                    if uid in seen_uids:
                        continue
                    seen_uids.add(uid)

                    # Fetch the email
                    msg_data = await loop.run_in_executor(
                        None, lambda u=uid: self._fetch_email(u)
                    )
                    if not msg_data:
                        continue

                    sender = msg_data["from"]
                    subject = msg_data["subject"]
                    body = msg_data["body"]
                    message_id = msg_data["message_id"]

                    if not body.strip():
                        continue

                    # Use sender email as chat_id
                    chat_id = sender
                    user_id = sender

                    # Store metadata for reply
                    self._reply_metadata[chat_id] = {
                        "from": sender,
                        "subject": subject,
                        "message_id": message_id,
                    }

                    # Include subject in content for context
                    content = body
                    if subject:
                        content = f"[Subject: {subject}]\n\n{body}"

                    await self.publish_inbound(
                        chat_id=chat_id,
                        user_id=user_id,
                        content=content,
                        subject=subject,
                        message_id=message_id,
                    )

            except imaplib.IMAP4.abort:
                # Connection lost, reconnect
                logger.warning("Email: IMAP connection lost, reconnecting...")
                try:
                    await loop.run_in_executor(None, self._connect_imap)
                except Exception as e:
                    logger.error(f"Email: reconnection failed: {e}")

            except Exception as e:
                logger.error(f"Email poll error: {e}")

            await asyncio.sleep(self._poll_interval)

    def _get_unseen_uids(self) -> list[str]:
        """Get UIDs of unseen emails."""
        if not self._imap:
            return []
        try:
            self._imap.noop()  # Keep connection alive
            status, data = self._imap.search(None, "UNSEEN")
            if status != "OK":
                return []
            uids = data[0].split()
            return [uid.decode() for uid in uids]
        except Exception:
            return []

    def _fetch_email(self, uid: str) -> dict | None:
        """Fetch and parse a single email by UID."""
        if not self._imap:
            return None

        try:
            status, data = self._imap.fetch(uid.encode(), "(RFC822)")
            if status != "OK" or not data[0]:
                return None

            raw_email = data[0][1]
            msg = email.message_from_bytes(raw_email)

            # Extract sender
            from_header = msg.get("From", "")
            sender_name, sender_email = email.utils.parseaddr(from_header)
            sender = sender_email or from_header

            # Extract subject
            subject = msg.get("Subject", "")

            # Extract message ID
            message_id = msg.get("Message-ID", "")

            # Extract body (prefer plain text)
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    if content_type == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or "utf-8"
                            body = payload.decode(charset, errors="replace")
                            break
                # Fallback to HTML if no plain text
                if not body:
                    for part in msg.walk():
                        if part.get_content_type() == "text/html":
                            payload = part.get_payload(decode=True)
                            if payload:
                                charset = part.get_content_charset() or "utf-8"
                                body = payload.decode(charset, errors="replace")
                                # Strip HTML tags (basic)
                                import re
                                body = re.sub(r"<[^>]+>", "", body)
                                break
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="replace")

            return {
                "from": sender,
                "subject": subject,
                "body": body.strip(),
                "message_id": message_id,
            }

        except Exception as e:
            logger.error(f"Email fetch error for UID {uid}: {e}")
            return None

    async def send_message(self, chat_id: str, content: str) -> None:
        """Send an email reply via SMTP."""
        metadata = self._reply_metadata.get(chat_id, {})
        to_address = chat_id
        subject = metadata.get("subject", "")
        in_reply_to = metadata.get("message_id", "")

        # Add Re: prefix if not already present
        if subject and not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        elif not subject:
            subject = "Re: Your message"

        loop = asyncio.get_event_loop()

        # Split into parts if extremely long
        chunks = self._split_message(content, MESSAGE_LIMIT)
        full_content = "\n\n---\n\n".join(chunks)

        try:
            await loop.run_in_executor(
                None,
                lambda: self._send_smtp(to_address, subject, full_content, in_reply_to),
            )
        except Exception as e:
            logger.error(f"Email send error to {to_address}: {e}")

        self._stream_buffers.pop(chat_id, None)

    def _send_smtp(
        self, to: str, subject: str, body: str, in_reply_to: str = ""
    ) -> None:
        """Send an email via SMTP (synchronous)."""
        msg = MIMEMultipart("alternative")
        msg["From"] = self._username
        msg["To"] = to
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

        # Plain text part
        text_part = MIMEText(body, "plain", "utf-8")
        msg.attach(text_part)

        with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
            server.starttls()
            server.login(self._username, self._password)
            server.send_message(msg)

    async def send_stream_chunk(self, chat_id: str, chunk: StreamChunk) -> None:
        """Buffer streaming chunks and send final email.

        Email does not support real-time editing, so we buffer and
        send only the final result.
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
