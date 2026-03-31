"""Session persistence — JSONL-based conversation storage."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import json
import time
from pathlib import Path
from typing import Any

from trio.core.config import get_sessions_dir


class Session:
    """A conversation session for a specific channel:chat_id pair."""

    def __init__(self, key: str, history: list[dict] | None = None,
                 name: str = "", created_at: float | None = None):
        self.key = key
        self.name = name or key
        self.created_at = created_at or time.time()
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

    def rename_session(self, session_key: str, new_name: str) -> bool:
        """Rename a session (display name, not file key)."""
        session = self.get(session_key)
        session.name = new_name
        # Save metadata
        meta_path = self._dir / f"{session_key}_meta.json"
        meta_path.write_text(
            json.dumps({"name": new_name, "created_at": session.created_at}),
            encoding="utf-8",
        )
        return True

    def get_named_sessions(self) -> list[dict]:
        """List sessions with their names and metadata."""
        sessions = []
        for f in sorted(self._dir.glob("*.jsonl")):
            key = f.stem
            meta_path = self._dir / f"{key}_meta.json"
            name = key
            created_at = f.stat().st_ctime
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    name = meta.get("name", key)
                    created_at = meta.get("created_at", created_at)
                except Exception:
                    pass  # nosec B110 — intentional silent fallback
            msg_count = sum(1 for line in f.read_text(encoding="utf-8").split("\n") if line.strip())
            sessions.append({
                "key": key,
                "name": name,
                "created_at": created_at,
                "messages": msg_count,
            })
        return sessions

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
