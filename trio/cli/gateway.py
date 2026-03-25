"""trio gateway — start all enabled channels."""

import asyncio
import logging

from rich.console import Console

from trio.core.bus import MessageBus
from trio.core.config import load_config, get_agent_defaults
from trio.core.loop import AgentLoop
from trio.core.memory import MemoryStore
from trio.core.session import SessionManager
from trio.channels.base import ChannelManager
from trio.providers.base import register_all_providers, ProviderRegistry
from trio.tools.base import ToolRegistry

console = Console()
logger = logging.getLogger(__name__)


async def run_gateway():
    """Start the gateway with all enabled channels."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    config = load_config()
    defaults = get_agent_defaults(config)

    # Initialize provider
    register_all_providers()
    provider_name = defaults.get("provider", "trio")
    provider_config = config.get("providers", {}).get(provider_name, {})
    provider_config["provider_name"] = provider_name

    try:
        provider = ProviderRegistry.create(provider_name, provider_config)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        return

    # Initialize core
    bus = MessageBus()
    sessions = SessionManager()
    memory = MemoryStore()
    tools = ToolRegistry()
    tools.register_builtins(config)

    # MCP tools
    mcp_config = config.get("tools", {}).get("mcpServers", {})
    mcp_manager = None
    if mcp_config:
        from trio.tools.mcp_client import MCPManager
        mcp_manager = MCPManager()
        mcp_tools = await mcp_manager.start_servers(mcp_config)
        for tool in mcp_tools:
            tools.register(tool)

    # Agent loop
    agent = AgentLoop(bus=bus, sessions=sessions, memory=memory,
                      provider=provider, tools=tools, config=config)

    # Channel manager
    channel_manager = ChannelManager(bus)
    channels_config = config.get("channels", {})

    # Register enabled channels
    enabled_count = 0

    if channels_config.get("discord", {}).get("enabled"):
        try:
            from trio.channels.discord_channel import DiscordChannel
            dc = DiscordChannel(bus=bus, config=channels_config["discord"])
            channel_manager.register(dc)
            enabled_count += 1
        except ImportError:
            console.print("[yellow]Discord: install discord.py (pip install trio-ai[discord])[/yellow]")

    if channels_config.get("telegram", {}).get("enabled"):
        try:
            from trio.channels.telegram_channel import TelegramChannel
            tc = TelegramChannel(bus=bus, config=channels_config["telegram"])
            channel_manager.register(tc)
            enabled_count += 1
        except ImportError:
            console.print("[yellow]Telegram: install pyTelegramBotAPI (pip install trio-ai[telegram])[/yellow]")

    if channels_config.get("signal", {}).get("enabled"):
        try:
            from trio.channels.signal_channel import SignalChannel
            sc = SignalChannel(bus=bus, config=channels_config["signal"])
            channel_manager.register(sc)
            enabled_count += 1
        except ImportError:
            console.print("[yellow]Signal channel not available[/yellow]")

    if channels_config.get("whatsapp", {}).get("enabled"):
        try:
            from trio.channels.whatsapp_channel import WhatsAppChannel
            wa = WhatsAppChannel(bus=bus, config=channels_config["whatsapp"])
            channel_manager.register(wa)
            enabled_count += 1
        except ImportError:
            console.print("[yellow]WhatsApp: install aiohttp (pip install aiohttp)[/yellow]")

    if channels_config.get("slack", {}).get("enabled"):
        try:
            from trio.channels.slack_channel import SlackChannel
            sl = SlackChannel(bus=bus, config=channels_config["slack"])
            channel_manager.register(sl)
            enabled_count += 1
        except ImportError:
            console.print("[yellow]Slack: install slack-sdk (pip install trio-ai[slack])[/yellow]")

    if channels_config.get("teams", {}).get("enabled"):
        try:
            from trio.channels.teams_channel import TeamsChannel
            tm = TeamsChannel(bus=bus, config=channels_config["teams"])
            channel_manager.register(tm)
            enabled_count += 1
        except ImportError:
            console.print("[yellow]Teams: install botbuilder-core (pip install trio-ai[teams])[/yellow]")

    if channels_config.get("google_chat", {}).get("enabled"):
        try:
            from trio.channels.google_chat_channel import GoogleChatChannel
            gc = GoogleChatChannel(bus=bus, config=channels_config["google_chat"])
            channel_manager.register(gc)
            enabled_count += 1
        except ImportError:
            console.print("[yellow]Google Chat: install google-auth (pip install trio-ai[google_chat])[/yellow]")

    if channels_config.get("imessage", {}).get("enabled"):
        try:
            from trio.channels.imessage_channel import IMessageChannel
            im = IMessageChannel(bus=bus, config=channels_config["imessage"])
            channel_manager.register(im)
            enabled_count += 1
        except (ImportError, RuntimeError) as e:
            console.print(f"[yellow]iMessage: {e}[/yellow]")

    if enabled_count == 0:
        console.print("[red]No channels enabled. Edit ~/.trio/config.json or run 'trio onboard'.[/red]")
        return

    # Heartbeat channel + daemon
    heartbeat_daemon = None
    if config.get("heartbeat", {}).get("enabled"):
        from trio.channels.heartbeat_channel import HeartbeatChannel
        from trio.cron.heartbeat import HeartbeatDaemon

        hb_channel = HeartbeatChannel(bus=bus, config=config)
        channel_manager.register(hb_channel)
        heartbeat_daemon = HeartbeatDaemon(bus=bus, config=config)

    console.print(f"[green]Starting gateway with {enabled_count} channel(s)...[/green]")

    try:
        tasks = [agent.run(), channel_manager.start_all()]
        if heartbeat_daemon:
            tasks.append(heartbeat_daemon.start())
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/yellow]")
    finally:
        agent.stop()
        await channel_manager.stop_all()
        if heartbeat_daemon:
            await heartbeat_daemon.stop()
        await provider.close()
        if mcp_manager:
            await mcp_manager.stop_all()
