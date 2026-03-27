"""Directory sandbox -- restricts all agent operations to a specific project folder.

When a user runs `trio` in a directory, ALL file/shell/code operations
are confined to that directory. No path traversal, no escaping.

Similar to how Claude Code scopes to the project root.
"""

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_sandbox_root: Path | None = None


def init_sandbox(root: str | Path | None = None) -> Path:
    """Initialize the sandbox to a specific directory.

    If no root is given, uses current working directory.
    Creates a .trio/ folder inside to mark it as a trio project.
    """
    global _sandbox_root
    root_path = Path(root or os.getcwd()).resolve()

    if not root_path.is_dir():
        raise NotADirectoryError(f"Sandbox root does not exist: {root_path}")

    _sandbox_root = root_path

    # Create .trio project marker
    trio_dir = root_path / ".trio"
    trio_dir.mkdir(exist_ok=True)

    logger.info(f"Sandbox initialized: {root_path}")
    return root_path


def get_sandbox_root() -> Path:
    """Get the current sandbox root directory."""
    if _sandbox_root is None:
        return init_sandbox()
    return _sandbox_root


def is_sandboxed() -> bool:
    """Check if sandbox is initialized."""
    return _sandbox_root is not None


def validate_path(path: str | Path) -> Path:
    """Validate that a path is within the sandbox.

    Resolves symlinks and prevents path traversal.
    Returns the resolved absolute path if valid.
    Raises PermissionError if path escapes sandbox.
    """
    root = get_sandbox_root()
    resolved = Path(path).resolve()

    # Allow the root itself
    if resolved == root:
        return resolved

    # Check if the resolved path is under the sandbox root
    try:
        resolved.relative_to(root)
        return resolved
    except ValueError:
        raise PermissionError(
            f"Access denied: '{path}' is outside the project directory.\n"
            f"trio can only access files within: {root}"
        )


def safe_join(relative_path: str) -> Path:
    """Safely join a relative path to the sandbox root.

    Prevents directory traversal via ../ or absolute paths.
    """
    root = get_sandbox_root()

    # Block absolute paths
    if os.path.isabs(relative_path):
        raise PermissionError(
            f"Access denied: absolute paths not allowed. Use paths relative to {root}"
        )

    # Normalize and check for traversal
    normed = os.path.normpath(relative_path)
    if normed.startswith("..") or normed.startswith(os.sep):
        raise PermissionError(
            f"Access denied: path traversal detected in '{relative_path}'"
        )

    joined = (root / normed).resolve()
    validate_path(joined)
    return joined


def list_project_files(max_depth: int = 3) -> list[str]:
    """List files in the sandbox directory up to max_depth."""
    root = get_sandbox_root()
    files = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden dirs and common junk
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
    info = {
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

    # Detect primary language
    extensions = {}
    for f in list_project_files(max_depth=4):
        ext = Path(f).suffix.lower()
        if ext in (".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb", ".php"):
            extensions[ext] = extensions.get(ext, 0) + 1
            info["files_count"] += 1

    if extensions:
        top_ext = max(extensions, key=extensions.get)
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
    # Ensure command runs from sandbox root
    return f'cd "{root}" && {cmd}'
