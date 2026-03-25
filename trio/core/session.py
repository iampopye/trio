"""Session persistence — JSONL-based conversation storage."""

import json
import time
from pathlib import Path
from typing import Any

from trio.core.config import get_sessions_dir


class Session:
    """A conversation session for a specific channel:chat_id pair."""

    def __init__(self, key: str, history: list[dict] | None = None):
        self.key = key
        self.history: list[dict] = history or []
        self.last_consolidated: int = 0
        self.metadata: dict[str, Any] = {}

    def add_message(self, role: str, content: str, **kwargs) -> dict:
        msg = {
            "role": role,
            "content": content,
            "timestamp": time.time(),
            **kwargs,
        }
        self.history.append(msg)
        return msg

    def get_recent(self, n: int = 20) -> list[dict]:
        return self.history[-n:]

    def clear(self) -> None:
        self.history.clear()
        self.last_consolidated = 0

    @property
    def message_count(self) -> int:
        return len(self.history)


class SessionManager:
    """Manages conversation sessions with JSONL persistence."""

    def __init__(self, data_dir: Path | None = None):
        self._dir = data_dir or get_sessions_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, Session] = {}

    def get(self, session_key: str) -> Session:
        """Get or load a session by key."""
        if session_key in self._cache:
            return self._cache[session_key]

        session_file = self._session_path(session_key)
        history = []

        if session_file.exists():
            history = self._load_jsonl(session_file)

        session = Session(key=session_key, history=history)
        self._cache[session_key] = session
        return session

    def save_message(self, session_key: str, message: dict) -> None:
        """Append a single message to the session's JSONL file."""
        session_file = self._session_path(session_key)
        with open(session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(message, ensure_ascii=False) + "\n")

    def save_session(self, session: Session) -> None:
        """Rewrite the entire session file (used after consolidation)."""
        session_file = self._session_path(session.key)
        with open(session_file, "w", encoding="utf-8") as f:
            for msg in session.history:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    def delete(self, session_key: str) -> None:
        """Delete a session (reset)."""
        session_file = self._session_path(session_key)
        if session_file.exists():
            session_file.unlink()
        self._cache.pop(session_key, None)

    def list_sessions(self) -> list[str]:
        """List all session keys."""
        return [f.stem for f in self._dir.glob("*.jsonl")]

    def _session_path(self, key: str) -> Path:
        safe_key = key.replace(":", "_").replace("/", "_")
        return self._dir / f"{safe_key}.jsonl"

    def _load_jsonl(self, path: Path) -> list[dict]:
        messages = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return messages
