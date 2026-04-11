"""CLI channel — interactive terminal chat for `trio agent`."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import sys
import logging

from trio.channels.base import BaseChannel
from trio.core.bus import MessageBus, StreamChunk, OutboundMessage

logger = logging.getLogger(__name__)


class CLIChannel(BaseChannel):
    """Interactive terminal channel for `trio agent` mode."""

    def __init__(self, bus: MessageBus, config: dict | None = None):
        super().__init__(name="cli", bus=bus, config=config or {})
        self._running = True
        self._streaming = False
        self._streamed_content = False
        self._session_name: str | None = None
        self._response_done = asyncio.Event()

    async def start(self) -> None:
        """Start reading user input from terminal."""
        logger.info("CLI channel started")

    async def stop(self) -> None:
        self._running = False
        self._response_done.set()  # Unblock any waiting

    async def send_message(self, chat_id: str, content: str) -> None:
        """Print final message to terminal."""
        if self._streaming:
            print()  # New line after streaming
            self._streaming = False

        if self._streamed_content:
            # Content was already shown via streaming — only print stats line
            stats_start = content.rfind("\n\n_(")
            if stats_start >= 0:
                print(content[stats_start:])
            self._streamed_content = False
        else:
            print(f"\ntrio: {content}\n")

        # Signal that response is complete
        self._response_done.set()

    async def send_stream_chunk(self, chat_id: str, chunk: StreamChunk) -> None:
        """Print streaming chunks in real-time."""
        if chunk.is_final:
            if self._streaming:
                print()  # New line
                self._streaming = False
            return

        if chunk.chunk:
            if not self._streaming:
                print("\ntrio: ", end="", flush=True)
            print(chunk.chunk, end="", flush=True)
            self._streaming = True
            self._streamed_content = True

    async def run_interactive(self) -> None:
        """Run the interactive input loop."""
        exit_commands = {"exit", "quit", "/exit", "/quit", ":q"}

        print("\ntrio - the open agent framework for every platform")
        print("Type 'exit' to quit, '/help' for slash commands\n")

        while self._running:
            try:
                # Read input
                user_input = await asyncio.to_thread(self._get_input)

                if user_input is None or user_input.strip().lower() in exit_commands:
                    print("\nGoodbye!")
                    self._running = False
                    break

                stripped = user_input.strip()
                if not stripped:
                    continue

                # Handle slash commands locally without sending to LLM
                if stripped.startswith("/"):
                    handled = await self._handle_slash_command(stripped)
                    if handled:
                        continue

                # Reset response event
                self._response_done.clear()

                # Publish to bus
                await self.publish_inbound(
                    chat_id="cli_user",
                    user_id="cli_user",
                    content=stripped,
                )

                # Wait for response to complete
                try:
                    await asyncio.wait_for(self._response_done.wait(), timeout=300)
                except asyncio.TimeoutError:
                    print("\n[timeout — no response after 5 minutes]\n")

                print()  # Blank line before next prompt

            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye!")
                self._running = False
                break

    async def _handle_slash_command(self, cmd: str) -> bool:
        """Handle in-chat slash commands. Returns True if the command was handled."""
        parts = cmd[1:].split(maxsplit=1)
        if not parts:
            return False
        verb = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if verb == "help":
            self._show_slash_help()
            return True

        if verb == "provider":
            await self._slash_provider(arg)
            return True

        if verb == "model":
            await self._slash_model(arg)
            return True

        if verb == "skill":
            await self._slash_skill(arg)
            return True

        if verb == "clear":
            print("\033[2J\033[H", end="")  # ANSI clear screen
            print("trio - chat cleared\n")
            return True

        # Unknown slash command — let it fall through to the LLM
        return False

    def _show_slash_help(self) -> None:
        """Print available slash commands."""
        print("\n\033[1mAvailable slash commands:\033[0m")
        print("  /help                Show this help")
        print("  /provider            Show current provider and how to switch")
        print("  /provider <name>     Switch provider (e.g. /provider openai)")
        print("  /model <name>        Switch model (e.g. /model trio-max)")
        print("  /skill list          List installed skills")
        print("  /skill install <n>   Install a skill from TrioHub")
        print("  /clear               Clear the screen")
        print("  /exit                Exit chat")
        print()
        print("Run \033[36mtrio help\033[0m for the full command reference.\n")

    async def _slash_provider(self, arg: str) -> None:
        """Show or switch provider."""
        from trio.core.config import load_config, save_config

        cfg = load_config()
        current = cfg.get("agents", {}).get("defaults", {}).get("provider", "trio")

        if not arg:
            print(f"\nCurrent provider: \033[36m{current}\033[0m")
            print("Available: trio, ollama, openai, anthropic, gemini, groq, deepseek, openrouter, github_models")
            print("Switch with: /provider <name>\n")
            return

        new_provider = arg.lower().strip()
        cfg.setdefault("agents", {}).setdefault("defaults", {})["provider"] = new_provider
        save_config(cfg)
        print(f"\n✓ Provider switched to: \033[36m{new_provider}\033[0m")
        print("Restart 'trio agent' for the change to take effect.\n")

    async def _slash_model(self, arg: str) -> None:
        """Show or switch model."""
        from trio.core.config import load_config, save_config

        cfg = load_config()
        current = cfg.get("agents", {}).get("defaults", {}).get("model", "trio-max")

        if not arg:
            print(f"\nCurrent model: \033[36m{current}\033[0m")
            print("Built-in: trio-nano, trio-small, trio-medium, trio-high, trio-max, trio-pro")
            print("Switch with: /model <name>\n")
            return

        new_model = arg.strip()
        cfg.setdefault("agents", {}).setdefault("defaults", {})["model"] = new_model
        save_config(cfg)
        print(f"\n✓ Model switched to: \033[36m{new_model}\033[0m")
        print("Restart 'trio agent' for the change to take effect.\n")

    async def _slash_skill(self, arg: str) -> None:
        """List or install skills."""
        if not arg or arg == "list":
            from trio.core.config import get_skills_dir
            skills_dir = get_skills_dir()
            files = list(skills_dir.glob("*.md")) if skills_dir.is_dir() else []
            if not files:
                print("\nNo skills installed yet.")
                print("Browse: \033[36mtrio hub trending\033[0m")
                print("Install: \033[36m/skill install <name>\033[0m\n")
                return
            print(f"\nInstalled skills ({len(files)}):")
            for f in sorted(files)[:50]:
                print(f"  • {f.stem}")
            if len(files) > 50:
                print(f"  ... and {len(files) - 50} more")
            print()
            return

        if arg.startswith("install "):
            skill_name = arg[len("install "):].strip()
            print(f"\nTo install '{skill_name}', run in a separate terminal:")
            print(f"  \033[36mtrio skill install {skill_name}\033[0m\n")
            return

        print("\nUsage: /skill list | /skill install <name>\n")

    def set_session_name(self, name: str | None):
        """Set the current session name for the prompt."""
        self._session_name = name

    def _get_input(self) -> str | None:
        """Read a line from stdin (blocking, runs in thread)."""
        try:
            prompt = f"[{self._session_name}] You: " if self._session_name else "You: "
            return input(prompt)
        except (KeyboardInterrupt, EOFError):
            return None
