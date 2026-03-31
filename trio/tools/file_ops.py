"""File operations tool — read, write, edit, list files."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import logging
import os
from pathlib import Path
from typing import Any

from trio.tools.base import BaseTool, ToolResult
from trio.core.config import get_workspace_dir

logger = logging.getLogger(__name__)


class FileOpsTool(BaseTool):
    """Read, write, edit, and list files."""

    def __init__(self, restrict_to_workspace: bool = False):
        self._restrict = restrict_to_workspace
        self._workspace = Path(get_workspace_dir()) if restrict_to_workspace else None

    @property
    def name(self) -> str:
        return "file_ops"

    @property
    def description(self) -> str:
        return (
            "Read, write, edit, or list files. Operations: read, write, append, list. "
            "Use this to interact with the filesystem."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["read", "write", "append", "list"],
                    "description": "The file operation to perform",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory path",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write (for write/append operations)",
                },
            },
            "required": ["operation", "path"],
        }

    def _resolve_path(self, path: str) -> Path | None:
        """Resolve and validate path, enforcing sandbox if enabled."""
        p = Path(path).expanduser()
        if not p.is_absolute() and self._workspace:
            p = self._workspace / p
        if self._restrict and self._workspace:
            try:
                p.resolve().relative_to(self._workspace.resolve())
            except ValueError:
                return None  # Path escapes workspace
        return p

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        op = params.get("operation", "")
        path_str = params.get("path", "")
        content = params.get("content", "")

        if not path_str:
            return ToolResult(output="Error: No path provided", success=False)

        path = self._resolve_path(path_str)
        if path is None:
            return ToolResult(output="Error: Path outside workspace", success=False)

        if op == "read":
            return self._read(path)
        elif op == "write":
            return self._write(path, content)
        elif op == "append":
            return self._append(path, content)
        elif op == "list":
            return self._list_dir(path)
        else:
            return ToolResult(output=f"Error: Unknown operation '{op}'", success=False)

    def _read(self, path: Path) -> ToolResult:
        try:
            if not path.exists():
                return ToolResult(output=f"File not found: {path}", success=False)
            text = path.read_text(encoding="utf-8", errors="replace")
            if len(text) > 8000:
                text = text[:8000] + "\n... (truncated)"
            return ToolResult(output=text, metadata={"size": path.stat().st_size})
        except Exception as e:
            return ToolResult(output=f"Error reading {path}: {e}", success=False)

    def _write(self, path: Path, content: str) -> ToolResult:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return ToolResult(output=f"Written {len(content)} chars to {path}")
        except Exception as e:
            return ToolResult(output=f"Error writing {path}: {e}", success=False)

    def _append(self, path: Path, content: str) -> ToolResult:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
            return ToolResult(output=f"Appended {len(content)} chars to {path}")
        except Exception as e:
            return ToolResult(output=f"Error appending to {path}: {e}", success=False)

    def _list_dir(self, path: Path) -> ToolResult:
        try:
            if not path.is_dir():
                return ToolResult(output=f"Not a directory: {path}", success=False)
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
            lines = []
            for entry in entries[:100]:  # Limit to 100 entries
                prefix = "d " if entry.is_dir() else "f "
                size = f" ({entry.stat().st_size}B)" if entry.is_file() else ""
                lines.append(f"{prefix}{entry.name}{size}")
            output = "\n".join(lines) or "(empty directory)"
            return ToolResult(output=output, metadata={"entry_count": len(entries)})
        except Exception as e:
            return ToolResult(output=f"Error listing {path}: {e}", success=False)
