"""File operations tool — read, write, edit, list files.

All paths are validated through the SandboxManager before any I/O occurs.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import logging
import os
from pathlib import Path
from typing import Any

from trio.tools.base import BaseTool, ToolResult
from trio.core.config import get_workspace_dir
from trio.core.sandbox import get_sandbox, SandboxViolation

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

    def _resolve_path(self, path: str) -> Path:
        """Resolve and validate path through the sandbox.

        Raises ``SandboxViolation`` if the path escapes the sandbox.
        Falls back to legacy workspace restriction when the sandbox is
        disabled.
        """
        sandbox = get_sandbox()

        p = Path(path).expanduser()

        # Resolve relative paths against sandbox root (or workspace)
        if not p.is_absolute():
            if sandbox.enabled:
                p = sandbox.root / p
            elif self._workspace:
                p = self._workspace / p

        resolved = p.resolve()

        # Sandbox validation (primary enforcement)
        if sandbox.enabled:
            sandbox.validate_path(resolved)
            return resolved

        # Legacy workspace restriction fallback
        if self._restrict and self._workspace:
            try:
                resolved.relative_to(self._workspace.resolve())
            except ValueError:
                raise SandboxViolation(
                    f"Path '{path}' is outside the workspace",
                    path=str(path), context="file_ops/_resolve_path",
                )
        return resolved

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        op = params.get("operation", "")
        path_str = params.get("path", "")
        content = params.get("content", "")

        if not path_str:
            return ToolResult(output="Error: No path provided", success=False)

        try:
            path = self._resolve_path(path_str)
        except SandboxViolation as exc:
            logger.warning("File ops sandbox violation: %s | path=%s op=%s",
                           exc, path_str, op)
            return ToolResult(
                output=f"Sandbox violation: {exc}",
                success=False,
                metadata={"sandbox_violation": True},
            )

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
