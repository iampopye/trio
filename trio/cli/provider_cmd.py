"""trio provider — manage LLM providers."""

from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt

from trio.core.config import load_config, save_config
from trio.providers.openai_compat import KNOWN_PROVIDERS

console = Console()


async def run_provider(action: str | None = None):
    """Manage LLM providers."""
    if action == "add":
        await _add_provider()
    elif action == "list":
        _list_providers()
    elif action == "login":
        console.print("[yellow]OAuth login not yet implemented.[/yellow]")
    else:
        console.print("Usage: trio provider [add|list|login]")


async def _add_provider():
    """Interactively add a new provider."""
    console.print("\n[bold]Add a new LLM provider[/bold]\n")

    provider_choices = list(KNOWN_PROVIDERS.keys()) + ["ollama", "custom"]
    console.print("Available providers:")
    for p in provider_choices:
        base = KNOWN_PROVIDERS.get(p, "local" if p == "ollama" else "custom URL")
        console.print(f"  [cyan]{p}[/cyan] — {base}")

    name = Prompt.ask("\nProvider name", choices=provider_choices)

    config = load_config()

    if name == "ollama":
        base_url = Prompt.ask("Ollama URL", default="http://localhost:11434")
        model = Prompt.ask("Default model", default="llama3.1:8b")
        config["providers"]["ollama"] = {
            "base_url": base_url,
            "default_model": model,
        }
    elif name == "custom":
        api_base = Prompt.ask("API base URL (e.g. http://localhost:8000/v1)")
        api_key = Prompt.ask("API key (leave empty if none)", default="")
        model = Prompt.ask("Default model name")
        config["providers"]["custom"] = {
            "apiBase": api_base,
            "apiKey": api_key,
            "default_model": model,
            "provider_name": "custom",
        }
    else:
        api_key = Prompt.ask(f"{name} API key")
        model = Prompt.ask("Default model")
        config["providers"][name] = {
            "apiKey": api_key,
            "default_model": model,
            "provider_name": name,
        }

    # Ask if this should be the default
    from rich.prompt import Confirm
    if Confirm.ask(f"Set {name} as default provider?", default=True):
        config["agents"]["defaults"]["provider"] = name
        config["agents"]["defaults"]["model"] = model if name != "ollama" else config["providers"]["ollama"]["default_model"]

    save_config(config)
    console.print(f"\n[green]Provider '{name}' added successfully![/green]")


def _list_providers():
    """List all configured providers."""
    config = load_config()
    providers = config.get("providers", {})
    defaults = config.get("agents", {}).get("defaults", {})
    default_provider = defaults.get("provider", "trio")

    table = Table(title="Configured Providers")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Default Model")
    table.add_column("Default", style="yellow")

    for name, pconfig in providers.items():
        is_default = "***" if name == default_provider else ""
        model = pconfig.get("default_model", "")
        ptype = "built-in" if name == "trio" else ("ollama" if name == "ollama" else "openai-compat")
        table.add_row(name, ptype, model, is_default)

    console.print(table)
