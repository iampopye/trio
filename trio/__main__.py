"""CLI entry point for trio."""

import argparse
import asyncio
import os
import sys


def _ensure_path():
    """On Windows, ensure pip Scripts folder is on PATH so 'trioai' works."""
    if sys.platform != "win32":
        return
    scripts_dir = os.path.join(os.path.dirname(sys.executable), "Scripts")
    if not os.path.isdir(scripts_dir):
        # Microsoft Store Python uses a different layout
        import site
        user_scripts = os.path.join(site.getusersitepackages().replace("site-packages", ""), "Scripts")
        if os.path.isdir(user_scripts):
            scripts_dir = user_scripts
        else:
            return
    user_path = os.environ.get("PATH", "")
    if scripts_dir.lower() not in user_path.lower():
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS) as key:
                current, _ = winreg.QueryValueEx(key, "PATH")
                if scripts_dir.lower() not in current.lower():
                    winreg.SetValueEx(key, "PATH", 0, winreg.REG_EXPAND_SZ, current + ";" + scripts_dir)
                    print(f"[trio.ai] Added {scripts_dir} to your PATH.")
                    print("[trio.ai] Restart your terminal for 'trioai' command to work.\n")
        except Exception:
            pass


def main():
    _ensure_path()

    parser = argparse.ArgumentParser(
        prog="trioai",
        description="trio.ai - train your own AI, deploy it everywhere",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # trioai onboard
    subparsers.add_parser("onboard", help="Initialize config and workspace")

    # trioai agent
    agent_parser = subparsers.add_parser("agent", help="Interactive chat mode")
    agent_parser.add_argument("-m", "--message", help="Send a single message")
    agent_parser.add_argument("--no-markdown", action="store_true", help="Plain text output")
    agent_parser.add_argument("--logs", action="store_true", help="Show runtime logs")

    # trioai gateway
    subparsers.add_parser("gateway", help="Start all enabled channels")

    # trioai provider
    provider_parser = subparsers.add_parser("provider", help="Manage LLM providers")
    provider_sub = provider_parser.add_subparsers(dest="provider_action")
    provider_sub.add_parser("add", help="Add a new provider interactively")
    provider_sub.add_parser("list", help="List configured providers")
    provider_sub.add_parser("login", help="OAuth login for a provider")

    # trioai status
    subparsers.add_parser("status", help="Show system status")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "onboard":
        from trio.cli.onboard import run_onboard
        asyncio.run(run_onboard())

    elif args.command == "agent":
        from trio.cli.agent import run_agent
        asyncio.run(run_agent(
            message=args.message,
            no_markdown=args.no_markdown,
            show_logs=args.logs,
        ))

    elif args.command == "gateway":
        from trio.cli.gateway import run_gateway
        asyncio.run(run_gateway())

    elif args.command == "provider":
        from trio.cli.provider_cmd import run_provider
        asyncio.run(run_provider(args.provider_action))

    elif args.command == "status":
        from trio.cli.status import run_status
        asyncio.run(run_status())


if __name__ == "__main__":
    main()
