"""Functional smoke test for EVERY registered slash command.

The builders only ran ``py_compile`` — no command was ever dispatched. This test
closes that gap by enumerating every command in the registry and driving each one
through the real ``dispatch()`` with the offline fixtures from conftest.py.

Core contract under test (the never-crash invariant):
    A command must NEVER crash the REPL. With empty args, a representative arg,
    or degraded/None refs, every handler must return a ``CommandResult`` and must
    not raise.

Two passes per command:
    1. Through the real ``dispatch()`` (the production path the channel uses).
       ``dispatch()`` has its own try/except safety net, so this proves the
       user-visible contract.
    2. Directly against ``cmd.handler(ctx, arg)`` (bypassing that net). This
       surfaces a handler that raises *internally* — which ``dispatch()`` would
       otherwise mask behind a generic "Command /x failed" message — so a latent
       bug fails the test instead of hiding in production.

All side effects are neutralised so the suite is hermetic:
    - ``load_config`` / ``save_config`` are patched (never touch ~/.trio).
    - The CLI runners a few natives call (hub/pairing/daemon/doctor) are patched
      to no-ops so nothing hits the network or spawns a process.
    - ``git`` shell-outs are patched to a canned result (deterministic, fast).
    - The working directory is a tmp_path (so /init and /export write there).
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT.

from __future__ import annotations

import copy

import pytest

from triobot.cli.slash import CommandResult, dispatch
from triobot.cli.slash.registry import CANONICAL, build_registry

from .conftest import make_ctx

# A representative, mostly-harmless argument per command. Chosen to exercise the
# "with an argument" branch of each handler without triggering a destructive or
# genuinely long-running path. Anything not listed here gets the default below.
_REPRESENTATIVE_ARG: dict[str, str] = {
    # Session & Context
    "context": "",
    "resume": "nonexistent-session",
    "save": "smoke-session",
    "load": "nonexistent-session",
    "export": "",  # empty → default tmp path; a name would also work
    "history": "5",
    # Model & Provider
    "provider": "ollama",
    "model": "llama3.1:8b",
    "models": "",
    "effort": "high",
    "fast": "on",
    "thinking": "on",
    # Agents, Tools, MCP & Skills
    "skill": "list",
    "tools": "",
    "agents": "nonexistent-agent",
    "mcp": "",
    "plugins": "",
    "fork": "do something",
    # Dev Workflow
    "plan": "off",
    "diff": "--stat",
    "commit": "",
    "memory": "a smoke-test fact",
    "search": "smoke",
    # System & Config
    "help": "model",
    "config": "agents.defaults.memory_window 40",
    "doctor": "",
    "permissions": "allow shell",
    "theme": "dark",
    "update": "",
    "login": "",
    "logout": "ollama",
    # triobot-native
    "tier": "llama3.1:8b",
    "channel": "cli",
    "hub": "python",
    "onboard": "",
    "serve": "",
    "gateway": "",
    "daemon": "status",
    "train": "",
    "pairing": "list",
    # System & exit — kept last conceptually; exit is fine to call.
    "exit": "",
}

_DEFAULT_ARG = "smoke"


@pytest.fixture(autouse=True)
def _neutralize_side_effects(monkeypatch, tmp_path):
    """Make every command hermetic: no real config writes, no network, no git.

    Patched at the *source* module so the handlers' lazy
    ``from triobot.core.config import load_config, save_config`` (and the CLI
    runner imports) pick up the fakes.
    """
    # --- config: never read or write the real ~/.trio/config.json -------------
    fake_config = {
        "agents": {"defaults": {"provider": "ollama", "model": "llama3.1:8b"}},
        "channels": {"cli": {"enabled": True}},
        "providers": {"ollama": {"api_key": "x"}},
        "tools": {"builtin": []},
    }

    def _load_config():
        return copy.deepcopy(fake_config)

    saved: list[dict] = []

    def _save_config(cfg):
        saved.append(cfg)  # capture, don't write to disk

    monkeypatch.setattr("triobot.core.config.load_config", _load_config)
    monkeypatch.setattr("triobot.core.config.save_config", _save_config)

    # --- CLI runners some natives call: no network, no subprocess, no output --
    async def _noop_async(*args, **kwargs):
        return None

    for target in (
        "triobot.cli.hub_cmd.run_hub",
        "triobot.cli.pairing_cmd.run_pairing",
        "triobot.cli.daemon_cmd.run_daemon",
        "triobot.cli.doctor_cmd.run_doctor",
    ):
        monkeypatch.setattr(target, _noop_async, raising=False)

    # --- git shell-out used by /diff and /commit: canned, deterministic -------
    async def _fake_run_git(*args):
        return True, "diff --git a/x b/x\n+smoke\n"

    monkeypatch.setattr(
        "triobot.cli.slash.commands.dev_workflow._run_git", _fake_run_git
    )

    # --- keep /init and /export writes inside tmp_path ------------------------
    monkeypatch.chdir(tmp_path)

    yield


def _all_commands():
    """Every canonical command, registry built once."""
    build_registry()
    # De-dup defensively (CANONICAL is one-per-command already, but be safe).
    seen: set[str] = set()
    out = []
    for cmd in CANONICAL:
        if cmd.name in seen:
            continue
        seen.add(cmd.name)
        out.append(cmd)
    return out


def _command_ids():
    return [c.name for c in _all_commands()]


def test_registry_has_expected_command_count():
    """Sanity: the registry is populated with a healthy number of commands."""
    cmds = _all_commands()
    # 6 modules, dozens of commands. Guard against an import regression that
    # silently drops a whole category.
    assert len(cmds) >= 30, f"only {len(cmds)} commands registered"


@pytest.mark.asyncio
@pytest.mark.parametrize("cmd", _all_commands(), ids=_command_ids())
async def test_command_dispatches_with_empty_arg(cmd, tmp_path):
    """Every command dispatches with an empty arg and returns a CommandResult."""
    ctx = make_ctx(tmp_path)
    res = await dispatch(f"/{cmd.name}", ctx)
    assert isinstance(res, CommandResult), f"/{cmd.name} did not return CommandResult"
    # dispatch()'s net converts a raise into a "failed" message. If we see that,
    # the handler raised internally on the empty-arg path — a contract violation.
    assert "failed:" not in res.message.lower(), (
        f"/{cmd.name} raised on empty arg (dispatch caught it): {res.message}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cmd", _all_commands(), ids=_command_ids())
async def test_command_dispatches_with_representative_arg(cmd, tmp_path):
    """Every command dispatches with a representative arg and returns a result."""
    ctx = make_ctx(tmp_path)
    arg = _REPRESENTATIVE_ARG.get(cmd.name, _DEFAULT_ARG)
    line = f"/{cmd.name} {arg}".strip()
    res = await dispatch(line, ctx)
    assert isinstance(res, CommandResult), f"{line} did not return CommandResult"
    assert "failed:" not in res.message.lower(), (
        f"{line} raised on representative arg (dispatch caught it): {res.message}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cmd", _all_commands(), ids=_command_ids())
async def test_handler_never_raises_directly(cmd, tmp_path):
    """Call each handler directly (no dispatch net) — it must not raise.

    This is the strict form of the never-crash contract: a handler must return a
    CommandResult itself, not rely on dispatch() to mop up an exception.
    """
    ctx = make_ctx(tmp_path)
    arg = _REPRESENTATIVE_ARG.get(cmd.name, _DEFAULT_ARG)
    try:
        res = await cmd.handler(ctx, arg)
    except Exception as exc:  # noqa: BLE001 — the whole point is to catch any raise
        pytest.fail(f"/{cmd.name} handler raised directly: {type(exc).__name__}: {exc}")
    assert isinstance(res, CommandResult), (
        f"/{cmd.name} handler returned {type(res).__name__}, not CommandResult"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cmd", _all_commands(), ids=_command_ids())
async def test_handler_survives_all_none_refs(cmd, tmp_path):
    """With every optional ref set to None, no handler may raise.

    Mirrors the degraded/legacy channel construction the CommandContext docstring
    promises to tolerate (provider/agent/mcp_manager/sessions/memory/tools/... may
    all be None).
    """
    ctx = make_ctx(
        tmp_path,
        provider=None,
        sessions=None,
        memory=None,
        tools=None,
        mcp_manager=None,
        agent=None,
        channel=None,
        bus=None,
    )
    arg = _REPRESENTATIVE_ARG.get(cmd.name, _DEFAULT_ARG)
    try:
        res = await cmd.handler(ctx, arg)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"/{cmd.name} handler raised with all-None refs: "
            f"{type(exc).__name__}: {exc}"
        )
    assert isinstance(res, CommandResult), (
        f"/{cmd.name} handler returned {type(res).__name__} with None refs"
    )
