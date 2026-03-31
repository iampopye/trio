"""Email tool — send and read emails via SMTP/IMAP."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import email
import imaplib
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any

from trio.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class EmailTool(BaseTool):
    """Send and read emails via SMTP/IMAP."""

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    @property
    def name(self) -> str:
        return "email"

    @property
    def description(self) -> str:
        return (
            "Send and read emails. Actions: send (compose and send an email), "
            "read_inbox (list recent emails), read_message (read a specific email), "
            "search (search emails by query)."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["send", "read_inbox", "read_message", "search"],
                    "description": "Email action to perform",
                },
                "to": {"type": "string", "description": "Recipient email (for send)"},
                "subject": {"type": "string", "description": "Email subject (for send)"},
                "body": {"type": "string", "description": "Email body (for send)"},
                "query": {"type": "string", "description": "Search query (for search)"},
                "count": {"type": "integer", "description": "Number of emails to read (default 10)", "default": 10},
                "message_id": {"type": "string", "description": "Message ID to read (for read_message)"},
            },
            "required": ["action"],
        }

    def _get_smtp(self):
        host = self._config.get("smtp_host", "")
        port = self._config.get("smtp_port", 587)
        username = self._config.get("username", "")
        password = self._config.get("password", "")
        if not all([host, username, password]):
            raise ValueError("Email not configured. Set smtp_host, username, password in config.")
        server = smtplib.SMTP(host, port)
        server.starttls()
        server.login(username, password)
        return server

    def _get_imap(self):
        host = self._config.get("imap_host", "")
        username = self._config.get("username", "")
        password = self._config.get("password", "")
        if not all([host, username, password]):
            raise ValueError("Email not configured. Set imap_host, username, password in config.")
        conn = imaplib.IMAP4_SSL(host)
        conn.login(username, password)
        return conn

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        action = params.get("action", "")

        try:
            if action == "send":
                return await asyncio.to_thread(self._send, params)
            elif action == "read_inbox":
                return await asyncio.to_thread(self._read_inbox, params.get("count", 10))
            elif action == "read_message":
                mid = params.get("message_id", "")
                if not mid:
                    return ToolResult(output="Error: message_id required", success=False)
                return await asyncio.to_thread(self._read_message, mid)
            elif action == "search":
                query = params.get("query", "")
                if not query:
                    return ToolResult(output="Error: query required", success=False)
                return await asyncio.to_thread(self._search, query, params.get("count", 10))
            else:
                return ToolResult(output=f"Unknown action: {action}", success=False)
        except Exception as e:
            logger.error(f"Email action '{action}' failed: {e}")
            return ToolResult(output=f"Email error: {e}", success=False)

    def _send(self, params: dict) -> ToolResult:
        to = params.get("to", "")
        subject = params.get("subject", "")
        body = params.get("body", "")
        if not to:
            return ToolResult(output="Error: 'to' address required", success=False)

        username = self._config.get("username", "")
        msg = MIMEMultipart()
        msg["From"] = username
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        server = self._get_smtp()
        server.sendmail(username, to, msg.as_string())
        server.quit()
        return ToolResult(output=f"Email sent to {to}: {subject}")

    def _read_inbox(self, count: int) -> ToolResult:
        conn = self._get_imap()
        conn.select("INBOX")
        _, data = conn.search(None, "ALL")
        ids = data[0].split()
        ids = ids[-count:] if len(ids) > count else ids

        results = []
        for mid in reversed(ids):
            _, msg_data = conn.fetch(mid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            results.append(
                f"ID: {mid.decode()}\n"
                f"From: {msg.get('From', '?')}\n"
                f"Subject: {msg.get('Subject', '(no subject)')}\n"
                f"Date: {msg.get('Date', '?')}"
            )
        conn.close()
        conn.logout()
        return ToolResult(output="\n\n".join(results) or "Inbox is empty.")

    def _read_message(self, message_id: str) -> ToolResult:
        conn = self._get_imap()
        conn.select("INBOX")
        _, msg_data = conn.fetch(message_id.encode(), "(RFC822)")
        if not msg_data or not msg_data[0]:
            conn.logout()
            return ToolResult(output=f"Message {message_id} not found", success=False)

        msg = email.message_from_bytes(msg_data[0][1])
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                    break
        else:
            body = msg.get_payload(decode=True).decode("utf-8", errors="replace")

        if len(body) > 4000:
            body = body[:4000] + "\n... (truncated)"

        conn.close()
        conn.logout()
        return ToolResult(
            output=f"From: {msg.get('From')}\nSubject: {msg.get('Subject')}\nDate: {msg.get('Date')}\n\n{body}"
        )

    def _search(self, query: str, count: int) -> ToolResult:
        conn = self._get_imap()
        conn.select("INBOX")
        _, data = conn.search(None, "SUBJECT", f'"{query}"')
        ids = data[0].split()
        ids = ids[-count:] if len(ids) > count else ids

        results = []
        for mid in reversed(ids):
            _, msg_data = conn.fetch(mid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            results.append(
                f"ID: {mid.decode()} | From: {msg.get('From', '?')} | Subject: {msg.get('Subject', '?')}"
            )
        conn.close()
        conn.logout()
        return ToolResult(output="\n".join(results) or f"No emails matching: {query}")
