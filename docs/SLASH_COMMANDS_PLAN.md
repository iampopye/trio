# triobot Interactive Slash-Command System — Implementation Plan

Status: Proposed
Branch: `rename/trio-to-triobot`
Owner: Architecture
Scope: `triobot/cli/slash/` registry + wiring in `triobot/cli/agent.py` and `triobot/channels/cli_channel.py`

---

## 0. Problem & Constraints

### The problem

The interactive REPL (`triobot/channels/cli_channel.py :: run_interactive`) dispatches slash
commands through a hardcoded `if/elif` chain in `_handle_slash_command`. That method only has
access to `self.bus`, `self.config`, `self._session_name`, `self._response_done`. It cannot reach
the agent loop, sessions, memory, tools, or MCP — so the current five commands (`/help`,
`/provider`, `/model`, `/skill`, `/clear`) are the ceiling of what is expressible. Every new command
would mean another `elif` and more merge contention on a single 240-line file.

### Constraints (verified against source)

1. `CLIChannel.__init__` currently receives only `bus` (and optional `config`). `run_agent()` at
   `triobot/cli/agent.py:105` calls `CLIChannel(bus=bus)`. Everything the commands need is already
   constructed in `run_agent()` (config, provider, bus, sessions, memory, tools, mcp_manager, agent)
   but is never handed to the channel.
2. The agent runs as a concurrent task (`asyncio.create_task(agent.run())`) reading the same bus.
   Slash commands run **in the REPL thread's event loop**, synchronously with input, and must NOT
   go through the bus (they are local, deterministic, and must not hit the LLM).
3. `AgentLoop` holds per-user mutable state (`_user_modes`, `_user_models`, `_deep_thinking`) keyed
   by `session_key`. The CLI session key is `"cli:cli_user"` (`InboundMessage.session_key` =
   `f"{channel}:{chat_id}"`, and the CLI publishes `channel="cli"`, `chat_id="cli_user"`).
   Commands that change mode/model must mutate the SAME dicts the agent reads, so they must operate
   on the live `agent` instance, not a copy.
4. `save_config()` persists to `~/.trio/config.json`, but the running provider/agent were built at
   startup. Config-mutating commands can persist immediately but generally require a note that some
   changes take effect on next launch (matches current `/provider`, `/model` behavior).
5. Immutability rule (coding-style): command handlers return NEW result objects; they never mutate
   shared config dicts in place except through the sanctioned `save_config()` path and the agent's
   own per-user state setters.

### Design goals

- One command = one module (or one small category module) → parallel implementation, zero merge
  conflicts on the dispatcher.
- Auto-generated `/help`, grouped by category, driven by registry metadata.
- Feasibility-tagged phases (P1→P4) so multiple engineering agents can build in parallel.
- Registry + dispatch unit-testable with NO live provider and NO network.

---

## 1. Registry Architecture

### 1.1 Module layout

```
triobot/cli/slash/
├── __init__.py            # public surface: dispatch(), build_registry(), CommandContext, command
├── model.py               # SlashCommand dataclass, Category enum, CommandResult
├── context.py             # CommandContext dataclass (the 8 refs)
├── registry.py            # @command decorator, REGISTRY, build_registry(), resolve()
├── dispatch.py            # dispatch(line, ctx) -> CommandResult; parse !shell / @file
├── help.py                # render_help(registry, category=None) -> str
├── special.py             # handle_shell(cmd, ctx), expand_at_file(text, ctx)
├── errors.py              # SlashError, UnknownCommand, BadUsage
└── commands/
    ├── __init__.py        # imports every command module so decorators register (import side effect)
    ├── session_context.py # /clear /new /reset /compact /context /resume /save /load /export
    │                      #   /rename /history /fork /rewind /undo /redo  (Category.SESSION)
    ├── model_provider.py  # /model /models /provider /login /logout /effort /thinking /fast
    │                      #   (Category.MODEL)
    ├── agents_tools.py    # /agents /tools /mcp /skill /skills /permissions /approvals /sandbox
    │                      #   (Category.AGENTS)
    ├── dev_workflow.py    # /init /diff /review /commit /plan /run  (Category.DEV)
    ├── system_config.py   # /help /config /status /cost /doctor /update /theme /vim /log /shell
    │                      #   (Category.SYSTEM)
    └── triobot_native.py  # /channels /gateway /serve /onboard /pairing /train /hub /tier /daemon
    │                      #   /heartbeat  (Category.NATIVE)
```

Rationale for grouping by category module rather than one-file-per-command: ~50 commands as 50 files
is churn without benefit, and many commands in a category share a helper (e.g. all model commands
touch the same config path). Six category modules keep each file well under the 800-line ceiling
(estimated 120–250 lines each) while letting six agents each own one file with no overlap. The
dispatcher, model, context, and help modules are stable infrastructure written ONCE in P1 and rarely
touched afterward.

### 1.2 The `SlashCommand` model  (`slash/model.py`)

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable


class Category(str, Enum):
    SESSION = "Session & Context"
    MODEL   = "Model & Provider"
    AGENTS  = "Agents, Tools, MCP & Skills"
    DEV     = "Dev Workflow"
    SYSTEM  = "System & Config"
    NATIVE  = "triobot-native"


@dataclass(frozen=True)
class CommandResult:
    """Immutable result of a command. `message` is printed by the channel.
    `handled=True` stops the line from being sent to the LLM.
    `exit_repl=True` requests the REPL to quit.
    `send_to_llm` optionally carries text to publish to the bus (e.g. expanded @file prompt)."""
    message: str = ""
    handled: bool = True
    exit_repl: bool = False
    send_to_llm: str | None = None


# Handler signature: async (ctx, arg) -> CommandResult
Handler = Callable[["CommandContext", str], Awaitable[CommandResult]]


@dataclass(frozen=True)
class SlashCommand:
    name: str                       # canonical, no leading slash, e.g. "model"
    handler: Handler
    category: Category
    summary: str                    # one line for /help
    usage: str = ""                 # e.g. "/model <name>"
    aliases: tuple[str, ...] = ()   # e.g. ("new", "reset") for /clear
    phase: str = "P1"               # P1 | P2 | P3 | P4 — informational / gating
```

`frozen=True` on the dataclasses enforces the immutability rule: commands are values, results are
values.

### 1.3 The `CommandContext`  (`slash/context.py`)

This is the ONLY object every handler receives. It carries EXACTLY the eight refs `run_agent()`
already builds, plus a `console` for rich output and the fixed CLI session key.

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rich.console import Console
    from triobot.core.bus import MessageBus
    from triobot.core.session import SessionManager
    from triobot.core.memory import MemoryStore
    from triobot.core.loop import AgentLoop
    from triobot.tools.base import ToolRegistry
    from triobot.providers.base import BaseProvider
    from triobot.tools.mcp_client import MCPManager
    from triobot.channels.cli_channel import CLIChannel


@dataclass
class CommandContext:
    channel:     "CLIChannel"           # for screen clear, session-name label, publish_inbound
    config:      dict[str, Any]         # live config dict (load_config() result)
    provider:    "BaseProvider"         # running provider (list_models, supports_tools, ...)
    bus:         "MessageBus"           # to publish inbound (e.g. @file-expanded prompts)
    sessions:    "SessionManager"       # get/save/list/rename/delete
    memory:      "MemoryStore"          # read_memory/read_history/search_history/save_memory_fact
    tools:       "ToolRegistry"         # list_tools/get_schemas/execute
    mcp_manager: "MCPManager | None"    # None when no MCP servers configured
    agent:       "AgentLoop"            # per-user modes/models/deepthink, session helpers
    console:     "Console"              # rich console for formatted output

    # Canonical CLI identity (matches InboundMessage.session_key contract)
    channel_name: str = "cli"
    chat_id:      str = "cli_user"

    @property
    def session_key(self) -> str:
        return f"{self.channel_name}:{self.chat_id}"
```

Every ref here is a reference to the SAME live object the agent task uses. `/model` mutating
`ctx.agent._user_models[ctx.session_key]` is immediately visible to the next agent turn.

### 1.4 The `@command` decorator + registry  (`slash/registry.py`)

```python
from __future__ import annotations
from .model import SlashCommand, Category, Handler

# name/alias -> SlashCommand  (aliases point at the same object)
REGISTRY: dict[str, SlashCommand] = {}
# ordered canonical list for /help
CANONICAL: list[SlashCommand] = []


def command(name, *, category, summary, usage="", aliases=(), phase="P1"):
    """Decorator that registers a handler as a SlashCommand.
       Raises at import time on duplicate name/alias — fail fast, catch merge collisions."""
    def wrap(fn: Handler) -> Handler:
        cmd = SlashCommand(name=name, handler=fn, category=category,
                           summary=summary, usage=usage or f"/{name}",
                           aliases=tuple(aliases), phase=phase)
        for key in (name, *aliases):
            if key in REGISTRY:
                raise ValueError(f"Duplicate slash command/alias: /{key}")
            REGISTRY[key] = cmd
        CANONICAL.append(cmd)
        return fn
    return wrap


def build_registry() -> dict[str, SlashCommand]:
    """Import all command modules so their decorators run, then return REGISTRY.
       Import is idempotent; safe to call once per REPL start."""
    from . import commands  # noqa: F401  (commands/__init__ imports every category module)
    return REGISTRY


def resolve(verb: str) -> SlashCommand | None:
    return REGISTRY.get(verb.lower())
```

`commands/__init__.py` simply does `from . import (session_context, model_provider, agents_tools,
dev_workflow, system_config, triobot_native)`. Adding a command in P2/P3/P4 = adding a decorated
function inside an already-imported category module; no wiring change anywhere.

### 1.5 Dispatch  (`slash/dispatch.py`)

The single entry point the channel calls. Handles slash verbs, `!shell`, and `@file` expansion.

```python
from __future__ import annotations
from .registry import resolve
from .model import CommandResult
from .special import handle_shell, expand_at_file


async def dispatch(line: str, ctx) -> CommandResult:
    stripped = line.strip()

    # 1. !shell escape (highest precedence, OpenCode-style)
    if stripped.startswith("!"):
        return await handle_shell(stripped[1:].strip(), ctx)

    # 2. Slash command
    if stripped.startswith("/"):
        parts = stripped[1:].split(maxsplit=1)
        if not parts:
            return CommandResult(handled=False)          # bare "/" → treat as normal input
        verb, arg = parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")
        cmd = resolve(verb)
        if cmd is None:
            # Unknown slash → not handled; channel falls through to the LLM (preserves today's behavior)
            return CommandResult(handled=False)
        try:
            return await cmd.handler(ctx, arg)
        except Exception as e:                            # never crash the REPL on a bad command
            return CommandResult(message=f"[red]Command /{verb} failed:[/red] {e}")

    # 3. @file expansion inside otherwise-normal input → produce prompt for the LLM
    if "@" in stripped:
        expanded = await expand_at_file(stripped, ctx)
        if expanded is not None and expanded != stripped:
            return CommandResult(handled=False, send_to_llm=expanded)

    return CommandResult(handled=False)                   # normal chat input
```

Note: `handled=False` means "channel should send this to the LLM". `send_to_llm` lets `@file` rewrite
the outgoing text while still routing through the normal LLM path.

### 1.6 Auto-generated `/help`  (`slash/help.py`)

```python
from .registry import CANONICAL
from .model import Category


def render_help(category: str | None = None) -> str:
    lines = ["", "[bold]triobot slash commands[/bold]", ""]
    for cat in Category:                              # stable enum order
        cmds = [c for c in CANONICAL if c.category is cat]
        if category and category.lower() not in cat.value.lower():
            continue
        if not cmds:
            continue
        lines.append(f"[bold cyan]{cat.value}[/bold cyan]")
        for c in sorted(cmds, key=lambda x: x.name):
            alias = f"  ([dim]{', '.join('/' + a for a in c.aliases)}[/dim])" if c.aliases else ""
            lines.append(f"  [green]{c.usage:<26}[/green] {c.summary}{alias}")
        lines.append("")
    lines.append("[dim]!<cmd> runs a shell command · @path/to/file inlines a file · run `trio help` for CLI reference[/dim]")
    return "\n".join(lines)
```

`/help <topic>` filters by category name substring. `/help model` shows just the Model & Provider
group. The help table is 100% derived from registry metadata — a new command appears automatically.

---

## 2. Wiring Changes (precise edits)

### 2.1 `triobot/cli/agent.py`

**Edit 1 — pass the 8 refs into CLIChannel.** Replace line 105:

```python
# BEFORE
cli = CLIChannel(bus=bus)

# AFTER
cli = CLIChannel(
    bus=bus,
    config=config,
    provider=provider,
    sessions=sessions,
    memory=memory,
    tools=tools,
    mcp_manager=mcp_manager,
    agent=agent,
    console=console,
)
```

All of `config`, `provider`, `sessions`, `memory`, `tools`, `mcp_manager`, `agent` already exist in
scope (lines 35, 61, 69–83, 85). `console` is the module-level `Console()` at line 21. No other change
to `agent.py`. `mcp_manager` may be `None` (line 76) — that is expected and handled by
`CommandContext`.

### 2.2 `triobot/channels/cli_channel.py`

**Edit 1 — widen `__init__` to accept and store the refs, and lazily build the context.**

```python
def __init__(self, bus, config=None, *, provider=None, sessions=None, memory=None,
             tools=None, mcp_manager=None, agent=None, console=None):
    super().__init__(name="cli", bus=bus, config=config or {})
    self._running = True
    self._streaming = False
    self._streamed_content = False
    self._session_name = None
    self._response_done = asyncio.Event()
    # slash-command dependencies (may be None in legacy/test construction)
    self._provider = provider
    self._sessions = sessions
    self._memory = memory
    self._tools = tools
    self._mcp_manager = mcp_manager
    self._agent = agent
    self._console = console
    self._ctx = None            # built lazily on first command
    self._registry_ready = False
```

Keeping the new params keyword-only with `None` defaults means existing construction
(`CLIChannel(bus=bus)`) and any tests keep working — the channel degrades gracefully to "no rich
commands" if wired without deps.

**Edit 2 — build the `CommandContext` once, on demand.**

```python
def _get_context(self):
    if self._ctx is None:
        from triobot.cli.slash import CommandContext
        from triobot.cli.slash.registry import build_registry
        if not self._registry_ready:
            build_registry()
            self._registry_ready = True
        from rich.console import Console
        self._ctx = CommandContext(
            channel=self, config=self.config, provider=self._provider, bus=self.bus,
            sessions=self._sessions, memory=self._memory, tools=self._tools,
            mcp_manager=self._mcp_manager, agent=self._agent,
            console=self._console or Console(),
        )
    return self._ctx
```

**Edit 3 — replace the entire `if/elif` body of `_handle_slash_command` with a dispatcher call.**
Delete `_handle_slash_command`, `_show_slash_help`, `_slash_provider`, `_slash_model`, `_slash_skill`
(lines 117–226) and their inline logic; that behavior now lives in the registry command modules.

```python
async def _handle_slash_command(self, cmd: str) -> bool:
    """Route a slash/! line through the registry. Returns True if handled locally."""
    from triobot.cli.slash import dispatch
    result = await dispatch(cmd, self._get_context())

    if result.message:
        (self._console or __import__("rich").get_console()).print(result.message)
    if result.exit_repl:
        self._running = False
        return True
    if result.send_to_llm is not None:
        # @file expansion etc. — route the rewritten text to the LLM
        await self._route_to_llm(result.send_to_llm)
        return True
    return result.handled
```

**Edit 4 — route `!shell` / `@file` through the same entry, and factor the LLM send path.**
`run_interactive` currently special-cases only `startswith("/")` (line 89). Change the guard so that
`/`, `!`, and lines containing `@` all pass through `_handle_slash_command`, and extract the
"publish + wait" block (lines 94–110) into `_route_to_llm(text)` so `send_to_llm` can reuse it:

```python
# in run_interactive, replace the slash guard:
if stripped.startswith("/") or stripped.startswith("!") or "@" in stripped:
    handled = await self._handle_slash_command(stripped)
    if handled:
        continue
# ... normal path calls self._route_to_llm(stripped)
```

```python
async def _route_to_llm(self, text: str) -> None:
    self._response_done.clear()
    await self.publish_inbound(chat_id="cli_user", user_id="cli_user", content=text)
    try:
        await asyncio.wait_for(self._response_done.wait(), timeout=300)
    except asyncio.TimeoutError:
        print("\n[timeout — no response after 5 minutes]\n")
    print()
```

Exit words (`exit`, `quit`, `/exit`, `/quit`, `:q`) stay handled at the top of `run_interactive`
(lines 69, 79) — but `/exit` and `/quit` are ALSO registered as no-op commands returning
`exit_repl=True`, so `/help` lists them. The literal `exit`/`quit`/`:q` remain a channel-level
convenience.

---

## 3. Full Command Table

Feasibility tags:
`P1 now` = buildable with only config + provider + channel refs (no session/memory).
`P2 session-memory` = needs `sessions` / `memory`.
`P3 agents-mcp-tools` = needs `agent`, `tools`, or `mcp_manager` live state.
`P4 needs-new-infra` = requires code that does not yet exist (git integration, checkpoints, cost
tracking, theme system, editor launch, undo stacks). Ships as a clear "not yet available" stub in the
same phase so `/help` is honest, then upgraded when infra lands.

### 3.1 Session & Context  (`commands/session_context.py`, Category.SESSION)

| Command | Aliases | Behavior | Drives (API / subcommand) | Tag |
|---|---|---|---|---|
| `/clear` | `cls` | ANSI-clear the terminal, keep session | channel prints `\033[2J\033[H` | P1 now |
| `/new` | — | Start a fresh named session, switch to it | `sessions.get(new_key)` + `rename_session` + set channel session name; mirror `AgentLoop._handle_session_command("new")` | P2 session-memory |
| `/reset` | — | Clear current conversation history | `sessions.delete(ctx.session_key)`; clear `agent._user_modes/_user_models` for key | P2 session-memory |
| `/context` | `ctx` | Show token/size estimate: message count, memory-window, model | `sessions.get().message_count`, `memory.read_memory()` length, `agent.memory_window` | P2 session-memory |
| `/compact` | — | Consolidate old messages into MEMORY.md now | `memory.consolidate(old, provider)` on `session.history[:-window]`, then trim + `save_session` | P2 session-memory |
| `/history` | `hist` `log` | Show last N interactions | `memory.read_history(n)`; `arg` = N (default 30) | P2 session-memory |
| `/search` | `grep` | Search HISTORY.md | `memory.search_history(arg)` | P2 session-memory |
| `/resume` | — | List named sessions and switch by name | `sessions.get_named_sessions()`; switch via channel session name + reuse key | P2 session-memory |
| `/save` | — | Snapshot current session under a name | `sessions.rename_session(key, arg)` + `save_session` | P2 session-memory |
| `/load` | — | Load a named session into the CLI view | `sessions.get(key)`, set channel session name | P2 session-memory |
| `/rename` | — | Rename current session | `sessions.rename_session(ctx.session_key, arg)` | P2 session-memory |
| `/export` | — | Write current session to a Markdown file | read `sessions.get().history`, write `~/.trio/exports/<name>.md` | P2 session-memory |
| `/remember` | `memorize` | Save a fact to long-term MEMORY.md | `memory.save_memory_fact(arg)` | P2 session-memory |
| `/fork` | — | Copy current session to a new key | read history, `save_message` loop into new key | P2 session-memory |
| `/rewind` | `checkpoint` | Drop the last N turns from the session | rewrite `session.history[:-2n]` via `save_session` | P4 needs-new-infra (no checkpoint store; ships as history-trim) |
| `/undo` | — | Revert last turn (user+assistant) | trim 2 messages, `save_session` | P4 needs-new-infra |
| `/redo` | — | Reapply last undone turn | requires undo stack | P4 needs-new-infra (stub) |

### 3.2 Model & Provider  (`commands/model_provider.py`, Category.MODEL)

| Command | Aliases | Behavior | Drives | Tag |
|---|---|---|---|---|
| `/model` | `setmodel` | Show or set model; persists + updates live agent | no-arg: show `agent._user_models.get(key, default)`; arg: set `agent._user_models[key]=arg` + `save_config` | P1 now |
| `/models` | — | List models from the live provider | `await provider.list_models()` | P1 now (P3 if provider needs network) |
| `/provider` | `providers` | Show or switch provider (persist; note restart) | read/write `config["agents"]["defaults"]["provider"]` + `save_config` | P1 now |
| `/login` | — | OAuth/login for a provider | wraps `triobot.cli.provider_cmd.run_provider("login")` | P3 agents-mcp-tools |
| `/logout` | — | Clear stored provider credential | delete key from `config["providers"][name]`, `save_config` | P1 now |
| `/effort` | — | Set reasoning effort (low/med/high) | set `config["agents"]["defaults"]["effort"]`; mode hint to agent | P4 needs-new-infra (no effort plumbing; stores pref) |
| `/thinking` | `deepthink` | Toggle visible reasoning stream | flip `agent._deep_thinking[key]` (already read at loop.py:221) | P1 now |
| `/fast` | — | Toggle fast mode | set `config["agents"]["defaults"]["fast"]` via same path as `/model` | P1 now |
| `/mode` | `chat` `coder` `think` | Switch general/coding/reasoning mode | set `agent._user_modes[key]` (read at loop.py:176) | P1 now |

### 3.3 Agents, Tools, MCP & Skills  (`commands/agents_tools.py`, Category.AGENTS)

| Command | Aliases | Behavior | Drives | Tag |
|---|---|---|---|---|
| `/tools` | — | List registered tools + schemas summary | `tools.list_tools()`, `tools.get_schemas()` | P3 agents-mcp-tools |
| `/tool` | — | Run a tool ad-hoc: `/tool <name> {json}` | `await tools.execute(name, params)` | P3 agents-mcp-tools |
| `/agents` | `subagents` | List sub-agents | `agent.subagent_registry.list_agents()` | P3 agents-mcp-tools |
| `/mcp` | — | Show MCP servers + their tools | `mcp_manager._servers` keys; filter `tools.list_tools()` by `name_` prefix | P3 agents-mcp-tools |
| `/skill` | `skills` | List/install skills | no-arg/`list`: `get_skills_dir().glob("*.md")`; `install <n>`: wrap `run_skill` | P1 now |
| `/permissions` | `perms` | Show/set approval policy | read/write `config` approval settings; `agent.approval_manager` | P3 agents-mcp-tools |
| `/approvals` | — | Toggle approval mode (auto/ask/deny) | set `config["approvals"]["mode"]`, `save_config` | P3 agents-mcp-tools |
| `/sandbox` | — | Toggle workspace-restricted tool mode | flip `config["tools"]["restrictToWorkspace"]`, note restart | P1 now |

### 3.4 Dev Workflow  (`commands/dev_workflow.py`, Category.DEV)

| Command | Aliases | Behavior | Drives | Tag |
|---|---|---|---|---|
| `/init` | — | Scaffold project context: create/append `AGENTS.md`/`SOUL.md` in workspace | `get_workspace_dir()` write | P1 now |
| `/diff` | — | Show `git diff` for the active repo | shell out via `tools.execute("shell", {"command":"git diff"})` or subprocess | P3 agents-mcp-tools |
| `/review` | — | Ask the agent to review current diff | build prompt from `git diff`, route to LLM (`send_to_llm`) | P3 agents-mcp-tools |
| `/commit` | — | Draft a commit message from the diff | git diff → LLM prompt → `send_to_llm` | P4 needs-new-infra (no git wrapper yet; ships via shell tool) |
| `/plan` | — | Enter plan mode (agent proposes before acting) | set `agent._user_modes[key]="reasoning"` + planning system hint | P1 now |
| `/run` | — | Run a project command (build/test) | `tools.execute("shell", {...})` | P3 agents-mcp-tools |

### 3.5 System & Config  (`commands/system_config.py`, Category.SYSTEM)

| Command | Aliases | Behavior | Drives | Tag |
|---|---|---|---|---|
| `/help` | `?` `commands` | Auto-generated grouped help | `help.render_help(arg)` | P1 now |
| `/config` | `settings` | Show config or set `key=value` | `load_config()` / dotted-path set + `save_config` | P1 now |
| `/status` | — | System status (provider, model, tools, mcp) | wraps `triobot.cli.status.run_status` or inline summary from ctx | P1 now |
| `/doctor` | — | Diagnose environment | wraps `triobot.cli.doctor_cmd.run_doctor(fix=False)` | P1 now |
| `/update` | — | Update triobot | wraps `triobot.cli.update_cmd.run_update` | P1 now |
| `/cost` | `usage` | Show token/cost for the session | sum `usage` from provider responses (needs accounting) | P4 needs-new-infra (stub: shows "not tracked yet") |
| `/theme` | `themes` | Switch console theme | persist `config["ui"]["theme"]`; apply to rich Console | P4 needs-new-infra (no theme system; stores pref) |
| `/vim` | — | Toggle vim input keybindings | persist pref; input layer does not support it yet | P4 needs-new-infra (stub) |
| `/log` | `logs` | Toggle runtime log verbosity | `logging.getLogger().setLevel(...)` | P1 now |
| `/shell` | `sh` `bang` | Run a shell command (explicit form of `!`) | `special.handle_shell(arg, ctx)` | P1 now |
| `/exit` | `quit` `q` | Exit the REPL | `CommandResult(exit_repl=True)` | P1 now |

### 3.6 triobot-native  (`commands/triobot_native.py`, Category.NATIVE)

These thinly wrap existing `trio <x>` subcommand runners (all `async def run_*`) so behavior stays
single-sourced.

| Command | Aliases | Behavior | Drives (subcommand runner) | Tag |
|---|---|---|---|---|
| `/channels` | — | List channels + enabled state | read `config["channels"]` | P1 now |
| `/gateway` | — | Report/launch enabled channels | wraps `triobot.cli.gateway.run_gateway` (report-only in REPL) | P1 now |
| `/serve` | — | Print how to open the web UI | describes `trio serve` (do not block REPL) | P1 now |
| `/onboard` | — | Re-run provider onboarding | wraps `triobot.cli.onboard.run_onboard` | P1 now |
| `/pairing` | — | Show DM pairing status | wraps `triobot.cli.pairing_cmd.run_pairing` (list) | P1 now |
| `/train` | — | Show training status / how to train | describes `trio train` | P1 now |
| `/hub` | — | Search/trending TrioHub | wraps `triobot.cli.hub_cmd.run_hub` | P1 now |
| `/tier` | `tiers` | Show/set the active model (provider-defined) | thin alias of `/model`; switch via `/model` path | P1 now |
| `/daemon` | — | Show gateway daemon status | wraps `triobot.cli.daemon_cmd.run_daemon("status")` | P1 now |
| `/heartbeat` | — | Show heartbeat status | wraps `triobot.cli.heartbeat_cmd.run_heartbeat("status")` | P1 now |
| `/repo` | `repos` | List/switch project workspaces | wraps `triobot.cli.repo_cmd.run_repo` | P1 now |

**Total: 53 commands** (17 Session, 9 Model, 8 Agents, 6 Dev, 11 System, 12 Native — several share a
category module). Well within the 45–55 target.

Wrapping note: subcommand runners that expect an argparse `args` namespace (e.g. `run_plugin`,
`run_skill`, `run_hub`, `run_pairing`, `run_repo`) must be called with a small shim namespace
(`types.SimpleNamespace(...)`) built by the native command from `arg`. Runners that take plain
strings (`run_provider(action)`, `run_heartbeat(action)`, `run_daemon(action)`, `run_doctor(fix=)`,
`run_update(channel=)`) are called directly. This keeps the CLI and REPL behavior identical.

---

## 4. `!shell` and `@file` Special-Syntax Design  (`slash/special.py`)

### 4.1 `!shell`

Triggered when a line starts with `!` (dispatch step 1) or via `/shell <cmd>`.

```python
async def handle_shell(cmd: str, ctx) -> CommandResult:
    if not cmd:
        return CommandResult(message="[yellow]Usage:[/yellow] !<command>  e.g. !git status")
    # Prefer the registered, policy-guarded shell tool if present
    if "shell" in ctx.tools.list_tools():
        res = await ctx.tools.execute("shell", {"command": cmd})
        body = res.output if res.success else f"[red]{res.output}[/red]"
        return CommandResult(message=f"[dim]$ {cmd}[/dim]\n{body}")
    # Fallback: direct subprocess (no shell=True; split safely)
    import shlex, asyncio
    try:
        proc = await asyncio.create_subprocess_exec(
            *shlex.split(cmd),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await proc.communicate()
        return CommandResult(message=f"[dim]$ {cmd}[/dim]\n{out.decode(errors='replace')}")
    except FileNotFoundError:
        return CommandResult(message=f"[red]Command not found:[/red] {cmd.split()[0]}")
```

Security posture (per security.md): route through the existing `ShellTool` when enabled so the
`restrictToWorkspace` guard and future approval policy apply; the direct fallback uses
`create_subprocess_exec` with `shlex.split` (NO `shell=True`, no string interpolation into a shell)
to avoid shell-injection. `!` is a local escape — it never reaches the LLM.

### 4.2 `@file`

Triggered when a normal (non-`/`, non-`!`) line contains one or more `@path` tokens. Each `@path`
is replaced with a fenced block of that file's content, and the rewritten text is sent to the LLM
via `CommandResult(handled=False, send_to_llm=expanded)`.

```python
import re, pathlib
AT_TOKEN = re.compile(r"@([^\s]+)")
MAX_FILE_BYTES = 100_000

async def expand_at_file(text: str, ctx) -> str | None:
    from triobot.core.config import get_workspace_dir
    matches = list(AT_TOKEN.finditer(text))
    if not matches:
        return None
    workspace = get_workspace_dir()
    blocks, out = [], text
    for m in matches:
        raw = m.group(1)
        # resolve relative to workspace, then cwd; block traversal outside both roots
        candidates = [workspace / raw, pathlib.Path.cwd() / raw, pathlib.Path(raw)]
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            continue
        rp = path.resolve()
        if not (str(rp).startswith(str(workspace.resolve())) or str(rp).startswith(str(pathlib.Path.cwd().resolve()))):
            continue                                   # path traversal guard
        data = rp.read_bytes()[:MAX_FILE_BYTES]
        blocks.append(f"\n\n--- {raw} ---\n```\n{data.decode(errors='replace')}\n```")
        out = out.replace(m.group(0), raw)             # keep filename inline, append content below
    if not blocks:
        return None
    return out + "".join(blocks)
```

Design points:
- `@file` produces a normal LLM turn (matches OpenCode: attach file context to the prompt), so it
  returns `handled=False, send_to_llm=...` rather than printing.
- Path traversal is blocked (input-validation rule): resolved path must live under the workspace or
  cwd; size is capped at 100 KB.
- Binary/unreadable bytes are decoded with `errors="replace"` so a stray binary reference never
  crashes the REPL.
- A `@` that resolves to no file is left untouched (could be an email address, decorator, etc.).

---

## 5. Phased Build Sequence (parallelizable)

### Phase 0 — Infrastructure (SERIAL, one agent, ~half day) — BLOCKS everything

Build the stable spine so all later work is pure additive command functions:

1. `slash/model.py` (Category, CommandResult, SlashCommand)
2. `slash/context.py` (CommandContext)
3. `slash/registry.py` (`@command`, REGISTRY, build_registry, resolve)
4. `slash/errors.py`
5. `slash/dispatch.py`
6. `slash/help.py`
7. `slash/special.py` (handle_shell + expand_at_file)
8. `slash/__init__.py` (re-exports: `dispatch`, `command`, `CommandContext`, `render_help`)
9. `slash/commands/__init__.py` (imports the six category modules — create empty category modules
   first so imports resolve)
10. **Wiring** in `agent.py` (Edit 1) and `cli_channel.py` (Edits 1–4).

Exit criteria: `/help` renders (empty categories OK), `!echo hi` works, `@somefile` inlines,
unknown `/foo` still falls through to the LLM. Tests in §6 for registry + dispatch pass.

### Phase 1 — "P1 now" commands (PARALLEL across 6 agents, one per category module)

Each agent owns exactly ONE file in `commands/` → zero merge conflicts. All P1-tagged rows above:

- Agent A → `system_config.py`: `/help /config /status /doctor /update /log /shell /exit`
- Agent B → `model_provider.py`: `/model /models /provider /logout /thinking /fast /mode`
- Agent C → `triobot_native.py`: all native wrappers (`/channels /gateway /serve /onboard /pairing
  /train /hub /tier /daemon /heartbeat /repo`)
- Agent D → `agents_tools.py`: `/skill /sandbox` (P1 subset)
- Agent E → `dev_workflow.py`: `/init /plan` (P1 subset)
- Agent F → `session_context.py`: `/clear` (P1 subset)

These need only P1 refs (config, provider, channel) that Phase 0 wired. Independent; ship in any order.

### Phase 2 — "P2 session-memory" commands (PARALLEL, mostly one agent on session_context.py)

Depends on Phase 0 only. Fill out `session_context.py`: `/new /reset /context /compact /history
/search /resume /save /load /rename /export /remember /fork`. One agent owns the file; can be split
into two agents by editing disjoint function sets if throughput matters (session-ops vs memory-ops),
but same-file coordination is then required — prefer single owner.

`/models` upgrade (if provider is network-backed) also lands here for Agent B.

### Phase 3 — "P3 agents-mcp-tools" commands (PARALLEL across 3 files)

Depends on Phase 0. Independent files → 3 agents:
- `agents_tools.py`: `/tools /tool /agents /mcp /permissions /approvals`
- `dev_workflow.py`: `/diff /review /run`
- `model_provider.py`: `/login`

### Phase 4 — "P4 needs-new-infra" commands (SERIAL where infra is shared)

Each ships first as an honest stub (`CommandResult(message="… not available yet")`) so `/help` never
lies, then is upgraded when the backing infra lands:
- Git wrapper → `/commit`, upgrade `/diff /review`
- Checkpoint/undo store → `/rewind /undo /redo`
- Cost accounting (aggregate `LLMResponse.usage`) → `/cost`
- Theme system → `/theme`
- Effort plumbing → `/effort`
- Editor/vim input layer → `/vim`, `/editor`

Stubs can be authored during Phase 1 (they only need the registry) so `/help` is complete early;
upgrades are scheduled independently.

### Dependency summary

```
Phase 0 (serial) ──► Phase 1 (6 parallel)
                └──► Phase 2 (parallel, session_context owner)
                └──► Phase 3 (3 parallel)
                └──► Phase 4 stubs (parallel) ─► Phase 4 upgrades (serial per infra)
```

The ONLY hard dependency is Phase 0. Every command function is additive: it imports `command` +
`CommandResult` + `Category`, decorates a handler, and touches only refs already present on
`CommandContext`. No two command agents edit the same file within a phase.

---

## 6. Test Approach (no live provider, no network)

All tests live under `tests/cli/slash/` and rely on fakes — the registry and dispatch are pure and
fully testable in isolation.

### 6.1 Fakes / fixtures

```python
# tests/cli/slash/conftest.py
class FakeProvider:
    async def list_models(self): return ["llama3.2:3b", "llama3.1:8b"]
    def supports_tools(self): return False
    def supports_vision(self): return False

class FakeChannel:
    def __init__(self): self.cleared = False; self._session_name = None
    def set_session_name(self, n): self._session_name = n

def make_ctx(tmp_path, **over):
    from triobot.cli.slash import CommandContext
    from triobot.core.session import SessionManager
    from triobot.core.memory import MemoryStore
    from triobot.tools.base import ToolRegistry
    from rich.console import Console
    base = dict(
        channel=FakeChannel(), config={"agents": {"defaults": {"provider": "ollama", "model": "llama3.1:8b"}}},
        provider=FakeProvider(), bus=None,
        sessions=SessionManager(data_dir=tmp_path / "s"),
        memory=MemoryStore(memory_dir=tmp_path / "m"),
        tools=ToolRegistry(), mcp_manager=None, agent=FakeAgent(), console=Console(),
    )
    base.update(over)
    return CommandContext(**base)
```

`SessionManager` and `MemoryStore` accept an injected dir (`data_dir` / `memory_dir`), so tests use
`tmp_path` and never touch `~/.trio`. `FakeAgent` exposes the three per-user dicts
(`_user_modes`, `_user_models`, `_deep_thinking`), `memory_window`, `default_model`, and a stub
`subagent_registry.list_agents()`.

### 6.2 Registry tests (`test_registry.py`)

- `build_registry()` populates REGISTRY; every canonical name resolves.
- Duplicate name/alias raises `ValueError` at decoration time (register two handlers with same name
  in a throwaway module → assert raises). Guards against merge collisions.
- Every `SlashCommand` has non-empty `summary` and a `usage` starting with `/`.
- Every command's `category` is a valid `Category` member and `phase` in `{P1,P2,P3,P4}`.

### 6.3 Dispatch tests (`test_dispatch.py`)  — AAA style

```python
async def test_unknown_slash_falls_through_to_llm():
    ctx = make_ctx(tmp_path)
    res = await dispatch("/nope", ctx)
    assert res.handled is False           # channel will send to LLM

async def test_help_is_handled_and_lists_categories():
    ctx = make_ctx(tmp_path)
    res = await dispatch("/help", ctx)
    assert res.handled and "Session & Context" in res.message

async def test_bang_runs_shell_without_llm():
    ctx = make_ctx(tmp_path)
    res = await dispatch("!echo hi", ctx)     # tools empty → subprocess fallback
    assert "hi" in res.message and res.handled

async def test_at_file_expands_and_routes_to_llm(tmp_path):
    (tmp_path / "note.txt").write_text("SECRET-CONTENT")
    ctx = make_ctx(tmp_path)
    res = await dispatch("summarize @note.txt", monkeypatched_workspace_ctx)
    assert res.handled is False and "SECRET-CONTENT" in res.send_to_llm

async def test_at_file_blocks_path_traversal(tmp_path):
    res = await dispatch("read @../../etc/passwd", ctx)
    assert res.send_to_llm is None         # traversal rejected, treated as normal input

async def test_handler_exception_does_not_crash(monkeypatch):
    # register a bomb command, dispatch it, assert graceful CommandResult with error message
```

### 6.4 Per-command tests

Each command module gets a focused test asserting the observable effect on the fakes:
- `/model llama3.1:8b` → `ctx.agent._user_models[ctx.session_key] == "llama3.1:8b"` and `save_config`
  called (patch `triobot.core.config.save_config`).
- `/thinking` → toggles `ctx.agent._deep_thinking[key]`.
- `/remember foo` → `MEMORY.md` (in tmp) contains `foo`.
- `/reset` → session file deleted; modes/models cleared.
- `/mcp` with `mcp_manager=None` → prints "no MCP servers", never raises.
- Native wrappers: patch the wrapped `run_*` runner and assert it is awaited with the right arg.

### 6.5 What is NOT tested here

Actual LLM generation, streaming, and network calls are out of scope — dispatch never invokes the
provider except `list_models()` (faked). This keeps the whole suite deterministic, offline, and fast,
satisfying the "unit-test the registry + dispatch without a live provider" requirement and the 80%
coverage target for the new `slash/` package.

---

## 7. Architecture Decision Record

### ADR-001: Registry + CommandContext over inline if/elif

**Status:** Proposed

**Context:** The REPL's slash handling is a hardcoded `if/elif` on a channel that lacks references to
sessions, memory, tools, agent, and MCP. Adding commands means editing one file and widening a chain
— high merge contention, no help autogeneration, no path to the ~50 commands industry CLIs ship.

**Decision:** Introduce a `triobot/cli/slash/` package with a decorator-based registry, a single
`CommandContext` carrying the eight live refs `run_agent()` already builds, a pure `dispatch()`
function, and category-grouped command modules. Wire the refs from `agent.py` into `CLIChannel`, and
replace the `if/elif` with one `dispatch()` call. Special-case `!shell` and `@file` inside dispatch.

**Consequences:**
- Easier: adding a command is one decorated function in an existing category file; `/help` updates
  itself; ~50 commands buildable by parallel agents with no dispatcher merge conflicts; registry and
  dispatch are unit-testable offline.
- Harder / trade-offs: one indirection layer (context + registry) versus a flat chain — justified by
  the command count and the need to reach live agent state. `CommandContext` couples the channel to
  the agent's internals (`_user_modes` etc.); accepted deliberately because in-REPL commands MUST
  mutate the same live state the agent reads, and that state has no public setter today. A thin
  `AgentLoop` setter API (`set_mode`, `set_model_override`, `toggle_deep_thinking`) is a recommended
  P2 follow-up to replace private-attribute access.
- Reversible: the registry is additive and self-contained; if it were ever abandoned, the channel
  edit is a ~15-line revert. Low blast radius.
