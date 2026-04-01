"""Directory sandbox -- restricts ALL agent operations to a specific project folder.

When a user runs `trio` in a directory, ALL file/shell/code operations
are confined to that directory. No path traversal, no escaping.

Similar to how Claude Code scopes to the project root.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

import functools
import logging
import os
import re
import shlex
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Exception ────────────────────────────────────────────────────────────────

class SandboxViolation(PermissionError):
    """Raised when any operation attempts to escape the sandbox."""

    def __init__(self, message: str, *, path: str | None = None,
                 command: str | None = None, context: str = ""):
        self.sandbox_path = path
        self.sandbox_command = command
        self.sandbox_context = context
        super().__init__(message)


# ── Sandbox Manager ──────────────────────────────────────────────────────────

class SandboxManager:
    """Enforces filesystem and command sandboxing to a project root.

    All file paths are resolved (symlinks followed) and checked against
    the root directory. Shell commands are scanned for attempts to cd or
    access paths outside the sandbox.

    Usage::

        sandbox = SandboxManager("/home/user/project")
        sandbox.validate_path("/home/user/project/src/main.py")  # OK
        sandbox.validate_path("/etc/passwd")  # raises SandboxViolation
        sandbox.validate_command("cat ../../../etc/passwd")  # raises SandboxViolation
    """

    def __init__(self, root: str | Path, *,
                 enabled: bool = True,
                 allowed_paths: list[str | Path] | None = None):
        self._root = Path(root).resolve()
        self._enabled = enabled
        # Always allow the root itself; extra dirs (e.g. /tmp) can be added
        self._allowed_roots: list[Path] = [self._root]
        for p in (allowed_paths or []):
            resolved = Path(p).resolve()
            if resolved.is_dir():
                self._allowed_roots.append(resolved)
                logger.debug("Sandbox extra allowed dir: %s", resolved)

        if not self._root.is_dir():
            raise NotADirectoryError(f"Sandbox root does not exist: {self._root}")

        # Create .trio project marker
        trio_dir = self._root / ".trio"
        trio_dir.mkdir(exist_ok=True)

        logger.info("SandboxManager initialized: root=%s  enabled=%s  "
                     "extra_allowed=%s", self._root, self._enabled,
                     [str(p) for p in self._allowed_roots[1:]])

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def root(self) -> Path:
        return self._root

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ── Path validation ──────────────────────────────────────────────────

    def validate_path(self, path: str | Path) -> Path:
        """Validate that *path* is inside the sandbox.

        * Resolves symlinks so ``../../etc/passwd`` cannot sneak through.
        * Rejects absolute paths that fall outside the allowed roots.
        * Returns the resolved absolute ``Path`` on success.
        * Raises ``SandboxViolation`` on failure.
        """
        if not self._enabled:
            return Path(path).resolve()

        raw = str(path)
        target = Path(path)

        # Resolve relative paths against the sandbox root
        if not target.is_absolute():
            target = self._root / target

        resolved = target.resolve()

        # Check against each allowed root
        for allowed in self._allowed_roots:
            if resolved == allowed:
                return resolved
            try:
                resolved.relative_to(allowed)
                return resolved
            except ValueError:
                continue

        # None matched -- violation
        msg = (f"Sandbox violation: '{raw}' resolves to '{resolved}' which is "
               f"outside the project directory '{self._root}'")
        logger.warning(msg)
        raise SandboxViolation(msg, path=raw, context="validate_path")

    # ── Command validation ───────────────────────────────────────────────

    # Patterns that indicate path access in commands
    _CD_PATTERN = re.compile(r'\bcd\s+("?)(.+?)\1(?:\s|;|&&|\|\||$)')
    _REDIRECT_PATTERN = re.compile(r'[12]?>>\s*(\S+)|[12]?>\s*(\S+)')
    _SOURCE_PATTERN = re.compile(r'\b(?:source|\.)\s+(\S+)')

    def validate_command(self, cmd: str) -> str:
        """Validate a shell command does not escape the sandbox.

        Checks for:
        * ``cd`` to directories outside the sandbox
        * File redirects (``>``, ``>>``) to paths outside the sandbox
        * ``source`` / ``.`` of files outside the sandbox
        * Explicit absolute paths in arguments that escape the root

        Returns the original command string if valid.
        Raises ``SandboxViolation`` if the command tries to escape.
        """
        if not self._enabled:
            return cmd

        # Check cd targets
        for m in self._CD_PATTERN.finditer(cmd):
            cd_target = m.group(2).strip()
            try:
                self.validate_path(cd_target)
            except SandboxViolation:
                msg = (f"Sandbox violation: 'cd {cd_target}' would leave the "
                       f"project directory '{self._root}'")
                logger.warning(msg)
                raise SandboxViolation(msg, command=cmd, context="validate_command/cd")

        # Check redirects
        for m in self._REDIRECT_PATTERN.finditer(cmd):
            redir_path = m.group(1) or m.group(2)
            if redir_path:
                try:
                    self.validate_path(redir_path)
                except SandboxViolation:
                    msg = (f"Sandbox violation: redirect to '{redir_path}' is "
                           f"outside the project directory")
                    logger.warning(msg)
                    raise SandboxViolation(msg, command=cmd,
                                           context="validate_command/redirect")

        # Check source/dot targets
        for m in self._SOURCE_PATTERN.finditer(cmd):
            src_path = m.group(1)
            try:
                self.validate_path(src_path)
            except SandboxViolation:
                msg = (f"Sandbox violation: 'source {src_path}' targets a file "
                       f"outside the project directory")
                logger.warning(msg)
                raise SandboxViolation(msg, command=cmd,
                                       context="validate_command/source")

        # Scan all tokens for absolute paths outside the sandbox
        try:
            tokens = shlex.split(cmd)
        except ValueError:
            tokens = cmd.split()

        for token in tokens:
            # Only check tokens that look like absolute paths
            if not (token.startswith("/") or (len(token) >= 3 and token[1] == ":")):
                continue
            # Skip common non-path tokens like /dev/null
            if token in ("/dev/null", "/dev/stdin", "/dev/stdout", "/dev/stderr"):
                continue
            try:
                self.validate_path(token)
            except SandboxViolation:
                msg = (f"Sandbox violation: command references '{token}' which "
                       f"is outside the project directory '{self._root}'")
                logger.warning(msg)
                raise SandboxViolation(msg, command=cmd,
                                       context="validate_command/abs_path")

        return cmd

    # ── Decorator / context manager for file operations ──────────────────

    def wrap_file_ops(self, fn: Callable | None = None):
        """Decorator that validates the first ``path`` argument through the sandbox.

        Can be used as::

            @sandbox.wrap_file_ops
            def read_file(path: str) -> str:
                ...

        Or as a context manager factory is not needed -- just wrap individual
        calls with :meth:`validate_path`.
        """
        if fn is None:
            # Called as @wrap_file_ops() with parens -- return decorator
            return self.wrap_file_ops

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Try to find the path in positional or keyword args
            path_arg = kwargs.get("path") or (args[0] if args else None)
            if path_arg is not None:
                self.validate_path(path_arg)
            return fn(*args, **kwargs)

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            path_arg = kwargs.get("path") or (args[0] if args else None)
            if path_arg is not None:
                self.validate_path(path_arg)
            return await fn(*args, **kwargs)

        import asyncio
        if asyncio.iscoroutinefunction(fn):
            return async_wrapper
        return wrapper


# ── Module-level singleton ───────────────────────────────────────────────────

_sandbox: SandboxManager | None = None


def init_sandbox(root: str | Path | None = None, *,
                 enabled: bool = True,
                 allowed_paths: list[str | Path] | None = None) -> SandboxManager:
    """Initialize the module-level sandbox singleton.

    Reads sandbox settings from trio config if available, with parameters
    as overrides.
    """
    global _sandbox

    # Try to load config-based settings
    cfg_enabled = enabled
    cfg_allowed: list[str | Path] = list(allowed_paths or [])

    try:
        from trio.core.config import load_config
        config = load_config()
        sandbox_cfg = config.get("sandbox", {})
        if "enabled" in sandbox_cfg:
            cfg_enabled = sandbox_cfg["enabled"]
        if "root" in sandbox_cfg and root is None:
            root = sandbox_cfg["root"]
        if "allowed_paths" in sandbox_cfg:
            cfg_allowed.extend(sandbox_cfg["allowed_paths"])
    except Exception:
        pass  # Config not available -- use parameters as-is

    root_path = Path(root or os.getcwd()).resolve()
    _sandbox = SandboxManager(root_path, enabled=cfg_enabled,
                              allowed_paths=cfg_allowed)
    return _sandbox


def get_sandbox() -> SandboxManager:
    """Return the current sandbox manager (initializes if needed)."""
    if _sandbox is None:
        return init_sandbox()
    return _sandbox


def get_sandbox_root() -> Path:
    """Get the current sandbox root directory."""
    return get_sandbox().root


def is_sandboxed() -> bool:
    """Check if sandbox is initialized and enabled."""
    return _sandbox is not None and _sandbox.enabled


def validate_path(path: str | Path) -> Path:
    """Module-level shortcut: validate a path through the singleton sandbox."""
    return get_sandbox().validate_path(path)


def validate_command(cmd: str) -> str:
    """Module-level shortcut: validate a shell command through the singleton sandbox."""
    return get_sandbox().validate_command(cmd)


def safe_join(relative_path: str) -> Path:
    """Safely join a relative path to the sandbox root.

    Prevents directory traversal via ../ or absolute paths.
    """
    root = get_sandbox_root()

    if os.path.isabs(relative_path):
        raise SandboxViolation(
            f"Access denied: absolute paths not allowed. "
            f"Use paths relative to {root}",
            path=relative_path, context="safe_join",
        )

    normed = os.path.normpath(relative_path)
    if normed.startswith("..") or normed.startswith(os.sep):
        raise SandboxViolation(
            f"Access denied: path traversal detected in '{relative_path}'",
            path=relative_path, context="safe_join",
        )

    joined = (root / normed).resolve()
    validate_path(joined)
    return joined


def list_project_files(max_depth: int = 3) -> list[str]:
    """List files in the sandbox directory up to max_depth."""
    root = get_sandbox_root()
    files: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d not in (
                "node_modules", "__pycache__", "venv", ".venv", "env",
                ".git", "dist", "build", ".next", ".cache"
            )
        ]

        depth = Path(dirpath).relative_to(root).parts
        if len(depth) >= max_depth:
            dirnames.clear()
            continue

        for fname in filenames:
            if fname.startswith("."):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fname), root)
            files.append(rel.replace("\\", "/"))

    return sorted(files)


def get_project_info() -> dict:
    """Get project information from the sandbox directory."""
    root = get_sandbox_root()
    info: dict[str, Any] = {
        "root": str(root),
        "name": root.name,
        "files_count": 0,
        "has_git": (root / ".git").is_dir(),
        "has_package_json": (root / "package.json").is_file(),
        "has_pyproject": (root / "pyproject.toml").is_file(),
        "has_requirements": (root / "requirements.txt").is_file(),
        "has_dockerfile": (root / "Dockerfile").is_file(),
        "language": "unknown",
    }

    extensions: dict[str, int] = {}
    for f in list_project_files(max_depth=4):
        ext = Path(f).suffix.lower()
        if ext in (".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs",
                    ".java", ".rb", ".php"):
            extensions[ext] = extensions.get(ext, 0) + 1
            info["files_count"] += 1

    if extensions:
        top_ext = max(extensions, key=extensions.get)  # type: ignore[arg-type]
        lang_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".tsx": "typescript", ".jsx": "javascript", ".go": "go",
            ".rs": "rust", ".java": "java", ".rb": "ruby", ".php": "php",
        }
        info["language"] = lang_map.get(top_ext, "unknown")

    return info


def wrap_shell_command(cmd: str) -> str:
    """Wrap a shell command to run inside the sandbox directory."""
    root = get_sandbox_root()
    return f'cd "{root}" && {cmd}'
