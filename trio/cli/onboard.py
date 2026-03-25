"""trio onboard — interactive setup wizard."""

import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

from trio.core.config import (
    get_trio_dir, get_config_path, get_workspace_dir,
    get_memory_dir, get_sessions_dir, get_skills_dir,
    DEFAULT_CONFIG, save_config,
)

console = Console()


def _friendly_path(p: Path) -> str:
    """Show ~/.trio/... instead of full absolute path for privacy."""
    try:
        rel = p.relative_to(Path.home())
        return f"~/{rel.as_posix()}"
    except ValueError:
        return p.name


async def run_onboard():
    """Interactive setup wizard for first-time users."""
    console.print(Panel.fit(
        "[bold cyan]Welcome to trio.ai![/bold cyan]\n"
        "Train your own AI. Deploy it everywhere.\n\n"
        "Let's get you set up.",
        border_style="cyan",
    ))

    trio_dir = get_trio_dir()
    config_path = get_config_path()

    # Check if already configured
    if config_path.exists():
        if not Confirm.ask("\n[yellow]Config already exists. Overwrite?[/yellow]", default=False):
            console.print("[green]Keeping existing config.[/green]")
            return

    config = DEFAULT_CONFIG.copy()

    # Provider setup
    console.print("\n[bold]Step 1: LLM Provider[/bold]")
    console.print(
        "Choose how trio powers its AI:\n"
        "  [cyan]default[/cyan]  — Built-in Trio model (runs on your system, no API keys needed)\n"
        "  [cyan]custom[/cyan]   — Use an external model (Ollama, OpenAI, Claude, Gemini, etc.)\n"
    )

    mode = Prompt.ask(
        "Setup mode",
        choices=["default", "custom"],
        default="default",
    )

    if mode == "default":
        # Built-in Trio model — zero config needed
        console.print("\n[green]Using built-in Trio model (trio-nano).[/green]")
        console.print("[dim]The model will auto-initialize on first use using your system's CPU.[/dim]")
        console.print("[dim]No downloads, no API keys, no external dependencies.[/dim]")

        preset = Prompt.ask(
            "Model size",
            choices=["nano", "small", "medium"],
            default="nano",
        )
        model_name = f"trio-{preset}"

        config["providers"]["trio"] = {"default_model": model_name}
        config["agents"]["defaults"]["provider"] = "trio"
        config["agents"]["defaults"]["model"] = model_name

    else:
        # Custom provider
        console.print("\n[bold]Select your provider:[/bold]")
        provider = Prompt.ask(
            "Provider",
            choices=["ollama", "openai", "anthropic", "gemini", "groq", "openrouter", "deepseek"],
            default="ollama",
        )

        if provider == "ollama":
            base_url = Prompt.ask("Ollama URL", default="http://localhost:11434")
            model = Prompt.ask("Default model", default="llama3.1:8b")
            config["providers"]["ollama"] = {
                "base_url": base_url,
                "default_model": model,
            }
            config["agents"]["defaults"]["provider"] = "ollama"
            config["agents"]["defaults"]["model"] = model
        else:
            api_key = Prompt.ask(f"{provider} API key")
            model = Prompt.ask("Default model")
            config["providers"][provider] = {
                "apiKey": api_key,
                "default_model": model,
            }
            config["agents"]["defaults"]["provider"] = provider
            config["agents"]["defaults"]["model"] = model

    # Channel setup
    console.print("\n[bold]Step 2: Chat Channels (optional)[/bold]")
    console.print("You can always add channels later in config.json.\n")

    if Confirm.ask("Enable Discord?", default=False):
        token = Prompt.ask("Discord bot token")
        config["channels"]["discord"]["enabled"] = True
        config["channels"]["discord"]["token"] = token

    if Confirm.ask("Enable Telegram?", default=False):
        token = Prompt.ask("Telegram bot token")
        admin_id = Prompt.ask("Your Telegram user ID (admin)", default="0")
        config["channels"]["telegram"]["enabled"] = True
        config["channels"]["telegram"]["token"] = token
        config["channels"]["telegram"]["admin_id"] = int(admin_id)

    if Confirm.ask("Enable Signal?", default=False):
        phone = Prompt.ask("Signal phone number (e.g. +1234567890)")
        config["channels"]["signal"]["enabled"] = True
        config["channels"]["signal"]["phone"] = phone

    # Create directories
    console.print("\n[bold]Step 3: Creating workspace...[/bold]")

    dirs = [
        get_workspace_dir(),
        get_memory_dir(),
        get_sessions_dir(),
        get_skills_dir(),
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        console.print(f"  Created {_friendly_path(d)}")

    # Create workspace files
    soul_path = get_workspace_dir() / "SOUL.md"
    if not soul_path.exists():
        soul_path.write_text(
            "# trio Personality\n\n"
            "You are trio, a helpful and friendly AI assistant.\n"
            "Be concise, accurate, and helpful.\n"
            "Adapt your tone to match the user's style.\n",
            encoding="utf-8",
        )

    user_path = get_workspace_dir() / "USER.md"
    if not user_path.exists():
        user_path.write_text(
            "# User Context\n\n"
            "Add information about yourself here.\n"
            "trio will use this to personalize responses.\n",
            encoding="utf-8",
        )

    # Save config
    save_config(config)
    console.print(f"\n  Config saved to {_friendly_path(config_path)}")

    # Done
    provider_info = config["agents"]["defaults"]["provider"]
    model_info = config["agents"]["defaults"]["model"]

    console.print(Panel.fit(
        "[bold green]Setup complete![/bold green]\n\n"
        f"Provider: {provider_info}\n"
        f"Model: {model_info}\n"
        f"Config: {_friendly_path(config_path)}\n"
        f"Workspace: {_friendly_path(get_workspace_dir())}\n\n"
        "Quick start:\n"
        "  [cyan]trio agent[/cyan]      — Chat in terminal\n"
        "  [cyan]trio gateway[/cyan]    — Start all channels\n"
        "  [cyan]trio status[/cyan]     — Check system status\n"
        "  [cyan]trio provider add[/cyan] — Add another provider",
        border_style="green",
    ))
