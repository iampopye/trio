"""CLI entry point for trio."""

import argparse
import asyncio
import os
import sys


def _ensure_path():
    """Ensure pip scripts folder is on PATH so 'trio' command works.

    Supports Windows, macOS, and Linux.
    """
    from pathlib import Path

    if sys.platform == "win32":
        # Windows: add Scripts folder to user PATH via registry
        scripts_dir = os.path.join(os.path.dirname(sys.executable), "Scripts")
        if not os.path.isdir(scripts_dir):
            try:
                import site
                user_scripts = os.path.join(
                    site.getusersitepackages().replace("site-packages", ""), "Scripts"
                )
                if os.path.isdir(user_scripts):
                    scripts_dir = user_scripts
                else:
                    return
            except Exception:
                return
        user_path = os.environ.get("PATH", "")
        if scripts_dir.lower() not in user_path.lower():
            try:
                import winreg
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS
                ) as key:
                    current, _ = winreg.QueryValueEx(key, "PATH")
                    if scripts_dir.lower() not in current.lower():
                        winreg.SetValueEx(
                            key, "PATH", 0, winreg.REG_EXPAND_SZ,
                            current + ";" + scripts_dir,
                        )
                        print(f"[trio.ai] Added {scripts_dir} to your PATH.")
                        print("[trio.ai] Restart your terminal for 'trio' command to work.\n")
            except Exception:
                pass

    else:
        # macOS / Linux: check if ~/.local/bin is on PATH
        local_bin = Path.home() / ".local" / "bin"
        user_path = os.environ.get("PATH", "")
        if str(local_bin) not in user_path and local_bin.is_dir():
            # Detect shell profile
            shell = os.environ.get("SHELL", "/bin/bash")
            if "zsh" in shell:
                profile = Path.home() / ".zshrc"
            elif "fish" in shell:
                profile = Path.home() / ".config" / "fish" / "config.fish"
            else:
                profile = Path.home() / ".bashrc"

            export_line = f'export PATH="$HOME/.local/bin:$PATH"'
            try:
                if profile.exists():
                    content = profile.read_text(encoding="utf-8", errors="ignore")
                    if ".local/bin" not in content:
                        with open(profile, "a", encoding="utf-8") as f:
                            f.write(f"\n# Added by trio.ai\n{export_line}\n")
                        print(f"[trio.ai] Added ~/.local/bin to PATH in {profile.name}")
                        print("[trio.ai] Restart your terminal or run: source " + str(profile) + "\n")
            except Exception:
                pass


def main():
    _ensure_path()

    parser = argparse.ArgumentParser(
        prog="trio",
        description="trio.ai - train your own AI, deploy it everywhere",
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

    # trio heartbeat
    hb_parser = subparsers.add_parser("heartbeat", help="Heartbeat daemon management")
    hb_sub = hb_parser.add_subparsers(dest="hb_action")
    hb_sub.add_parser("status", help="Show heartbeat status")
    hb_sub.add_parser("log", help="Show recent heartbeat log")
    hb_sub.add_parser("edit", help="Open HEARTBEAT.md for editing")

    # trio plugin
    plugin_parser = subparsers.add_parser("plugin", help="Manage plugins")
    plugin_sub = plugin_parser.add_subparsers(dest="plugin_action")
    plugin_sub.add_parser("list", help="List installed plugins")
    plugin_sub.add_parser("install", help="Install a plugin").add_argument("path", help="Plugin path or URL")
    plugin_sub.add_parser("uninstall", help="Uninstall a plugin").add_argument("name", help="Plugin name")
    plugin_sub.add_parser("enable", help="Enable a plugin").add_argument("name", help="Plugin name")
    plugin_sub.add_parser("disable", help="Disable a plugin").add_argument("name", help="Plugin name")

    # trio skill
    skill_parser = subparsers.add_parser("skill", help="Manage skills")
    skill_sub = skill_parser.add_subparsers(dest="skill_action")
    skill_sub.add_parser("list", help="List installed skills")
    skill_search = skill_sub.add_parser("search", help="Search TrioHub for skills")
    skill_search.add_argument("query", help="Search query")
    skill_install = skill_sub.add_parser("install", help="Install a skill from TrioHub")
    skill_install.add_argument("name", help="Skill name")

    # trio hub
    hub_parser = subparsers.add_parser("hub", help="TrioHub community registry")
    hub_sub = hub_parser.add_subparsers(dest="hub_action")
    hub_sub.add_parser("search", help="Search TrioHub").add_argument("query", help="Search query")
    hub_sub.add_parser("trending", help="Show trending skills and plugins")

    # trio doctor
    doctor_parser = subparsers.add_parser("doctor", help="Diagnose and repair system issues")
    doctor_parser.add_argument("--fix", action="store_true", help="Auto-repair fixable issues")

    # trio update
    update_parser = subparsers.add_parser("update", help="Update trio to the latest version")
    update_parser.add_argument("--channel", default="stable", help="Update channel (default: stable)")

    # trio pairing
    pairing_parser = subparsers.add_parser("pairing", help="Manage DM pairing security")
    pairing_sub = pairing_parser.add_subparsers(dest="pairing_action")
    pairing_sub.add_parser("list", help="Show pairing status across channels")
    pairing_sub.add_parser("pending", help="Show pending pairing requests")
    pairing_approve = pairing_sub.add_parser("approve", help="Approve a pairing request")
    pairing_approve.add_argument("channel", help="Channel name (discord, telegram, etc.)")
    pairing_approve.add_argument("code", help="Pairing code")
    pairing_revoke = pairing_sub.add_parser("revoke", help="Revoke a user's access")
    pairing_revoke.add_argument("channel", help="Channel name")
    pairing_revoke.add_argument("user_id", help="User ID to revoke")

    # trio daemon
    daemon_parser = subparsers.add_parser("daemon", help="Manage background gateway service")
    daemon_sub = daemon_parser.add_subparsers(dest="daemon_action")
    daemon_sub.add_parser("install", help="Install as system service (auto-start)")
    daemon_sub.add_parser("uninstall", help="Remove system service")
    daemon_sub.add_parser("start", help="Start daemon in background")
    daemon_sub.add_parser("stop", help="Stop running daemon")
    daemon_sub.add_parser("restart", help="Restart the daemon")
    daemon_sub.add_parser("status", help="Show daemon status (PID, uptime, health)")
    daemon_sub.add_parser("logs", help="Show daemon logs")

    # trio serve
    serve_parser = subparsers.add_parser("serve", help="Start browser-based chat UI")
    serve_parser.add_argument("--port", type=int, default=3000, help="Port (default: 3000)")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")

    # trio train
    train_parser = subparsers.add_parser("train", help="Train or retrain the trio-max model")
    train_parser.add_argument("--reset", action="store_true", help="Start fresh, ignore saved progress")
    train_parser.add_argument("--setup", action="store_true", help="Download and install trio-max/nano via Ollama")

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

    elif args.command == "heartbeat":
        from trio.cli.heartbeat_cmd import run_heartbeat
        asyncio.run(run_heartbeat(args.hb_action))

    elif args.command == "plugin":
        from trio.cli.plugin_cmd import run_plugin
        asyncio.run(run_plugin(args))

    elif args.command == "skill":
        from trio.cli.skill_cmd import run_skill
        asyncio.run(run_skill(args))

    elif args.command == "hub":
        from trio.cli.hub_cmd import run_hub
        asyncio.run(run_hub(args))

    elif args.command == "doctor":
        from trio.cli.doctor_cmd import run_doctor
        asyncio.run(run_doctor(fix=args.fix))

    elif args.command == "update":
        from trio.cli.update_cmd import run_update
        asyncio.run(run_update(channel=args.channel))

    elif args.command == "pairing":
        from trio.cli.pairing_cmd import run_pairing
        asyncio.run(run_pairing(args))

    elif args.command == "daemon":
        from trio.cli.daemon_cmd import run_daemon
        asyncio.run(run_daemon(args.daemon_action))

    elif args.command == "serve":
        from trio.web.app import run_server
        run_server(host=args.host, port=args.port)

    elif args.command == "train":
        if args.setup:
            # Download pre-quantized GGUF models and register with Ollama
            import subprocess
            script = os.path.join(os.path.dirname(__file__), "..", "scripts", "setup_models.py")
            script = os.path.normpath(script)
            if not os.path.exists(script):
                print("[trio.ai] Error: setup_models.py not found at", script)
                sys.exit(1)
            print("[trio.ai] Setting up trio-max and trio-nano via Ollama...\n")
            subprocess.run([sys.executable, "-u", script])
        else:
            # Train from scratch using local training pipeline
            import subprocess
            script = os.path.join(os.path.dirname(__file__), "..", "scripts", "train_default_model.py")
            if not os.path.exists(script):
                script = os.path.join(os.path.dirname(__file__), "..", "scripts", "train_default_model.py")
            cmd = [sys.executable, "-u", script]
            if args.reset:
                cmd.append("--reset")
            print("[trio.ai] Starting model training...")
            print("[trio.ai] You can pause anytime (Ctrl+C) and resume with: trio train\n")
            subprocess.run(cmd)


if __name__ == "__main__":
    main()
