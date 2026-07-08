"""``triobot`` — pick a trio tier, auto-install it via Ollama, drop into chat.

Entry point for the standalone ``triobot`` command (see ``pyproject.toml``)
and the ``trio launch`` subcommand. The flow is:

1. Verify Ollama is installed and reachable (offer to auto-start daemon).
2. Show an arrow-key picker of the 6 tiers; recommend one based on hardware.
3. If the picked tier isn't already registered, download the GGUF from
   HuggingFace and run ``ollama create <tier>`` in a staging dir.
4. Also register the same Modelfile as the alias ``triobot`` so
   ``ollama run triobot`` resolves to whatever the user last picked.
5. Update ``~/.trio/config.json`` to point at Ollama + the new tier.
6. Hand off to ``triobot.cli.agent.run_agent``.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import subprocess  # nosec B404 — used by helpers only
import sys
import tempfile
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.prompt import Confirm

from triobot import __version__
from triobot.core.config import DEFAULT_CONFIG, load_config, save_config
from triobot.core.hf_download import HFDownloadError, download_gguf
from triobot.core.ollama_local import (
    DEFAULT_OLLAMA_HOST,
    create_model,
    ensure_alias,
    is_installed as ollama_is_installed,
    is_model_installed,
    is_running as ollama_is_running,
    list_local_models,
    models_dir as ollama_models_dir,
    ollama_host as resolve_ollama_host,
    start_daemon as start_ollama_daemon,
    wait_for_daemon,
)
from triobot.core.trio_lineup import TRIO_LINEUP, TrioTier, get_tier, tier_names


console = Console()
logger = logging.getLogger(__name__)

ALIAS_NAME = "triobot"

# Exit codes — narrow, documented, scriptable.
EXIT_OK = 0
EXIT_NO_OLLAMA = 1
EXIT_DAEMON_DOWN = 2
EXIT_NOT_FOUND = 3
EXIT_GENERIC = 4
EXIT_USAGE = 64
EXIT_CANCELLED = 130


# ── Public entry points ───────────────────────────────────────────────────────

def main() -> None:
    """Synchronous entry point used by the ``triobot`` console script."""
    parser = _build_arg_parser()
    args = parser.parse_args()

    try:
        exit_code = asyncio.run(
            run_launch(
                tier_name=args.tier,
                no_launch=args.no_launch,
            )
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled. Partial downloads are kept under "
                      "~/.trio/models/ — rerun triobot to resume.[/yellow]")
        sys.exit(EXIT_CANCELLED)
    sys.exit(exit_code)


async def run_launch(
    *,
    tier_name: Optional[str] = None,
    no_launch: bool = False,
) -> int:
    """Run the picker → download → register → chat handoff sequence.

    Returns a process exit code.
    """
    # 1. Ollama installed?
    if not ollama_is_installed():
        _print_install_help()
        return EXIT_NO_OLLAMA

    # 2. Ollama daemon up?
    host = resolve_ollama_host()
    if not _ensure_daemon_running(host):
        return EXIT_DAEMON_DOWN

    # 3. Resolve target tier — flag overrides picker.
    tier = _resolve_target_tier(tier_name)
    if tier is None:
        return EXIT_USAGE

    # 4. Already installed? Skip download + create.
    already_installed = is_model_installed(tier.name, host=host)
    if already_installed:
        console.print(f"[green]✓[/green] {tier.name} is already installed locally.")
    else:
        ok = await _install_tier(tier=tier, host=host)
        if not ok:
            return EXIT_GENERIC

    # 5. Always (re-)register the "triobot" alias so `ollama run triobot` works.
    alias_ok = _register_alias(tier=tier)
    if not alias_ok:
        console.print(
            "[yellow]Warning:[/yellow] failed to register the 'triobot' alias. "
            "You can still run this tier with [cyan]ollama run "
            f"{tier.name}[/cyan]."
        )

    # 6. Persist config so the chat session targets this tier.
    _persist_provider_config(tier=tier, host=host)

    if no_launch:
        console.print(
            f"\n[green]Done.[/green] {tier.name} is registered. "
            "Start a chat anytime with [cyan]trio agent[/cyan] or "
            f"[cyan]ollama run {tier.name}[/cyan]."
        )
        return EXIT_OK

    # 7. Hand off to the existing chat runtime.
    console.print(f"\n[bold cyan]Launching chat with {tier.name}…[/bold cyan]\n")
    from triobot.cli.agent import run_agent  # local import to keep startup snappy
    await run_agent(message=None, no_markdown=False, show_logs=False)
    return EXIT_OK


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="triobot",
        description=(
            "Pick a trio model tier, auto-download it, and drop into chat."
        ),
    )
    parser.add_argument(
        "--tier",
        choices=tier_names(),
        default=None,
        help="Skip the picker and use this tier directly.",
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Register the model but exit without starting chat.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"triobot {__version__}",
    )
    return parser


# ── Daemon orchestration ──────────────────────────────────────────────────────

def _print_install_help() -> None:
    console.print(
        "[red]Ollama is not installed.[/red]\n"
        "Install it from [cyan]https://ollama.com/download[/cyan] and rerun "
        "[cyan]triobot[/cyan]."
    )


def _ensure_daemon_running(host: str) -> bool:
    """Return True when the daemon is reachable; offer to auto-start otherwise."""
    if ollama_is_running(host=host, timeout=2.0):
        return True

    console.print(
        f"[yellow]The Ollama daemon at {host} is not responding.[/yellow]"
    )
    try:
        if not Confirm.ask("Start it now?", default=True):
            console.print("Run [cyan]ollama serve[/cyan] in another terminal and rerun triobot.")
            return False
    except (EOFError, KeyboardInterrupt):
        return False

    if not start_ollama_daemon():
        console.print("[red]Could not spawn 'ollama serve'.[/red]")
        return False

    console.print("[dim]Waiting for the daemon to come up…[/dim]")
    if wait_for_daemon(host=host, tries=5, delay=1.0):
        console.print("[green]✓[/green] Ollama daemon is up.")
        return True

    console.print(
        "[red]The Ollama daemon did not come up in 5s.[/red] "
        "Try [cyan]ollama serve[/cyan] manually and rerun triobot."
    )
    return False


# ── Picker ────────────────────────────────────────────────────────────────────

def _resolve_target_tier(flag: Optional[str]) -> Optional[TrioTier]:
    """Pick a tier from ``--tier`` or via the interactive picker."""
    if flag is not None:
        tier = get_tier(flag)
        if tier is None:
            console.print(f"[red]Unknown tier: {flag}[/red]")
            return None
        return tier

    # Non-TTY without a --tier flag: refuse rather than block forever.
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        console.print(
            "[red]triobot needs an interactive terminal for the picker.[/red]\n"
            "Pass [cyan]--tier <name>[/cyan] (one of: "
            + ", ".join(tier_names()) + ") to skip the picker."
        )
        return None

    return _show_picker()


def _show_picker() -> Optional[TrioTier]:
    """Display the arrow-key picker and return the selected tier (or None)."""
    from prompt_toolkit.shortcuts import radiolist_dialog

    installed = {m.base_name for m in list_local_models()}
    recommended = _recommend_default_tier()

    values: list[tuple[str, str]] = []
    for tier in TRIO_LINEUP:
        installed_tag = " [installed]" if tier.name in installed else ""
        label = (
            f"{tier.name:<12}  {tier.params:>4}  "
            f"~{tier.size_gb:>4.1f} GB  {tier.description}{installed_tag}"
        )
        values.append((tier.name, label))

    console.print(
        "\n[bold cyan]Pick a trio tier[/bold cyan]  "
        "[dim](arrows to move, Enter to select, Esc to cancel)[/dim]\n"
    )

    try:
        result = radiolist_dialog(
            title="triobot",
            text=(
                "Choose the model that fits your machine.\n"
                f"Recommended for your hardware: {recommended}"
            ),
            values=values,
            default=recommended,
        ).run()
    except (KeyboardInterrupt, EOFError):
        return None

    if result is None:
        return None
    return get_tier(result)


def _recommend_default_tier() -> str:
    """Return the recommended tier name based on detected hardware."""
    try:
        from triobot.core.hardware import detect_hardware, recommend_model
        hw = detect_hardware()
        rec = recommend_model(hw)
        candidate = rec.get("name")
        if candidate and get_tier(candidate) is not None:
            return candidate
    except Exception as exc:  # broad: hardware detection should never block the picker
        logger.debug("Hardware-based recommendation failed: %s", exc)
    return "trio-small"


# ── Install pipeline ──────────────────────────────────────────────────────────

async def _install_tier(*, tier: TrioTier, host: str) -> bool:
    """Download the GGUF, stage it, run ``ollama create``. Returns success."""
    dest_dir = ollama_models_dir()
    dest = dest_dir / tier.gguf_filename

    console.print(
        f"\n[bold]Installing {tier.name}[/bold] "
        f"([dim]{tier.params}, ~{tier.size_gb:.1f} GB[/dim])"
    )

    # 1. Download.
    hf_token = os.environ.get("HF_TOKEN") or None
    try:
        result = await download_gguf(
            hf_repo=tier.hf_repo,
            filename=tier.gguf_filename,
            dest=dest,
            expected_size_gb=tier.size_gb,
            hf_token=hf_token,
        )
    except HFDownloadError as exc:
        _print_download_error(exc)
        return False

    if not result.was_cached:
        console.print(
            f"[green]✓[/green] Downloaded {tier.gguf_filename} "
            f"({result.bytes_total / 1e9:.2f} GB)."
        )

    # 2. Stage the Modelfile and GGUF together so `FROM ./X.gguf` resolves.
    staging = Path(tempfile.mkdtemp(prefix=f"triobot-{tier.name}-"))
    success = False
    try:
        staged_modelfile = _stage_for_create(tier=tier, gguf_src=dest, staging=staging)

        # 3. Run `ollama create`.
        console.print(f"[dim]Registering {tier.name} with Ollama…[/dim]")
        create_result = create_model(
            name=tier.name,
            modelfile_path=staged_modelfile.name,
            cwd=str(staging),
        )

        if not create_result.ok:
            tail = (create_result.stderr or "").strip()[-500:]
            console.print(
                f"[red]ollama create failed (exit {create_result.returncode}).[/red]\n"
                f"[dim]Staging dir preserved at: {staging}[/dim]\n"
                f"[dim]--- stderr (last 500 chars) ---[/dim]\n{tail}"
            )
            return False

        console.print(f"[green]✓[/green] Registered [bold]{tier.name}[/bold] with Ollama.")
        # Keep the staging dir alive across the alias re-create; it gets reused.
        _register_alias(tier=tier, staging=staging)
        success = True
    finally:
        if success:
            shutil.rmtree(staging, ignore_errors=True)

    return True


def _stage_for_create(*, tier: TrioTier, gguf_src: Path, staging: Path) -> Path:
    """Hardlink (or copy) the GGUF + write a same-dir Modelfile."""
    staging.mkdir(parents=True, exist_ok=True)
    staged_gguf = staging / tier.gguf_filename

    try:
        os.link(gguf_src, staged_gguf)
    except OSError:
        # Cross-volume on Windows, or filesystem that doesn't support hardlinks.
        shutil.copy2(gguf_src, staged_gguf)

    modelfile_src = _bundled_modelfile_path(tier)
    modelfile_body = _normalize_modelfile_from(modelfile_src.read_text(encoding="utf-8"),
                                               gguf_filename=tier.gguf_filename)
    staged_modelfile = staging / tier.modelfile_name
    staged_modelfile.write_text(modelfile_body, encoding="utf-8")
    return staged_modelfile


def _bundled_modelfile_path(tier: TrioTier) -> Path:
    """Resolve the bundled Modelfile shipped inside the ``trio`` package."""
    return Path(__file__).resolve().parent.parent / "models" / tier.modelfile_name


def _normalize_modelfile_from(body: str, *, gguf_filename: str) -> str:
    """Rewrite the ``FROM`` line so it points at the staged GGUF.

    Idempotent — the bundled Modelfiles already match, but a downloaded
    Modelfile (or one a user edited) could have an absolute path that won't
    work from the staging dir.
    """
    expected_from = f"FROM ./{gguf_filename}"
    lines = body.splitlines()
    for idx, line in enumerate(lines):
        if line.lstrip().upper().startswith("FROM "):
            lines[idx] = expected_from
            break
    else:
        # No FROM line at all — prepend one.
        lines.insert(0, expected_from)
    return "\n".join(lines) + ("\n" if not body.endswith("\n") else "")


def _register_alias(*, tier: TrioTier, staging: Optional[Path] = None) -> bool:
    """Register the ``triobot`` alias against ``tier``'s Modelfile.

    If called *during* an install we can reuse the existing staging dir
    (saves a copy). For standalone calls (already-installed tier), we set
    up a fresh staging dir and pull the GGUF back into it.
    """
    if staging is not None and (staging / tier.modelfile_name).exists():
        result = ensure_alias(
            src_modelfile=tier.modelfile_name,
            cwd=str(staging),
            alias_name=ALIAS_NAME,
        )
        if not result.ok:
            tail = (result.stderr or "").strip()[-500:]
            console.print(
                f"[yellow]Could not register '{ALIAS_NAME}' alias "
                f"(exit {result.returncode}).[/yellow]\n"
                f"[dim]{tail}[/dim]"
            )
            return False
        console.print(f"[green]✓[/green] Aliased as [bold]{ALIAS_NAME}[/bold].")
        return True

    # Standalone path: need a staging dir that has the GGUF + Modelfile.
    gguf_src = ollama_models_dir() / tier.gguf_filename
    if not gguf_src.exists():
        # No local GGUF — Ollama has it but we can't construct a Modelfile.
        # Fall back to a `FROM <tier>` Modelfile so the alias still works.
        return _register_alias_from_local_model(tier)

    tmp = Path(tempfile.mkdtemp(prefix=f"triobot-alias-{tier.name}-"))
    try:
        _stage_for_create(tier=tier, gguf_src=gguf_src, staging=tmp)
        result = ensure_alias(
            src_modelfile=tier.modelfile_name,
            cwd=str(tmp),
            alias_name=ALIAS_NAME,
        )
        if not result.ok:
            tail = (result.stderr or "").strip()[-500:]
            console.print(
                f"[yellow]Could not register '{ALIAS_NAME}' alias "
                f"(exit {result.returncode}).[/yellow]\n[dim]{tail}[/dim]"
            )
            return False
        console.print(f"[green]✓[/green] Aliased as [bold]{ALIAS_NAME}[/bold].")
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _register_alias_from_local_model(tier: TrioTier) -> bool:
    """Last-resort alias: ``FROM <tier>`` referencing the already-registered tag."""
    tmp = Path(tempfile.mkdtemp(prefix=f"triobot-alias-ref-{tier.name}-"))
    try:
        modelfile = tmp / f"{ALIAS_NAME}.Modelfile"
        modelfile.write_text(f"FROM {tier.name}\n", encoding="utf-8")
        result = ensure_alias(
            src_modelfile=modelfile.name,
            cwd=str(tmp),
            alias_name=ALIAS_NAME,
        )
        if not result.ok:
            return False
        console.print(f"[green]✓[/green] Aliased as [bold]{ALIAS_NAME}[/bold].")
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── Config persistence ────────────────────────────────────────────────────────

def _persist_provider_config(*, tier: TrioTier, host: str) -> None:
    """Update ``~/.trio/config.json`` to point the agent at this tier via Ollama."""
    try:
        config = load_config()
    except Exception as exc:
        logger.warning("Could not load existing config (%s); starting from defaults.", exc)
        # Deep copy of the defaults so we don't mutate the module-level dict.
        import copy
        config = copy.deepcopy(DEFAULT_CONFIG)

    providers = config.setdefault("providers", {})
    providers["ollama"] = {
        "base_url": host,
        "default_model": tier.name,
    }

    agents = config.setdefault("agents", {})
    defaults = agents.setdefault("defaults", {})
    defaults["provider"] = "ollama"
    defaults["model"] = tier.name

    try:
        save_config(config)
    except OSError as exc:
        console.print(
            f"[yellow]Could not write config: {exc}[/yellow] "
            "Chat session will still start, but the choice won't persist."
        )


# ── Errors ────────────────────────────────────────────────────────────────────

def _print_download_error(exc: HFDownloadError) -> None:
    if exc.status == 404:
        console.print(
            f"[red]HuggingFace returned 404 for {exc.url}.[/red] "
            "Double-check the repo and filename, then retry."
        )
    elif exc.status in (401, 403):
        console.print(
            f"[red]HuggingFace returned {exc.status} for {exc.url}.[/red] "
            "Set [cyan]HF_TOKEN[/cyan] and retry."
        )
    elif "disk space" in str(exc).lower():
        console.print(f"[red]{exc}[/red]")
    else:
        console.print(f"[red]Download failed: {exc}[/red]")


# Module-level constant kept for callers that want to check the binding.
__all__ = ["main", "run_launch", "ALIAS_NAME"]
