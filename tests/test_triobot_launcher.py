"""Unit tests for the triobot launcher feature.

Covers:
- triobot.core.trio_lineup: tier definitions
- triobot.core.ollama_local: install/run checks, model listing, create
- triobot.core.hf_download: disk-space check, 404 path, huggingface_hub path
- triobot.cli.launch_cmd: --version, --tier, --no-launch flag behaviors
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT.

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Imports under test ────────────────────────────────────────────────────────

from triobot.core.trio_lineup import (
    TRIO_LINEUP,
    TrioTier,
    get_tier,
    tier_names,
)
from triobot.core import ollama_local
from triobot.core.ollama_local import (
    LocalModel,
    create_model,
    is_installed,
    is_model_installed,
    list_local_models,
)
from triobot.core import hf_download
from triobot.core.hf_download import (
    HFDownloadError,
    download_gguf,
    ensure_disk_space,
)
from triobot.cli import launch_cmd


# ── Lineup tests ──────────────────────────────────────────────────────────────


def test_lineup_has_six_tiers():
    """Lineup must contain exactly 6 tiers in nano→pro order."""
    assert len(TRIO_LINEUP) == 6
    expected_order = [
        "trio-nano",
        "trio-small",
        "trio-medium",
        "trio-high",
        "trio-max",
        "trio-pro",
    ]
    assert [t.name for t in TRIO_LINEUP] == expected_order


def test_lineup_repos_use_mrtechgarg():
    """Every hf_repo must start with mrtechgarg/trio-."""
    for tier in TRIO_LINEUP:
        assert tier.hf_repo.startswith("mrtechgarg/trio-"), (
            f"{tier.name} has unexpected repo: {tier.hf_repo}"
        )


def test_lineup_gguf_filenames_match_convention():
    """Every gguf_filename must be trio-<tier>-q4_k_m.gguf."""
    for tier in TRIO_LINEUP:
        # name is "trio-X"; gguf should be "trio-X-q4_k_m.gguf"
        suffix = tier.name[len("trio-") :]  # noqa: E203
        expected = f"trio-{suffix}-q4_k_m.gguf"
        assert tier.gguf_filename == expected, (
            f"{tier.name}: expected {expected}, got {tier.gguf_filename}"
        )


def test_get_tier_by_name_returns_entry_or_none():
    """get_tier returns the matching tier or None."""
    found = get_tier("trio-small")
    assert found is not None
    assert isinstance(found, TrioTier)
    assert found.name == "trio-small"

    assert get_tier("trio-bogus") is None
    assert get_tier("") is None


# ── ollama_local tests ────────────────────────────────────────────────────────


def test_is_installed_returns_false_when_which_is_none(monkeypatch: pytest.MonkeyPatch):
    """When shutil.which returns None, is_installed() returns False."""
    monkeypatch.setattr(ollama_local.shutil, "which", lambda _name: None)
    assert is_installed() is False


def test_is_installed_returns_true_when_which_finds_binary(monkeypatch: pytest.MonkeyPatch):
    """When shutil.which returns a path, is_installed() returns True."""
    monkeypatch.setattr(ollama_local.shutil, "which", lambda _name: "/usr/bin/ollama")
    assert is_installed() is True


class _FakeResponse:
    """Stand-in for urlopen's context-manager response object."""

    def __init__(self, payload: bytes, status: int = 200):
        self._payload = payload
        self.status = status

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_list_local_models_parses_api_tags(monkeypatch: pytest.MonkeyPatch):
    """list_local_models() parses the /api/tags JSON payload."""
    payload = {
        "models": [
            {"name": "trio-small:latest", "size": 2_400_000_000},
            {"name": "llama3:8b", "size": 4_700_000_000},
        ]
    }
    body = json.dumps(payload).encode("utf-8")

    def _fake_urlopen(_req, timeout=None):
        return _FakeResponse(body)

    # Patch the urlopen reference inside ollama_local
    monkeypatch.setattr(ollama_local, "urlopen", _fake_urlopen)

    models = list_local_models()
    names = [m.name for m in models]
    base_names = [m.base_name for m in models]
    assert "trio-small:latest" in names
    assert "llama3:8b" in names
    assert "trio-small" in base_names
    assert "llama3" in base_names


def test_list_local_models_returns_empty_on_connection_error(
    monkeypatch: pytest.MonkeyPatch,
):
    """When urlopen raises, list_local_models() returns []."""
    from urllib.error import URLError

    def _raise(*_args, **_kwargs):
        raise URLError("connection refused")

    monkeypatch.setattr(ollama_local, "urlopen", _raise)
    assert list_local_models() == []


def test_create_model_runs_ollama_with_list_args_and_no_shell(
    monkeypatch: pytest.MonkeyPatch,
):
    """create_model must invoke ollama via a list, not shell=True."""
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        completed = subprocess.CompletedProcess(args=cmd, returncode=0, stdout="ok", stderr="")
        return completed

    monkeypatch.setattr(ollama_local.subprocess, "run", _fake_run)
    result = create_model(name="trio-small", modelfile_path="trio-small.Modelfile", cwd="/tmp")

    assert isinstance(captured["cmd"], list)
    assert captured["cmd"][0] == "ollama"
    assert captured["cmd"][1] == "create"
    assert "trio-small" in captured["cmd"]
    # shell must NOT be True (either absent or False)
    assert captured["kwargs"].get("shell") is not True
    assert result.ok is True


def test_create_model_returns_zero_on_success(monkeypatch: pytest.MonkeyPatch):
    """create_model returns CreateResult with ok=True/returncode=0 on success."""

    def _fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="done", stderr="")

    monkeypatch.setattr(ollama_local.subprocess, "run", _fake_run)
    result = create_model(name="trio-small", modelfile_path="x.Modelfile", cwd="/tmp")
    assert result.returncode == 0
    assert result.ok is True


def test_create_model_returns_nonzero_on_failure(monkeypatch: pytest.MonkeyPatch):
    """create_model surfaces the nonzero exit from ollama."""

    def _fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=2, stdout="", stderr="boom")

    monkeypatch.setattr(ollama_local.subprocess, "run", _fake_run)
    result = create_model(name="trio-small", modelfile_path="x.Modelfile", cwd="/tmp")
    assert result.returncode == 2
    assert result.ok is False
    assert "boom" in result.stderr


# ── hf_download tests ────────────────────────────────────────────────────────


def test_disk_space_check_blocks_when_insufficient(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """ensure_disk_space raises HFDownloadError when free space is below requirement."""
    # 0.5 GB free, asking for 5 GB
    FakeUsage = types.SimpleNamespace
    monkeypatch.setattr(
        hf_download.shutil,
        "disk_usage",
        lambda _path: FakeUsage(total=10**10, used=10**10 - 5 * 10**8, free=5 * 10**8),
    )
    with pytest.raises(HFDownloadError) as excinfo:
        ensure_disk_space(tmp_path, required_gb=5.0)
    assert "disk space" in str(excinfo.value).lower() or "free" in str(excinfo.value).lower()


def test_disk_space_check_passes_when_sufficient(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """ensure_disk_space returns silently when there's plenty of room."""
    FakeUsage = types.SimpleNamespace
    monkeypatch.setattr(
        hf_download.shutil,
        "disk_usage",
        lambda _path: FakeUsage(total=10**12, used=10**11, free=10**11),
    )
    # Should not raise
    ensure_disk_space(tmp_path, required_gb=5.0)


# ── async download error path ────────────────────────────────────────────────


class _FakeAioResponse:
    """Minimal async-context-manager for aiohttp ClientResponse."""

    def __init__(self, status: int, headers: dict | None = None):
        self.status = status
        self.headers = headers or {}
        # body iterator: empty for error tests
        self.content = self  # for iter_chunked access

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def iter_chunked(self, _n):
        if False:
            yield b""
        return


class _FakeAioSession:
    """Minimal async-context-manager fake aiohttp ClientSession."""

    def __init__(self, status: int):
        self._status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, _url, headers=None, allow_redirects=True):
        return _FakeAioResponse(status=self._status)


@pytest.mark.asyncio
async def test_404_raises_clear_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """A 404 from HF must raise HFDownloadError whose message includes URL + 404."""
    dest = tmp_path / "trio-nano-q4_k_m.gguf"

    # Block the huggingface_hub fast path so we exercise the aiohttp branch.
    # Patch the function attribute reference inside hf_download.
    async def _force_no_hub(**_kwargs):
        return None

    monkeypatch.setattr(hf_download, "_try_hf_hub_download", _force_no_hub)

    # Skip disk-space pre-check
    monkeypatch.setattr(hf_download, "ensure_disk_space", lambda _d, _g: None)

    # Replace aiohttp.ClientSession with a fake that yields a 404 response.
    def _fake_session_ctor(*_args, **_kwargs):
        return _FakeAioSession(status=404)

    monkeypatch.setattr(hf_download.aiohttp, "ClientSession", _fake_session_ctor)

    with pytest.raises(HFDownloadError) as excinfo:
        await download_gguf(
            hf_repo="mrtechgarg/trio-nano",
            filename="trio-nano-q4_k_m.gguf",
            dest=dest,
            expected_size_gb=1.0,
        )
    msg = str(excinfo.value)
    assert "404" in msg
    assert "huggingface.co" in msg or excinfo.value.url


@pytest.mark.asyncio
async def test_huggingface_hub_path_used_when_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """When huggingface_hub is importable, hf_hub_download is preferred over aiohttp."""
    dest = tmp_path / "trio-nano-q4_k_m.gguf"
    # Write a fake "downloaded" file the hub path will hand back.
    fake_downloaded = tmp_path / "trio-nano-q4_k_m.gguf"

    def _fake_hf_hub_download(repo_id, filename, local_dir, token=None):
        # Simulate the file being downloaded into local_dir
        p = Path(local_dir) / filename
        p.write_bytes(b"x" * (1_000_000_000))  # 1 GB-ish but we won't actually check size strictly
        return str(p)

    # Skip disk pre-check (we wrote 1GB above, host may be tight)
    monkeypatch.setattr(hf_download, "ensure_disk_space", lambda _d, _g: None)
    # Skip the "_looks_complete" path so we exercise the download branch.
    monkeypatch.setattr(hf_download, "_looks_complete", lambda _p, _gb: False)

    # Inject a fake huggingface_hub module into sys.modules so the local
    # `from huggingface_hub import hf_hub_download` inside _try_hf_hub_download
    # finds it.
    fake_mod = types.ModuleType("huggingface_hub")
    fake_mock = MagicMock(side_effect=_fake_hf_hub_download)
    fake_mod.hf_hub_download = fake_mock
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_mod)

    # Sentinel: if aiohttp.ClientSession is used, fail loudly.
    def _explode(*_a, **_kw):
        raise AssertionError("aiohttp.ClientSession should not be used when hf_hub_download is available")

    monkeypatch.setattr(hf_download.aiohttp, "ClientSession", _explode)

    result = await download_gguf(
        hf_repo="mrtechgarg/trio-nano",
        filename="trio-nano-q4_k_m.gguf",
        dest=dest,
        expected_size_gb=1.0,
    )

    assert fake_mock.called, "hf_hub_download was not called"
    assert result.path.exists()


# ── launch_cmd tests ──────────────────────────────────────────────────────────


def test_main_with_version_flag_prints_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """`triobot --version` prints version string and exits 0."""
    monkeypatch.setattr(sys, "argv", ["triobot", "--version"])
    with pytest.raises(SystemExit) as excinfo:
        launch_cmd.main()
    # argparse `--version` writes to stdout in py3.4+
    captured = capsys.readouterr()
    output = (captured.out + captured.err).lower()
    assert "triobot" in output
    assert excinfo.value.code == 0


def test_main_exits_1_when_ollama_not_installed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """When ollama isn't installed, main exits 1 and prints install URL."""
    monkeypatch.setattr(sys, "argv", ["triobot"])
    # Force the launcher's view of ollama: not installed.
    monkeypatch.setattr(launch_cmd, "ollama_is_installed", lambda: False)

    with pytest.raises(SystemExit) as excinfo:
        launch_cmd.main()

    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "ollama.com/download" in out


def test_main_with_tier_flag_skips_picker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """--tier should bypass the picker entirely."""
    monkeypatch.setattr(sys, "argv", ["triobot", "--tier", "trio-small", "--no-launch"])

    # Ollama is installed and running
    monkeypatch.setattr(launch_cmd, "ollama_is_installed", lambda: True)
    monkeypatch.setattr(launch_cmd, "ollama_is_running", lambda host=None, timeout=2.0: True)
    monkeypatch.setattr(launch_cmd, "resolve_ollama_host", lambda: "http://localhost:11434")

    # Model already installed → no download/create path
    monkeypatch.setattr(launch_cmd, "is_model_installed", lambda name, host=None: True)

    # Alias registration should be a no-op success
    monkeypatch.setattr(launch_cmd, "_register_alias", lambda *, tier, staging=None: True)

    # Persist config to a temp HOME-like location
    monkeypatch.setattr(launch_cmd, "_persist_provider_config", lambda *, tier, host: None)

    # Picker MUST NOT be called
    def _picker_explode():
        raise AssertionError("Picker was invoked despite --tier flag")

    monkeypatch.setattr(launch_cmd, "_show_picker", _picker_explode)

    with pytest.raises(SystemExit) as excinfo:
        launch_cmd.main()
    assert excinfo.value.code == 0


def test_main_with_no_launch_flag_does_not_call_run_agent(monkeypatch: pytest.MonkeyPatch):
    """--no-launch must skip importing/calling run_agent."""
    monkeypatch.setattr(sys, "argv", ["triobot", "--tier", "trio-small", "--no-launch"])

    monkeypatch.setattr(launch_cmd, "ollama_is_installed", lambda: True)
    monkeypatch.setattr(launch_cmd, "ollama_is_running", lambda host=None, timeout=2.0: True)
    monkeypatch.setattr(launch_cmd, "resolve_ollama_host", lambda: "http://localhost:11434")
    monkeypatch.setattr(launch_cmd, "is_model_installed", lambda name, host=None: True)
    monkeypatch.setattr(launch_cmd, "_register_alias", lambda *, tier, staging=None: True)
    monkeypatch.setattr(launch_cmd, "_persist_provider_config", lambda *, tier, host: None)

    # If run_agent gets called, blow up. It's imported lazily inside run_launch,
    # so inject a fake `triobot.cli.agent` module beforehand.
    fake_agent_mod = types.ModuleType("triobot.cli.agent")

    async def _explode(**_kwargs):
        raise AssertionError("run_agent should NOT be called when --no-launch is set")

    fake_agent_mod.run_agent = _explode
    monkeypatch.setitem(sys.modules, "triobot.cli.agent", fake_agent_mod)

    with pytest.raises(SystemExit) as excinfo:
        launch_cmd.main()
    assert excinfo.value.code == 0
