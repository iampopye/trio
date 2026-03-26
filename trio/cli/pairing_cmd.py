"""CLI handler for trio pairing subcommand."""

from rich.console import Console
from rich.table import Table

console = Console()

_PLATFORMS = ("discord", "telegram", "signal", "whatsapp", "slack", "teams", "google_chat", "imessage")


async def run_pairing(args):
    from trio.shared.pairing import (
        approve_pairing, revoke_pairing, list_pending, list_allowed,
    )

    action = getattr(args, "pairing_action", None)

    if action == "approve":
        channel = args.channel
        code = args.code
        result = approve_pairing(channel, code)
        if result:
            console.print(f"[green]Approved![/green] User {result.get('user_id')} on {channel}")
        else:
            console.print(f"[red]Code not found or expired.[/red]")
            pending = list_pending(channel)
            if pending:
                console.print(f"\nPending codes for {channel}:")
                for p in pending:
                    console.print(f"  {p['code']} — user {p['user_id']} ({p['age_minutes']}m ago)")

    elif action == "revoke":
        channel = args.channel
        user_id = args.user_id
        if revoke_pairing(channel, user_id):
            console.print(f"[green]Revoked {user_id} from {channel}[/green]")
        else:
            console.print(f"[red]User {user_id} not found in {channel} allowlist[/red]")

    elif action == "list":
        table = Table(title="Pairing Status")
        table.add_column("Channel", style="cyan")
        table.add_column("Pending")
        table.add_column("Approved")

        for ch in _PLATFORMS:
            pending = list_pending(ch)
            allowed = list_allowed(ch)
            if pending or allowed:
                table.add_row(ch, str(len(pending)), str(len(allowed)))

        if table.row_count == 0:
            console.print("[dim]No pairing activity yet.[/dim]")
        else:
            console.print(table)

    elif action == "pending":
        for ch in _PLATFORMS:
            pending = list_pending(ch)
            if pending:
                console.print(f"\n[bold]{ch}[/bold] — {len(pending)} pending:")
                for p in pending:
                    console.print(f"  Code: [cyan]{p['code']}[/cyan] | "
                                  f"User: {p['user_id']} | {p['age_minutes']}m ago")

    else:
        console.print("[bold]trio pairing[/bold] — manage DM access\n")
        console.print("  [cyan]trio pairing list[/cyan]                    — Show pairing status")
        console.print("  [cyan]trio pairing pending[/cyan]                 — Show pending requests")
        console.print("  [cyan]trio pairing approve <channel> <code>[/cyan] — Approve a request")
        console.print("  [cyan]trio pairing revoke <channel> <user_id>[/cyan] — Revoke access")
