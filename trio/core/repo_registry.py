"""Multi-repo registry — manage multiple project workspaces.

trio.ai users often work on more than one project. The repo registry
lets them register repos by alias, switch between them, and search
across all of them.

Storage: ~/.trio/repos.json

Example:
    from trio.core.repo_registry import RepoRegistry

    reg = RepoRegistry()
    reg.register("my-app", "/home/user/projects/my-app")
    reg.register("trio", "/home/user/dev/trio")

    reg.list()                              # ["my-app", "trio"]
    reg.get("my-app")                       # RepoEntry(...)
    reg.set_active("trio")                  # Switch active repo
    reg.search("README")                    # Search across all repos
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from trio.core.config import get_trio_dir

logger = logging.getLogger(__name__)

REGISTRY_FILE = "repos.json"


@dataclass
class RepoEntry:
    """A registered repository."""

    alias: str
    path: str
    description: str = ""
    language: str = ""
    is_git: bool = False
    registered_at: float = field(default_factory=time.time)
    last_used_at: float = 0.0
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RepoEntry":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def exists(self) -> bool:
        return Path(self.path).is_dir()


class RepoRegistry:
    """Persistent registry of trio.ai workspaces.

    Storage layout (~/.trio/repos.json):
        {
            "active": "alias",
            "repos": [
                {"alias": "...", "path": "...", ...},
                ...
            ]
        }
    """

    def __init__(self):
        self._path = get_trio_dir() / REGISTRY_FILE
        self._active: str | None = None
        self._repos: dict[str, RepoEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._active = data.get("active")
            for raw in data.get("repos", []):
                entry = RepoEntry.from_dict(raw)
                self._repos[entry.alias] = entry
        except Exception as e:
            logger.warning("Failed to load repo registry: %s", e)

    def _save(self) -> None:
        try:
            data = {
                "active": self._active,
                "repos": [r.to_dict() for r in self._repos.values()],
            }
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            try:
                self._path.chmod(0o600)
            except (OSError, NotImplementedError):
                pass
        except Exception as e:
            logger.error("Failed to save repo registry: %s", e)

    # ── Public API ────────────────────────────────────────────────────────

    def register(
        self,
        alias: str,
        path: str | Path,
        description: str = "",
        language: str = "",
        tags: list[str] | None = None,
    ) -> RepoEntry:
        """Register a new repo (or update an existing one)."""
        alias = alias.strip().lower()
        if not alias or "/" in alias or "\\" in alias:
            raise ValueError(f"Invalid alias: {alias!r}")

        repo_path = Path(path).expanduser().resolve()
        if not repo_path.is_dir():
            raise ValueError(f"Path is not a directory: {repo_path}")

        is_git = (repo_path / ".git").is_dir()
        # Auto-detect language from common files
        if not language:
            language = self._detect_language(repo_path)

        entry = RepoEntry(
            alias=alias,
            path=str(repo_path),
            description=description,
            language=language,
            is_git=is_git,
            tags=tags or [],
        )
        self._repos[alias] = entry
        if self._active is None:
            self._active = alias
        self._save()
        logger.info("Registered repo: %s → %s", alias, repo_path)
        return entry

    def unregister(self, alias: str) -> bool:
        """Remove a repo from the registry."""
        alias = alias.strip().lower()
        if alias not in self._repos:
            return False
        del self._repos[alias]
        if self._active == alias:
            self._active = next(iter(self._repos), None)
        self._save()
        return True

    def list(self) -> list[RepoEntry]:
        """List all registered repos."""
        return list(self._repos.values())

    def get(self, alias: str) -> RepoEntry | None:
        """Look up a repo by alias."""
        return self._repos.get(alias.strip().lower())

    def set_active(self, alias: str) -> bool:
        """Mark a repo as the active one."""
        alias = alias.strip().lower()
        if alias not in self._repos:
            return False
        self._active = alias
        self._repos[alias].last_used_at = time.time()
        self._save()
        return True

    def get_active(self) -> RepoEntry | None:
        """Return the currently active repo."""
        if self._active and self._active in self._repos:
            return self._repos[self._active]
        return None

    def search(self, query: str, max_results: int = 20) -> list[tuple[RepoEntry, Path]]:
        """Search filenames across all registered repos.

        Returns a list of (repo, matching file) tuples. Limited to max_results.
        """
        query = query.strip().lower()
        if not query:
            return []

        results: list[tuple[RepoEntry, Path]] = []
        for repo in self._repos.values():
            if not repo.exists():
                continue
            try:
                root = Path(repo.path)
                for match in root.rglob(f"*{query}*"):
                    if not match.is_file():
                        continue
                    # Skip noise
                    if any(p in match.parts for p in (".git", "__pycache__", "node_modules", ".venv")):
                        continue
                    results.append((repo, match))
                    if len(results) >= max_results:
                        return results
            except Exception:
                continue
        return results

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _detect_language(path: Path) -> str:
        """Best-effort language detection from common project files."""
        markers = {
            "python": ["pyproject.toml", "requirements.txt", "setup.py", "Pipfile"],
            "javascript": ["package.json", "yarn.lock", "pnpm-lock.yaml"],
            "typescript": ["tsconfig.json"],
            "rust": ["Cargo.toml"],
            "go": ["go.mod"],
            "java": ["pom.xml", "build.gradle"],
            "ruby": ["Gemfile"],
            "php": ["composer.json"],
            "csharp": ["*.csproj"],
            "elixir": ["mix.exs"],
        }
        for lang, files in markers.items():
            for f in files:
                if "*" in f:
                    if list(path.glob(f)):
                        return lang
                elif (path / f).exists():
                    return lang
        return "unknown"
