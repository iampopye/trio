"""Async HuggingFace GGUF downloader with resume + Rich progress.

Prefers ``huggingface_hub.hf_hub_download`` when available (handles auth,
caching, mirrors). Falls back to a direct aiohttp download with HTTP
``Range`` resume against the public CDN URL.

The downloader is consumed by :mod:`triobot.cli.launch_cmd`. It is intentionally
decoupled from the rest of trio — no shared logging, no shared HTTP client.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import aiohttp
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)


logger = logging.getLogger(__name__)
_console = Console()


_TOKEN_PATTERN = re.compile(r"(?i)(bearer\s+|hf_)[A-Za-z0-9_-]{8,}")


def _redact_secrets(text: str) -> str:
    """Strip likely HF tokens and bearer credentials from ``text`` before logging."""
    return _TOKEN_PATTERN.sub("[REDACTED]", text)


# Treat the download as "already complete" when the partial file is at least
# this fraction of the expected GGUF size. Lets users skip a redundant probe
# when they already downloaded the file via another tool.
COMPLETE_THRESHOLD = 0.95

# Tunables for the streaming downloader.
_CHUNK_BYTES = 1024 * 1024            # 1 MiB
_REQUEST_TIMEOUT = 60 * 60            # 1 hour for the whole transfer
_CONNECT_TIMEOUT = 30                 # 30 seconds to establish the TCP+TLS conn


class HFDownloadError(RuntimeError):
    """Raised for unrecoverable HuggingFace download failures."""

    def __init__(self, message: str, *, status: Optional[int] = None, url: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.url = url


@dataclass(frozen=True)
class DownloadResult:
    """Result of a successful download."""

    path: Path
    bytes_total: int
    was_cached: bool


# ── URL validation ────────────────────────────────────────────────────────────

def _validate_https_url(url: str) -> str:
    """Reject non-HTTPS URLs early (B310 mitigation)."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HFDownloadError(
            f"Refusing non-HTTPS URL: {parsed.scheme!r}",
            url=url,
        )
    if not parsed.netloc:
        raise HFDownloadError("Empty host in URL", url=url)
    return url


# ── Pre-flight checks ─────────────────────────────────────────────────────────

def ensure_disk_space(dest_dir: Path, required_gb: float) -> None:
    """Raise :class:`HFDownloadError` if ``dest_dir`` does not have enough room.

    Adds a 10% safety buffer on top of the declared GGUF size.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    needed_bytes = int(required_gb * 1.1 * 1_000_000_000)
    free = shutil.disk_usage(dest_dir).free
    if free < needed_bytes:
        free_gb = free / 1_000_000_000
        raise HFDownloadError(
            f"Not enough free disk space at {dest_dir}: "
            f"need ~{required_gb * 1.1:.1f} GB, have {free_gb:.1f} GB free.",
        )


def _looks_complete(path: Path, expected_gb: float) -> bool:
    """True if ``path`` exists and is at least ``COMPLETE_THRESHOLD`` of expected size."""
    if not path.exists():
        return False
    expected_bytes = expected_gb * 1_000_000_000
    return path.stat().st_size >= expected_bytes * COMPLETE_THRESHOLD


# ── Public API ────────────────────────────────────────────────────────────────

async def download_gguf(
    *,
    hf_repo: str,
    filename: str,
    dest: Path,
    expected_size_gb: float,
    hf_token: Optional[str] = None,
) -> DownloadResult:
    """Download ``filename`` from HuggingFace repo ``hf_repo`` into ``dest``.

    - If ``huggingface_hub`` is importable, uses ``hf_hub_download`` (auth, retries).
    - Otherwise streams from the public CDN with HTTP Range resume.
    - Returns a :class:`DownloadResult` on success.

    Raises :class:`HFDownloadError` for permanent failures (404, no space).
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # 1. Skip-if-cached fast path.
    if _looks_complete(dest, expected_size_gb):
        size = dest.stat().st_size
        _console.print(
            f"[dim]Found cached GGUF at {dest} ({size / 1e9:.2f} GB); "
            f"skipping download.[/dim]"
        )
        return DownloadResult(path=dest, bytes_total=size, was_cached=True)

    # 2. Disk space pre-check.
    ensure_disk_space(dest.parent, expected_size_gb)

    # 3. Prefer huggingface_hub if installed.
    hub_path = await _try_hf_hub_download(
        hf_repo=hf_repo,
        filename=filename,
        dest=dest,
        hf_token=hf_token,
    )
    if hub_path is not None:
        size = hub_path.stat().st_size
        return DownloadResult(path=hub_path, bytes_total=size, was_cached=False)

    # 4. Fallback: direct aiohttp download with resume.
    url = f"https://huggingface.co/{hf_repo}/resolve/main/{filename}"
    _validate_https_url(url)
    await _stream_download(url=url, dest=dest, hf_token=hf_token)
    size = dest.stat().st_size
    return DownloadResult(path=dest, bytes_total=size, was_cached=False)


# ── huggingface_hub path ──────────────────────────────────────────────────────

async def _try_hf_hub_download(
    *,
    hf_repo: str,
    filename: str,
    dest: Path,
    hf_token: Optional[str],
) -> Optional[Path]:
    """Try ``hf_hub_download``; return final path on success or ``None`` to fall back."""
    try:
        from huggingface_hub import hf_hub_download  # type: ignore
    except ImportError:
        return None

    _console.print("[dim]Using huggingface_hub for download...[/dim]")

    def _run() -> str:
        # Synchronous call; run in a worker thread.
        return hf_hub_download(
            repo_id=hf_repo,
            filename=filename,
            local_dir=str(dest.parent),
            token=hf_token,
        )

    try:
        downloaded_str = await asyncio.to_thread(_run)
    except Exception as exc:  # broad: hub raises many error subtypes
        logger.warning(
            "huggingface_hub failed (%s); falling back to direct download.",
            _redact_secrets(str(exc)),
        )
        return None

    downloaded = Path(downloaded_str)
    if downloaded.resolve() != dest.resolve():
        try:
            shutil.move(str(downloaded), str(dest))
        except OSError:
            # If move fails (cross-volume / locked), copy + unlink.
            shutil.copy2(str(downloaded), str(dest))
            try:
                downloaded.unlink()
            except OSError:
                pass  # nosec B110 — best-effort cleanup
    return dest


# ── aiohttp streaming + resume ────────────────────────────────────────────────

async def _stream_download(*, url: str, dest: Path, hf_token: Optional[str]) -> None:
    """Stream ``url`` to ``dest`` with Range resume and a Rich progress bar."""
    part = dest.with_suffix(dest.suffix + ".part")
    resume_from = part.stat().st_size if part.exists() else 0

    headers: dict[str, str] = {}
    if hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"
    if resume_from > 0:
        headers["Range"] = f"bytes={resume_from}-"

    timeout = aiohttp.ClientTimeout(
        total=_REQUEST_TIMEOUT,
        connect=_CONNECT_TIMEOUT,
    )

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=headers, allow_redirects=True) as resp:
            await _handle_response_status(resp, url=url, resume_from=resume_from, part=part)

            # If we asked for a Range and got 416, treat as already complete.
            if resp.status == 416:
                if part.exists():
                    part.replace(dest)
                return

            # If server ignored Range and returned 200, restart from scratch.
            if resume_from > 0 and resp.status == 200:
                resume_from = 0
                part.unlink(missing_ok=True)

            total_size = _compute_total_size(resp, resume_from)

            mode = "ab" if resume_from > 0 else "wb"
            await _write_with_progress(
                resp=resp,
                part=part,
                mode=mode,
                resume_from=resume_from,
                total_size=total_size,
                display_name=dest.name,
            )

    part.replace(dest)


async def _handle_response_status(
    resp: aiohttp.ClientResponse,
    *,
    url: str,
    resume_from: int,
    part: Path,
) -> None:
    """Translate HTTP status codes into :class:`HFDownloadError` where appropriate."""
    if resp.status == 404:
        raise HFDownloadError(
            f"HuggingFace returned 404 for {url}",
            status=404,
            url=url,
        )
    if resp.status == 401 or resp.status == 403:
        raise HFDownloadError(
            f"HuggingFace returned {resp.status} for {url} "
            "(authentication required; set HF_TOKEN if the repo is private).",
            status=resp.status,
            url=url,
        )
    if resp.status not in (200, 206, 416):
        raise HFDownloadError(
            f"HuggingFace returned unexpected status {resp.status} for {url}",
            status=resp.status,
            url=url,
        )


def _compute_total_size(resp: aiohttp.ClientResponse, resume_from: int) -> Optional[int]:
    """Derive the total file size from response headers (best effort)."""
    # On 206 Partial Content, Content-Length is the *remaining* bytes.
    content_length = resp.headers.get("Content-Length")
    if content_length is None:
        return None
    try:
        remaining = int(content_length)
    except ValueError:
        return None
    if resp.status == 206:
        return resume_from + remaining
    return remaining


async def _write_with_progress(
    *,
    resp: aiohttp.ClientResponse,
    part: Path,
    mode: str,
    resume_from: int,
    total_size: Optional[int],
    display_name: str,
) -> None:
    """Stream the response body into ``part`` with a Rich progress bar."""
    progress = Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=_console,
        transient=False,
    )

    with progress:
        task_id = progress.add_task(
            f"Downloading {display_name}",
            total=total_size,
            completed=resume_from,
        )

        try:
            with open(part, mode) as fh:
                async for chunk in resp.content.iter_chunked(_CHUNK_BYTES):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    progress.update(task_id, advance=len(chunk))
        except asyncio.CancelledError:
            # Preserve .part so the next run can resume.
            raise
