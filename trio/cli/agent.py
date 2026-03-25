"""trio agent — interactive CLI chat mode."""

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

    # Create CLI channel
    cli = CLIChannel(bus=bus)
    channel_manager = ChannelManager(bus)
    channel_manager.register(cli)

    if message:
        # Single message mode
        await cli.publish_inbound(
            chat_id="cli_user",
            user_id="cli_user",
            content=message,
        )

        # Run agent for one turn
        agent_task = asyncio.create_task(agent.run())
        channel_task = asyncio.create_task(channel_manager.start_all())

        # Wait for response
        await asyncio.sleep(0.1)
        while bus.outbound_pending > 0 or bus.inbound_pending > 0:
            await asyncio.sleep(0.1)
        await asyncio.sleep(1)

        agent.stop()
        await channel_manager.stop_all()
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
