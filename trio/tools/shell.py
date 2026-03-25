"""Shell command execution tool — sandboxed subprocess execution."""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from trio.tools.base import BaseTool, ToolResult
from trio.core.config import get_workspace_dir

logger = logging.getLogger(__name__)

BLOCKED_COMMANDS = {"rm -rf /", "mkfs", "dd if=", ":(){:|:&};:", "chmod -R 777 /"}


class ShellTool(BaseTool):
    """Execute shell commands with optional workspace sandboxing."""

    def __init__(self, restrict_to_workspace: bool = False):
        self._restrict = restrict_to_workspace
        self._workspace = str(get_workspace_dir()) if restrict_to_workspace else None

    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command and return the output. "
            "Use this for running scripts, checking system info, or file operations."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 30)",
                    "default": 30,
                },
            },
            "required": ["command"],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        command = params.get("command", "")
        timeout = min(params.get("timeout", 30), 120)

        if not command:
            return ToolResult(output="Error: No command provided", success=False)

        # Safety check
        cmd_lower = command.lower().strip()
        for blocked in BLOCKED_COMMANDS:
            if blocked in cmd_lower:
                return ToolResult(output=f"Blocked: dangerous command", success=False)

        cwd = self._workspace if self._restrict else None

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

            output_parts = []
            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace").strip())
            if stderr:
                output_parts.append(f"STDERR: {stderr.decode('utf-8', errors='replace').strip()}")

            output = "\n".join(output_parts) or "(no output)"

            # Truncate if too long
            if len(output) > 4000:
                output = output[:4000] + "\n... (truncated)"

            return ToolResult(
                output=output,
                success=proc.returncode == 0,
                metadata={"return_code": proc.returncode},
            )

        except asyncio.TimeoutError:
            return ToolResult(output=f"Command timed out after {timeout}s", success=False)
        except Exception as e:
            return ToolResult(output=f"Error: {e}", success=False)
