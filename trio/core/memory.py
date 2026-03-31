"""Persistent memory system — MEMORY.md + HISTORY.md + auto-consolidation."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import time
from pathlib import Path
from typing import Any

from trio.core.config import get_memory_dir


class MemoryStore:
    """Three-tier memory: session history → HISTORY.md → MEMORY.md.

    - HISTORY.md: Append-only searchable log of all interactions
    - MEMORY.md: Consolidated long-term facts (auto-summarized)
    - Daily notes: memory/YYYY-MM-DD.md for daily context
    """

    def __init__(self, memory_dir: Path | None = None):
        self._dir = memory_dir or get_memory_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._memory_file = self._dir / "MEMORY.md"
        self._history_file = self._dir / "HISTORY.md"
        self._init_files()

    def _init_files(self) -> None:
        if not self._memory_file.exists():
            self._memory_file.write_text(
                "# trio Memory\n\n"
                "Long-term facts and knowledge consolidated from conversations.\n\n",
                encoding="utf-8",
            )
        if not self._history_file.exists():
            self._history_file.write_text(
                "# trio History\n\n"
                "Searchable log of recent interactions.\n\n",
                encoding="utf-8",
            )

    def append_to_history(self, channel: str, user_id: str, role: str, content: str) -> None:
        """Append a message to HISTORY.md."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] [{channel}:{user_id}] {role}: {content}\n"
        with open(self._history_file, "a", encoding="utf-8") as f:
            f.write(entry)

    def read_memory(self) -> str:
        """Read the full MEMORY.md contents."""
        if self._memory_file.exists():
            return self._memory_file.read_text(encoding="utf-8")
        return ""

    def read_history(self, last_n_lines: int = 50) -> str:
        """Read the last N lines of HISTORY.md."""
        if not self._history_file.exists():
            return ""
        lines = self._history_file.read_text(encoding="utf-8").splitlines()
        return "\n".join(lines[-last_n_lines:])

    def search_history(self, query: str) -> list[str]:
        """Simple grep-like search through HISTORY.md."""
        if not self._history_file.exists():
            return []
        query_lower = query.lower()
        results = []
        with open(self._history_file, "r", encoding="utf-8") as f:
            for line in f:
                if query_lower in line.lower():
                    results.append(line.strip())
        return results[-20:]  # Last 20 matches

    def save_memory_fact(self, fact: str) -> None:
        """Append a fact to MEMORY.md."""
        timestamp = time.strftime("%Y-%m-%d")
        with open(self._memory_file, "a", encoding="utf-8") as f:
            f.write(f"\n## {timestamp}\n{fact}\n")

    async def consolidate(self, session_messages: list[dict], provider: Any) -> str | None:
        """Consolidate old session messages into MEMORY.md via LLM summary.

        Args:
            session_messages: Messages to consolidate
            provider: LLM provider for summarization

        Returns:
            Summary text if consolidation happened, None otherwise
        """
        if len(session_messages) < 5:
            return None

        conversation_text = "\n".join(
            f"{msg['role']}: {msg['content']}"
            for msg in session_messages
            if msg.get("content")
        )

        summary_prompt = [
            {
                "role": "system",
                "content": (
                    "Summarize the key facts, preferences, and important information "
                    "from this conversation. Be concise. Use bullet points. "
                    "Focus on what would be useful to remember for future conversations."
                ),
            },
            {"role": "user", "content": conversation_text},
        ]

        try:
            summary = await provider.generate(summary_prompt)
            self.save_memory_fact(summary)
            return summary
        except Exception:
            return None

    def get_daily_note_path(self) -> Path:
        """Get path for today's daily note."""
        date_str = time.strftime("%Y-%m-%d")
        return self._dir / f"{date_str}.md"

    def append_daily_note(self, content: str) -> None:
        """Append to today's daily note."""
        path = self.get_daily_note_path()
        if not path.exists():
            path.write_text(f"# {time.strftime('%Y-%m-%d')}\n\n", encoding="utf-8")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{content}\n")
