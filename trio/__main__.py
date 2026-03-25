"""CLI entry point for trio."""

import argparse
import asyncio
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="trioai",
        description="trio - the open agent framework for every platform",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # trio onboard
    subparsers.add_parser("onboard", help="Initialize config and workspace")

    # trio agent
    agent_parser = subparsers.add_parser("agent", help="Interactive chat mode")
    agent_parser.add_argument("-m", "--message", help="Send a single message")
    agent_parser.add_argument("--no-markdown", action="store_true", help="Plain text output")
    agent_parser.add_argument("--logs", action="store_true", help="Show runtime logs")

    # trio gateway
    subparsers.add_parser("gateway", help="Start all enabled channels")

    # trio provider
    provider_parser = subparsers.add_parser("provider", help="Manage LLM providers")
    provider_sub = provider_parser.add_subparsers(dest="provider_action")
    provider_sub.add_parser("add", help="Add a new provider interactively")
    provider_sub.add_parser("list", help="List configured providers")
    provider_sub.add_parser("login", help="OAuth login for a provider")

    # trio status
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
