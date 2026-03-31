"""Shell command execution tool — sandboxed subprocess execution.

Security model:
    1. Allowlisted base commands only (ls, cat, git, python, npm, etc.)
    2. Blocklisted dangerous patterns as a second layer
    3. Pipe chain validation — every command in a pipeline is checked
    4. Workspace restriction (optional) limits cwd
    5. Timeout + output truncation
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import logging
import os
import re
import shlex
from pathlib import Path
from typing import Any

from trio.tools.base import BaseTool, ToolResult
from trio.core.config import get_workspace_dir

logger = logging.getLogger(__name__)

# ── Allowlist: only these base commands can be executed ─────────────────────
ALLOWED_COMMANDS = frozenset({
    # Navigation & files
    "ls", "dir", "pwd", "cd", "find", "tree", "stat", "file", "wc",
    "cat", "head", "tail", "less", "more", "tee",
    "cp", "mv", "mkdir", "touch", "ln",
    "rm",  # allowed but dangerous patterns blocked below
    # Text processing
    "echo", "printf", "grep", "rg", "awk", "sed", "sort", "uniq",
    "cut", "tr", "diff", "patch", "jq", "yq", "xargs",
    # Compression
    "tar", "zip", "unzip", "gzip", "gunzip", "bzip2",
    # Development
    "python", "python3", "pip", "pip3", "uv",
    "node", "npm", "npx", "yarn", "pnpm", "bun", "deno",
    "git", "gh",
    "cargo", "rustc", "go",
    "java", "javac", "mvn", "gradle",
    "gcc", "g++", "make", "cmake",
    "docker", "docker-compose",
    # System info (read-only, env/printenv excluded — they leak secrets)
    "whoami", "hostname", "uname", "date", "uptime",
    "which", "where", "type", "command",
    "ps", "top", "htop", "free", "df", "du",
    # Network (read-only)
    "ping", "nslookup", "dig", "host",
    # trio-specific
    "trio", "ollama",
    # NOTE: cmd, powershell, pwsh are intentionally excluded — they are
    # shell interpreters that can execute arbitrary commands and bypass
    # the allowlist. curl/wget excluded — data exfiltration risk.
})

# ── Blocklist: dangerous patterns always rejected ──────────────────────────
BLOCKED_PATTERNS = [
    re.compile(r'\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)?(/|~|\.\.|\\)'),  # rm -rf / or rm -rf ~
    re.compile(r'\bmkfs\b'),
    re.compile(r'\bdd\s+if='),
    re.compile(r':\(\)\s*\{.*\|.*&\s*\}\s*;'),  # fork bomb
    re.compile(r'\bchmod\s+(-R\s+)?777\s+/'),
    re.compile(r'\b(shutdown|reboot|halt|poweroff)\b'),
    re.compile(r'\bsudo\s+(rm|chmod|chown|mkfs|dd|shutdown|reboot|halt)\b'),
    re.compile(r'>\s*/dev/sd[a-z]'),  # write to raw disk
    re.compile(r'\bformat\s+[a-zA-Z]:'),  # Windows format drive
    re.compile(r'\brm\s+-rf\s+/\s*$'),  # rm -rf /
    re.compile(r'>\s*/etc/'),  # overwrite system configs
    re.compile(r'\bcrontab\s+-r\b'),  # delete all cron jobs
    re.compile(r'\biptables\s+-F\b'),  # flush firewall rules
    re.compile(r'\buserdel\b'),
    re.compile(r'\bgroupdel\b'),
    re.compile(r'\bpasswd\b'),
    re.compile(r'\bchpasswd\b'),
    # Reverse shell patterns
    re.compile(r'\b(nc|ncat|netcat)\s.*-[elp]'),
    re.compile(r'/dev/tcp/'),
    re.compile(r'\bbash\s+-i\s+>'),
    re.compile(r'\bpython[3]?\s+-c\s+.*socket'),
]


def _extract_base_command(cmd_part: str) -> str | None:
    """Extract the base command name from a shell command string."""
    cmd_part = cmd_part.strip()
    if not cmd_part:
        return None
    # Strip leading env vars like VAR=value
    while re.match(r'^[A-Za-z_][A-Za-z0-9_]*=\S*\s+', cmd_part):
        cmd_part = re.sub(r'^[A-Za-z_][A-Za-z0-9_]*=\S*\s+', '', cmd_part, count=1)
    # Get first token
    try:
        tokens = shlex.split(cmd_part)
    except ValueError:
        tokens = cmd_part.split()
    if not tokens:
        return None
    base = Path(tokens[0]).name  # Strip path: /usr/bin/python -> python
    return base


def _validate_command(command: str) -> tuple[bool, str]:
    """Validate a command against allowlist and blocklist.

    Returns (is_safe, reason).
    """
    cmd_lower = command.lower().strip()

    # Check blocked patterns first (always reject)
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(cmd_lower):
            return False, "Blocked: dangerous command pattern detected"

    # Split on pipes, semicolons, &&, || to check each sub-command
    parts = re.split(r'\s*(?:\|{1,2}|&&|;)\s*', command.strip())
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Handle subshells: $(cmd) or `cmd` — extract inner command
        inner_cmds = re.findall(r'\$\((.+?)\)', part) + re.findall(r'`(.+?)`', part)
        all_parts = [part] + inner_cmds
        for p in all_parts:
            base = _extract_base_command(p)
            if base and base not in ALLOWED_COMMANDS:
                return False, f"Blocked: '{base}' is not in the allowed commands list"

    return True, ""


class ShellTool(BaseTool):
    """Execute shell commands with allowlist-based sandboxing.

    Security layers:
        1. Command allowlist — only known-safe base commands
        2. Dangerous pattern blocklist — catches destructive args
        3. Workspace restriction — optional cwd sandboxing
        4. Timeout enforcement — max 120 seconds
        5. Output truncation — max 4000 chars
    """

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
            "Use this for running scripts, checking system info, or file operations. "
            "Only allowlisted commands are permitted for security."
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

        # Validate against allowlist and blocklist
        is_safe, reason = _validate_command(command)
        if not is_safe:
            logger.warning(f"Shell command blocked: {reason} | cmd={command[:100]}")
            return ToolResult(output=reason, success=False)

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
