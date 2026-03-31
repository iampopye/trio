"""trio agent — interactive CLI chat mode."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import logging
import sys

from rich.console import Console

from trio.core.bus import MessageBus
from trio.core.config import load_config, get_agent_defaults
from trio.core.loop import AgentLoop
from trio.core.memory import MemoryStore
from trio.core.session import SessionManager
from trio.channels.cli_channel import CLIChannel
from trio.channels.base import ChannelManager
from trio.providers.base import register_all_providers, ProviderRegistry
from trio.tools.base import ToolRegistry

console = Console()
logger = logging.getLogger(__name__)


async def run_agent(message: str | None = None, no_markdown: bool = False, show_logs: bool = False):
    """Start the interactive CLI agent."""

    # Configure logging
    if show_logs:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    # Load config
    config = load_config()
    defaults = get_agent_defaults(config)

    # Initialize providers
    register_all_providers()
    provider_name = defaults.get("provider", "trio")
    provider_config = config.get("providers", {}).get(provider_name, {})
    provider_config["provider_name"] = provider_name

    # For "local" provider: auto-detect GGUF model path if not set
    if provider_name == "local":
        from trio.providers.local import _find_gguf_model
        model_hint = defaults.get("model", "trio-nano")
        if not provider_config.get("model_path"):
            detected = _find_gguf_model(model_name=model_hint)
            if detected:
                provider_config["model_path"] = detected
                console.print(f"[dim]Auto-detected model: {detected}[/dim]")
            else:
                console.print(
                    f"[yellow]No GGUF model found for '{model_hint}'.[/yellow]\n"
                    "Place a .gguf file in ~/.trio/models/ or set model_path in config."
                )
        provider_config.setdefault("default_model", model_hint)

    try:
        provider = ProviderRegistry.create(provider_name, provider_config)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print("Run [cyan]trio onboard[/cyan] to configure a provider.")
        return

    # Initialize components
    bus = MessageBus()
    sessions = SessionManager()
    memory = MemoryStore()
    tools = ToolRegistry()
    tools.register_builtins(config)

    # Initialize MCP tools if configured
    mcp_config = config.get("tools", {}).get("mcpServers", {})
    mcp_manager = None
    if mcp_config:
        from trio.tools.mcp_client import MCPManager
        mcp_manager = MCPManager()
        mcp_tools = await mcp_manager.start_servers(mcp_config)
        for tool in mcp_tools:
            tools.register(tool)

    # Create agent loop
    agent = AgentLoop(
        bus=bus,
        sessions=sessions,
        memory=memory,
        provider=provider,
        tools=tools,
        config=config,
    )

    # Pre-load model for Ollama (avoids first-request timeout)
    if provider_name == "ollama":
        try:
            model_name = defaults.get("model", "llama3.1:8b")
            console.print(f"[dim]Loading {model_name}...[/dim]")
            await provider.keep_alive(model_name)
            console.print(f"[dim]Model ready.[/dim]")
        except Exception as e:
            console.print(f"[yellow]Warning: Could not pre-load model: {e}[/yellow]")

    # Create CLI channel
    cli = CLIChannel(bus=bus)
    channel_manager = ChannelManager(bus)
    channel_manager.register(cli)

    if message:
        # Single message mode
        cli._response_done.clear()

        agent_task = asyncio.create_task(agent.run())
        channel_task = asyncio.create_task(channel_manager.start_all())

        await cli.publish_inbound(
            chat_id="cli_user",
            user_id="cli_user",
            content=message,
        )

        # Wait for response to complete
        try:
            await asyncio.wait_for(cli._response_done.wait(), timeout=300)
        except asyncio.TimeoutError:
            print("[timeout]")

        agent.stop()
        await channel_manager.stop_all()
        await provider.close()
    else:
        # Interactive mode
        try:
            agent_task = asyncio.create_task(agent.run())
            channel_task = asyncio.create_task(channel_manager.start_all())
            await cli.run_interactive()
        except KeyboardInterrupt:
            pass
        finally:
            agent.stop()
            await channel_manager.stop_all()
            await provider.close()
            if mcp_manager:
                await mcp_manager.stop_all()
