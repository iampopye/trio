"""trio daemon — background gateway service management.

Subcommands:
    trio daemon install    — Install as system service (systemd / launchd / Windows)
    trio daemon uninstall  — Remove system service
    trio daemon start      — Start daemon in background
    trio daemon stop       — Stop running daemon
    trio daemon restart    — Restart daemon
    trio daemon status     — Show daemon status (PID, uptime, channels, health)
    trio daemon logs       — Show recent daemon logs (tail-f style)
"""

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from trio.core.config import get_trio_dir

console = Console()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_state_dir() -> Path:
    d = get_trio_dir() / "daemon"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_trio_command() -> str:
    """Get the full path to the trio executable."""
    trio_bin = shutil.which("trio")
    if trio_bin:
        return trio_bin
    return f"{sys.executable} -m trio"


def _python_exe() -> str:
    """Return the Python interpreter path."""
    return sys.executable


def _pythonw_exe() -> str:
    """Return pythonw.exe on Windows (no console window), else python."""
    if sys.platform == "win32":
        base = Path(sys.executable)
        pythonw = base.parent / "pythonw.exe"
        if pythonw.exists():
            return str(pythonw)
    return sys.executable


def _format_uptime(seconds: float) -> str:
    """Human-readable uptime string."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds / 60:.0f}m {seconds % 60:.0f}s"
    elif seconds < 86400:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m"
    else:
        d = int(seconds // 86400)
        h = int((seconds % 86400) // 3600)
        return f"{d}d {h}h"


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

async def run_daemon(action: str | None):
    """Main entry point — dispatched from ``trio daemon <action>``."""
    handlers = {
        "install": _cmd_install,
        "uninstall": _cmd_uninstall,
        "start": _cmd_start,
        "stop": _cmd_stop,
        "restart": _cmd_restart,
        "status": _cmd_status,
        "logs": _cmd_logs,
    }

    handler = handlers.get(action)
    if handler:
        handler()
    else:
        _cmd_help()


# ---------------------------------------------------------------------------
# trio daemon start / stop / restart
# ---------------------------------------------------------------------------

def _cmd_start():
    """Start the daemon as a background process."""
    from trio.cron.daemon import TrioDaemon

    running, pid = TrioDaemon.is_running()
    if running:
        console.print(f"[yellow]Daemon already running (PID {pid})[/yellow]")
        return

    console.print("[cyan]Starting trio daemon...[/cyan]")

    # Launch a detached subprocess that runs the daemon
    cmd = [_pythonw_exe(), "-m", "trio.cron.daemon"]

    state_dir = _get_state_dir()
    stdout_log = state_dir / "daemon_stdout.log"
    stderr_log = state_dir / "daemon_stderr.log"

    if sys.platform == "win32":
        # Windows: use CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        DETACHED_PROCESS = 0x00000008
        with open(stdout_log, "a") as out, open(stderr_log, "a") as err:
            proc = subprocess.Popen(
                cmd,
                stdout=out,
                stderr=err,
                stdin=subprocess.DEVNULL,
                creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS,
            )
    else:
        # Unix: nohup-style detach via start_new_session
        with open(stdout_log, "a") as out, open(stderr_log, "a") as err:
            proc = subprocess.Popen(
                cmd,
                stdout=out,
                stderr=err,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )

    # Wait briefly for PID file to appear
    for _ in range(20):
        time.sleep(0.5)
        running, pid = TrioDaemon.is_running()
        if running:
            console.print(f"[green]Daemon started (PID {pid})[/green]")
            return

    # Check if the process we launched is still alive
    if proc.poll() is None:
        console.print(
            f"[green]Daemon launched (process PID {proc.pid}), "
            f"waiting for initialization...[/green]"
        )
    else:
        console.print(
            "[red]Daemon process exited immediately. "
            "Check logs: trio daemon logs[/red]"
        )


def _cmd_stop():
    """Stop the running daemon."""
    from trio.cron.daemon import TrioDaemon

    running, pid = TrioDaemon.is_running()
    if not running:
        console.print("[yellow]Daemon is not running.[/yellow]")
        return

    console.print(f"[cyan]Stopping daemon (PID {pid})...[/cyan]")
    stopped = TrioDaemon.stop()
    if stopped:
        console.print("[green]Daemon stopped.[/green]")
    else:
        console.print("[red]Failed to stop daemon.[/red]")


def _cmd_restart():
    """Restart the daemon (stop then start)."""
    from trio.cron.daemon import TrioDaemon

    running, pid = TrioDaemon.is_running()
    if running:
        console.print(f"[cyan]Stopping daemon (PID {pid})...[/cyan]")
        TrioDaemon.stop()
        time.sleep(1)

    _cmd_start()


# ---------------------------------------------------------------------------
# trio daemon status
# ---------------------------------------------------------------------------

def _cmd_status():
    """Show detailed daemon status."""
    from trio.cron.daemon import TrioDaemon

    running, pid = TrioDaemon.is_running()
    status_data = TrioDaemon.get_status()

    table = Table(title="trio daemon status", show_header=False, border_style="dim")
    table.add_column("Key", style="bold")
    table.add_column("Value")

    if running:
        table.add_row("State", "[green]RUNNING[/green]")
        table.add_row("PID", str(pid))
    else:
        table.add_row("State", "[red]STOPPED[/red]")
        table.add_row("PID", "-")

    if status_data:
        uptime = status_data.get("uptime_seconds", 0)
        if running:
            # Recalculate uptime from started_at
            started_at = status_data.get("started_at")
            if started_at:
                uptime = time.time() - started_at
            table.add_row("Uptime", _format_uptime(uptime))
        else:
            table.add_row("Uptime", "-")

        channels = status_data.get("channels", [])
        table.add_row("Channels", ", ".join(channels) if channels else "(none)")

        last_check = status_data.get("last_health_check", "-")
        table.add_row("Last health check", last_check)

        health = status_data.get("health", {})
        if health:
            for component, state in health.items():
                if component == "memory_mb":
                    table.add_row("Memory (MB)", state)
                else:
                    color = "green" if state == "ok" else "yellow"
                    table.add_row(f"  {component}", f"[{color}]{state}[/{color}]")
    else:
        if running:
            table.add_row("Details", "(status file not yet written)")
        else:
            table.add_row("Details", "(no status data available)")

    # Service installation status
    svc_status = _service_install_status()
    table.add_row("System service", svc_status)

    console.print(table)

    # Memory usage from OS (live check if running)
    if running and pid:
        mem = _get_process_memory(pid)
        if mem:
            console.print(f"[dim]Live memory usage: {mem}[/dim]")


def _service_install_status() -> str:
    """Check whether a system service is installed."""
    system = platform.system()
    if system == "Darwin":
        if _LAUNCHD_PLIST.exists():
            return "[green]launchd (installed)[/green]"
    elif system == "Linux":
        if _SYSTEMD_PATH.exists():
            return "[green]systemd (installed)[/green]"
    elif system == "Windows":
        # Check scheduled task
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", _WIN_TASK_NAME, "/FO", "LIST"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return "[green]Scheduled Task (installed)[/green]"
        startup = _win_startup_dir()
        if startup and (startup / "trio-daemon.cmd").exists():
            return "[green]Startup folder (installed)[/green]"
    return "[dim]not installed[/dim]"


def _get_process_memory(pid: int) -> str | None:
    """Get memory usage for a PID (cross-platform)."""
    if sys.platform == "win32":
        try:
            import ctypes
            import ctypes.wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.wintypes.DWORD),
                    ("PageFaultCount", ctypes.wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid,
            )
            if not handle:
                return None
            try:
                counters = PROCESS_MEMORY_COUNTERS()
                counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
                ctypes.windll.psapi.GetProcessMemoryInfo(
                    handle, ctypes.byref(counters), counters.cb,
                )
                mb = counters.WorkingSetSize / (1024 * 1024)
                return f"{mb:.1f} MB"
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            return None
    else:
        try:
            # /proc on Linux, ps on macOS
            if Path("/proc").exists():
                status = Path(f"/proc/{pid}/status").read_text()
                for line in status.splitlines():
                    if line.startswith("VmRSS:"):
                        kb = int(line.split()[1])
                        return f"{kb / 1024:.1f} MB"
            else:
                result = subprocess.run(
                    ["ps", "-o", "rss=", "-p", str(pid)],
                    capture_output=True, text=True,
                )
                if result.returncode == 0 and result.stdout.strip():
                    kb = int(result.stdout.strip())
                    return f"{kb / 1024:.1f} MB"
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# trio daemon logs
# ---------------------------------------------------------------------------

def _cmd_logs():
    """Show recent daemon logs, then tail for new output."""
    from trio.cron.daemon import TrioDaemon

    log_text = TrioDaemon.get_logs(lines=80)
    console.print(Panel(log_text, title="daemon.log (last 80 lines)", border_style="dim"))

    # Also show heartbeat log if present
    hb_log = _get_state_dir() / "heartbeat.log"
    if hb_log.exists():
        try:
            hb_lines = hb_log.read_text(encoding="utf-8", errors="replace").splitlines()
            if hb_lines:
                console.print()
                hb_tail = "\n".join(hb_lines[-20:])
                console.print(Panel(
                    hb_tail,
                    title="heartbeat.log (last 20 lines)",
                    border_style="dim",
                ))
        except OSError:
            pass

    console.print("\n[dim]Hint: watch the live log with: tail -f ~/.trio/daemon/daemon.log[/dim]")


# ---------------------------------------------------------------------------
# trio daemon install / uninstall (system service)
# ---------------------------------------------------------------------------

def _cmd_install():
    """Install as a system service for the current platform."""
    system = platform.system()
    if system == "Darwin":
        _install_launchd()
    elif system == "Linux":
        _install_systemd()
    elif system == "Windows":
        _install_windows()
    else:
        console.print(f"[red]Unsupported platform: {system}[/red]")


def _cmd_uninstall():
    """Remove the system service."""
    system = platform.system()
    if system == "Darwin":
        _uninstall_launchd()
    elif system == "Linux":
        _uninstall_systemd()
    elif system == "Windows":
        _uninstall_windows()
    else:
        console.print(f"[red]Unsupported platform: {system}[/red]")


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

def _cmd_help():
    console.print("[bold]trio daemon[/bold] -- manage background gateway service\n")
    console.print("  [cyan]trio daemon start[/cyan]      -- Start daemon in background")
    console.print("  [cyan]trio daemon stop[/cyan]       -- Stop running daemon")
    console.print("  [cyan]trio daemon restart[/cyan]    -- Restart daemon")
    console.print("  [cyan]trio daemon status[/cyan]     -- Show daemon status (PID, uptime, health)")
    console.print("  [cyan]trio daemon logs[/cyan]       -- Show recent daemon logs")
    console.print("  [cyan]trio daemon install[/cyan]    -- Install as system service (auto-start)")
    console.print("  [cyan]trio daemon uninstall[/cyan]  -- Remove system service")


# ═══════════════════════════════════════════════════════════════════════════
# macOS — LaunchAgent
# ═══════════════════════════════════════════════════════════════════════════

_LAUNCHD_LABEL = "ai.trio.daemon"
_LAUNCHD_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"


def _install_launchd():
    state_dir = _get_state_dir()
    python = _python_exe()

    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>-m</string>
        <string>trio.cron.daemon</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>{state_dir / 'launchd_stdout.log'}</string>
    <key>StandardErrorPath</key>
    <string>{state_dir / 'launchd_stderr.log'}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>{Path.home()}</string>
        <key>PATH</key>
        <string>{os.environ.get('PATH', '/usr/bin:/bin:/usr/local/bin')}</string>
    </dict>
    <key>ProcessType</key>
    <string>Background</string>
</dict>
</plist>"""

    _LAUNCHD_PLIST.parent.mkdir(parents=True, exist_ok=True)
    _LAUNCHD_PLIST.write_text(plist, encoding="utf-8")

    subprocess.run(["launchctl", "load", "-w", str(_LAUNCHD_PLIST)])
    console.print(f"[green]Daemon installed as LaunchAgent![/green]")
    console.print(f"  Plist: {_LAUNCHD_PLIST}")
    console.print("[dim]The daemon will auto-start on login and restart on crash.[/dim]")


def _uninstall_launchd():
    if _LAUNCHD_PLIST.exists():
        subprocess.run(["launchctl", "unload", str(_LAUNCHD_PLIST)])
        _LAUNCHD_PLIST.unlink()
        console.print("[green]LaunchAgent removed.[/green]")
    else:
        console.print("[yellow]No LaunchAgent installed.[/yellow]")


# ═══════════════════════════════════════════════════════════════════════════
# Linux — systemd user unit
# ═══════════════════════════════════════════════════════════════════════════

_SYSTEMD_SERVICE = "trio-daemon"
_SYSTEMD_PATH = (
    Path.home() / ".config" / "systemd" / "user" / f"{_SYSTEMD_SERVICE}.service"
)


def _install_systemd():
    python = _python_exe()

    unit = f"""\
[Unit]
Description=trio.ai Daemon (gateway + heartbeat + health monitor)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={python} -m trio.cron.daemon
ExecStop=/bin/kill -TERM $MAINPID
Restart=on-failure
RestartSec=10
TimeoutStopSec=30
WorkingDirectory={Path.home()}
Environment="HOME={Path.home()}"
Environment="PATH={os.environ.get('PATH', '/usr/bin:/bin:/usr/local/bin')}"

[Install]
WantedBy=default.target
"""

    _SYSTEMD_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SYSTEMD_PATH.write_text(unit, encoding="utf-8")

    subprocess.run(["systemctl", "--user", "daemon-reload"])
    subprocess.run(["systemctl", "--user", "enable", "--now", _SYSTEMD_SERVICE])

    # Enable linger so it survives logout
    user = os.environ.get("USER", "")
    if user:
        subprocess.run(["loginctl", "enable-linger", user])

    console.print(f"[green]Daemon installed as systemd user service![/green]")
    console.print(f"  Unit: {_SYSTEMD_PATH}")
    console.print("[dim]The daemon will auto-start on login and restart on failure.[/dim]")
    console.print(f"[dim]Manage with: systemctl --user {{start|stop|status}} {_SYSTEMD_SERVICE}[/dim]")


def _uninstall_systemd():
    if _SYSTEMD_PATH.exists():
        subprocess.run(["systemctl", "--user", "stop", _SYSTEMD_SERVICE])
        subprocess.run(["systemctl", "--user", "disable", _SYSTEMD_SERVICE])
        _SYSTEMD_PATH.unlink()
        subprocess.run(["systemctl", "--user", "daemon-reload"])
        console.print("[green]systemd service removed.[/green]")
    else:
        console.print("[yellow]No systemd service installed.[/yellow]")


# ═══════════════════════════════════════════════════════════════════════════
# Windows — Scheduled Task + Startup folder fallback
# ═══════════════════════════════════════════════════════════════════════════

_WIN_TASK_NAME = "TrioDaemon"


def _win_startup_dir() -> Path | None:
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        return None
    return (
        Path(appdata) / "Microsoft" / "Windows"
        / "Start Menu" / "Programs" / "Startup"
    )


def _install_windows():
    state_dir = _get_state_dir()
    pythonw = _pythonw_exe()

    # Create a .cmd wrapper script that uses pythonw for headless execution
    cmd_script = state_dir / "trio-daemon.cmd"
    cmd_content = f'@echo off\r\n"{pythonw}" -m trio.cron.daemon\r\n'
    cmd_script.write_text(cmd_content, encoding="utf-8")

    # Also create a .vbs wrapper for truly invisible startup
    vbs_script = state_dir / "trio-daemon.vbs"
    vbs_content = (
        f'Set WshShell = CreateObject("WScript.Shell")\r\n'
        f'WshShell.Run """{pythonw}"" -m trio.cron.daemon", 0, False\r\n'
    )
    vbs_script.write_text(vbs_content, encoding="utf-8")

    # Try schtasks (preferred — runs at logon, can restart on failure)
    result = subprocess.run(
        [
            "schtasks", "/Create",
            "/TN", _WIN_TASK_NAME,
            "/TR", f'"{pythonw}" -m trio.cron.daemon',
            "/SC", "ONLOGON",
            "/RL", "HIGHEST",
            "/F",
        ],
        capture_output=True, text=True,
    )

    if result.returncode == 0:
        console.print(f"[green]Daemon installed as Scheduled Task ({_WIN_TASK_NAME})![/green]")
        console.print("[dim]The daemon will auto-start on logon.[/dim]")
        console.print(f"[dim]Manage with: schtasks /Query /TN {_WIN_TASK_NAME}[/dim]")
        return

    # Fallback: copy VBS to Startup folder (invisible launch)
    startup = _win_startup_dir()
    if startup and startup.exists():
        dest = startup / "trio-daemon.vbs"
        shutil.copy2(vbs_script, dest)
        console.print(f"[green]Daemon installed in Startup folder![/green]")
        console.print(f"  Script: {dest}")
        console.print("[dim]The daemon will auto-start on logon.[/dim]")
        return

    console.print(
        "[red]Could not install as Scheduled Task or Startup item. "
        "You can manually run: trio daemon start[/red]"
    )


def _uninstall_windows():
    removed = False

    # Remove scheduled task
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", _WIN_TASK_NAME, "/F"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        console.print("[green]Scheduled Task removed.[/green]")
        removed = True

    # Remove from startup folder
    startup = _win_startup_dir()
    if startup:
        for name in ("trio-daemon.vbs", "trio-daemon.cmd"):
            script = startup / name
            if script.exists():
                script.unlink()
                console.print(f"[green]Startup script removed: {name}[/green]")
                removed = True

    # Clean up state dir scripts
    state_dir = _get_state_dir()
    for name in ("trio-daemon.cmd", "trio-daemon.vbs"):
        script = state_dir / name
        if script.exists():
            script.unlink()

    if not removed:
        console.print("[yellow]No system service was installed.[/yellow]")
