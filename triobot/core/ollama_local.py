"""Local Ollama daemon helpers used by the ``triobot`` launcher.

These wrappers avoid pulling in ``aiohttp`` for daemon health checks (so
the probe stays cheap) and shell out to ``ollama`` for ``create``/``list``.

Every subprocess call passes ``shell=False`` and a list of args. No string
interpolation. The list-of-args form is required for B603/B607 safety.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess  # nosec B404 — required for ollama CLI
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from urllib.request import Request, build_opener, urlopen, ProxyHandler
from urllib.error import URLError


logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
_DAEMON_STARTUP_TRIES = 5
_DAEMON_STARTUP_DELAY_SECONDS = 1.0
_CREATE_TIMEOUT_SECONDS = 900  # 15 minutes for large GGUF imports


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LocalModel:
    """One installed model as reported by ``/api/tags``."""

    name: str
    size_bytes: int

    @property
    def base_name(self) -> str:
        """Strip the ``:tag`` suffix Ollama adds to model names."""
        return self.name.split(":", 1)[0]


@dataclass(frozen=True)
class CreateResult:
    """Result of ``ollama create``."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


# ── URL validation ────────────────────────────────────────────────────────────

def _validate_local_url(url: str) -> str:
    """Reject anything that's not HTTP(S) (B310 mitigation)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme!r}")
    return url


def _api_url(host: str, path: str) -> str:
    """Join ``host`` and an ``/api/...`` path safely."""
    host = host.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return _validate_local_url(host + path)


def _is_loopback(url: str) -> bool:
    """True if the URL targets a loopback host (proxy should be bypassed)."""
    hostname = (urlparse(url).hostname or "").lower()
    return hostname in ("localhost", "127.0.0.1", "::1")


def _proxy_env_set() -> bool:
    """True if any HTTP(S)_PROXY env var is set in the current environment."""
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        if os.environ.get(var):
            return True
    return False


def _open_url(req: Request, timeout: float, url: str):
    """Open ``req``, bypassing HTTP(S)_PROXY env vars for loopback targets."""
    if _is_loopback(url) and _proxy_env_set():
        opener = build_opener(ProxyHandler({}))
        return opener.open(req, timeout=timeout)  # nosec B310 — scheme validated
    return urlopen(req, timeout=timeout)  # nosec B310 — scheme validated


# ── Public API ────────────────────────────────────────────────────────────────

def is_installed() -> bool:
    """True if the ``ollama`` executable is on PATH."""
    return shutil.which("ollama") is not None


def is_running(host: str = DEFAULT_OLLAMA_HOST, timeout: float = 3.0) -> bool:
    """True if the Ollama daemon at ``host`` responds to ``/api/tags``."""
    try:
        url = _api_url(host, "/api/tags")
    except ValueError:
        return False

    req = Request(url, headers={"Accept": "application/json"})
    try:
        with _open_url(req, timeout=timeout, url=url) as resp:
            return 200 <= resp.status < 500
    except (URLError, TimeoutError, OSError):
        return False


def start_daemon() -> bool:
    """Best-effort start of ``ollama serve`` in the background.

    Returns True if a child process was spawned; the caller is responsible
    for retry-polling :func:`is_running`.
    """
    if not is_installed():
        return False

    creationflags = 0
    start_new_session = False
    if sys.platform == "win32":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        creationflags = 0x00000008 | 0x00000200
    else:
        start_new_session = True

    try:
        subprocess.Popen(  # nosec B603 B607 — list args, no shell
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            start_new_session=start_new_session,
        )
        return True
    except (OSError, ValueError) as exc:
        logger.warning("Failed to start ollama serve: %s", exc)
        return False


def wait_for_daemon(
    host: str = DEFAULT_OLLAMA_HOST,
    tries: int = _DAEMON_STARTUP_TRIES,
    delay: float = _DAEMON_STARTUP_DELAY_SECONDS,
) -> bool:
    """Poll :func:`is_running` up to ``tries`` times, sleeping ``delay`` between."""
    for _ in range(max(tries, 1)):
        if is_running(host=host, timeout=2.0):
            return True
        time.sleep(delay)
    return False


def list_local_models(host: str = DEFAULT_OLLAMA_HOST) -> list[LocalModel]:
    """Return all models installed in the local Ollama instance.

    Parses ``GET /api/tags``. Returns an empty list on any error.
    """
    try:
        url = _api_url(host, "/api/tags")
    except ValueError:
        return []

    req = Request(url, headers={"Accept": "application/json"})
    try:
        with _open_url(req, timeout=5, url=url) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.debug("list_local_models failed: %s", exc)
        return []

    items: list[LocalModel] = []
    for raw in payload.get("models", []) or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("model") or "").strip()
        if not name:
            continue
        try:
            size_bytes = int(raw.get("size") or 0)
        except (TypeError, ValueError):
            size_bytes = 0
        items.append(LocalModel(name=name, size_bytes=size_bytes))
    return items


def is_model_installed(name: str, host: str = DEFAULT_OLLAMA_HOST) -> bool:
    """True if a model whose base name matches ``name`` is already installed."""
    target = name.split(":", 1)[0]
    for m in list_local_models(host=host):
        if m.base_name == target:
            return True
    return False


def create_model(
    name: str,
    modelfile_path: str,
    cwd: str,
    timeout: int = _CREATE_TIMEOUT_SECONDS,
) -> CreateResult:
    """Run ``ollama create <name> -f <modelfile_path>`` in ``cwd``.

    ``modelfile_path`` is passed as-given (typically a *relative* filename so
    the Modelfile's ``FROM ./X.gguf`` directive resolves correctly against
    ``cwd``).
    """
    cmd = ["ollama", "create", name, "-f", modelfile_path]
    try:
        proc = subprocess.run(  # nosec B603 B607 — list args, no shell
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CreateResult(
            returncode=124,
            stdout=exc.stdout or "",
            stderr=(exc.stderr or "") + f"\n[ollama create timed out after {timeout}s]",
        )
    except (OSError, ValueError) as exc:
        return CreateResult(returncode=1, stdout="", stderr=str(exc))

    return CreateResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )


def ensure_alias(
    src_modelfile: str,
    cwd: str,
    alias_name: str,
    timeout: int = _CREATE_TIMEOUT_SECONDS,
) -> CreateResult:
    """Register ``alias_name`` so ``ollama run <alias_name>`` works.

    Re-runs ``ollama create`` against the same Modelfile. Ollama treats this
    as an upsert, so it's safe to overwrite an existing alias.
    """
    return create_model(
        name=alias_name,
        modelfile_path=src_modelfile,
        cwd=cwd,
        timeout=timeout,
    )


# ── Misc ──────────────────────────────────────────────────────────────────────

def models_dir() -> Path:
    """Return the directory where triobot stores downloaded GGUFs.

    Honors the ``TRIO_MODELS_DIR`` environment variable; otherwise defaults
    to ``~/.trio/models``.
    """
    override = os.environ.get("TRIO_MODELS_DIR")
    if override:
        path = Path(override).expanduser()
    else:
        path = Path.home() / ".trio" / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ollama_host() -> str:
    """Return the configured Ollama host URL (honors ``OLLAMA_HOST``)."""
    return os.environ.get("OLLAMA_HOST") or DEFAULT_OLLAMA_HOST
