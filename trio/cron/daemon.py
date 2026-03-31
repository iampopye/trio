"""Production-grade daemon for trio.ai — runs gateway as a background service.

Handles PID management, structured logging, health monitoring with auto-restart,
and cross-platform signal handling (SIGTERM/SIGINT on Unix, CTRL_C_EVENT on Windows).
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import json
import logging
import os
import platform
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trio.core.config import get_trio_dir, load_config, get_agent_defaults

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DAEMON_DIR: Path | None = None


def _daemon_dir() -> Path:
    global _DAEMON_DIR
    if _DAEMON_DIR is None:
        _DAEMON_DIR = get_trio_dir() / "daemon"
        _DAEMON_DIR.mkdir(parents=True, exist_ok=True)
    return _DAEMON_DIR


def _pid_path() -> Path:
    return _daemon_dir() / "daemon.pid"


def _log_path() -> Path:
    return _daemon_dir() / "daemon.log"


def _status_path() -> Path:
    return _daemon_dir() / "status.json"


def _heartbeat_log_path() -> Path:
    return _daemon_dir() / "heartbeat.log"


# ---------------------------------------------------------------------------
# TrioDaemon
# ---------------------------------------------------------------------------


class TrioDaemon:
    """Production daemon that runs the trio gateway as a background service.

    Responsibilities:
      - Start the full gateway (channels + agent loop)
      - Run the heartbeat scheduler
      - Periodically health-check all subsystems and auto-restart crashed ones
      - Write a PID file so external tools can manage the process
      - Write structured status to ``~/.trio/daemon/status.json``
    """

    HEALTH_CHECK_INTERVAL = 60  # seconds

    def __init__(self, config: dict | None = None):
        self.config = config or load_config()
        self._started_at: float | None = None

        # Core components — created in ``start``
        self._bus: Any = None
        self._sessions: Any = None
        self._memory: Any = None
        self._tools: Any = None
        self._provider: Any = None
        self._agent: Any = None
        self._channel_manager: Any = None
        self._heartbeat_daemon: Any = None
        self._mcp_manager: Any = None

        # Asyncio tasks for long-running coroutines
        self._agent_task: asyncio.Task | None = None
        self._channel_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._health_task: asyncio.Task | None = None

        self._running = False
        self._shutdown_event: asyncio.Event | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the daemon — gateway + heartbeat + health monitor."""
        self._running = True
        self._started_at = time.time()
        self._shutdown_event = asyncio.Event()

        self._write_pid()
        self._setup_logging()
        self._install_signal_handlers()

        logger.info("=" * 60)
        logger.info("trio daemon starting  (pid=%d)", os.getpid())
        logger.info("=" * 60)

        try:
            await self._init_core()
            await self._launch_tasks()

            # Write initial status
            self._write_status("running")

            # Block until shutdown is requested
            await self._shutdown_event.wait()
        except Exception:
            logger.exception("Fatal error in daemon — shutting down")
        finally:
            await self._shutdown()

    # ------------------------------------------------------------------
    # Initialization helpers
    # ------------------------------------------------------------------

    async def _init_core(self) -> None:
        """Initialize all core subsystems (mirrors ``gateway.run_gateway``)."""
        from trio.core.bus import MessageBus
        from trio.core.loop import AgentLoop
        from trio.core.memory import MemoryStore
        from trio.core.session import SessionManager
        from trio.channels.base import ChannelManager
        from trio.providers.base import register_all_providers, ProviderRegistry
        from trio.tools.base import ToolRegistry

        config = self.config
        defaults = get_agent_defaults(config)

        # Provider
        register_all_providers()
        provider_name = defaults.get("provider", "trio")
        provider_config = config.get("providers", {}).get(provider_name, {})
        provider_config["provider_name"] = provider_name
        self._provider = ProviderRegistry.create(provider_name, provider_config)

        # Core services
        self._bus = MessageBus()
        self._sessions = SessionManager()
        self._memory = MemoryStore()
        self._tools = ToolRegistry()
        self._tools.register_builtins(config)

        # MCP tools
        mcp_config = config.get("tools", {}).get("mcpServers", {})
        if mcp_config:
            from trio.tools.mcp_client import MCPManager
            self._mcp_manager = MCPManager()
            mcp_tools = await self._mcp_manager.start_servers(mcp_config)
            for tool in mcp_tools:
                self._tools.register(tool)

        # Agent loop
        self._agent = AgentLoop(
            bus=self._bus,
            sessions=self._sessions,
            memory=self._memory,
            provider=self._provider,
            tools=self._tools,
            config=config,
        )

        # Channel manager
        self._channel_manager = ChannelManager(self._bus)
        self._register_channels()

        # Heartbeat
        if config.get("heartbeat", {}).get("enabled"):
            from trio.channels.heartbeat_channel import HeartbeatChannel
            from trio.cron.heartbeat import HeartbeatDaemon

            hb_channel = HeartbeatChannel(bus=self._bus, config=config)
            self._channel_manager.register(hb_channel)
            self._heartbeat_daemon = HeartbeatDaemon(
                bus=self._bus,
                config=config,
                log_path=_heartbeat_log_path(),
            )

        logger.info("Core subsystems initialized")

    def _register_channels(self) -> None:
        """Register all enabled channels (mirrors gateway.py channel setup)."""
        channels_config = self.config.get("channels", {})
        bus = self._bus
        cm = self._channel_manager

        channel_defs: list[tuple[str, str, str]] = [
            ("discord", "trio.channels.discord_channel", "DiscordChannel"),
            ("telegram", "trio.channels.telegram_channel", "TelegramChannel"),
            ("signal", "trio.channels.signal_channel", "SignalChannel"),
            ("whatsapp", "trio.channels.whatsapp_channel", "WhatsAppChannel"),
            ("slack", "trio.channels.slack_channel", "SlackChannel"),
            ("teams", "trio.channels.teams_channel", "TeamsChannel"),
            ("google_chat", "trio.channels.google_chat_channel", "GoogleChatChannel"),
            ("imessage", "trio.channels.imessage_channel", "IMessageChannel"),
        ]

        for name, module_path, class_name in channel_defs:
            cfg = channels_config.get(name, {})
            if not cfg.get("enabled"):
                continue
            try:
                import importlib
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name)
                channel = cls(bus=bus, config=cfg)
                cm.register(channel)
            except (ImportError, RuntimeError, AttributeError) as exc:
                logger.warning("Channel '%s' unavailable: %s", name, exc)

    # ------------------------------------------------------------------
    # Task management
    # ------------------------------------------------------------------

    async def _launch_tasks(self) -> None:
        """Create asyncio tasks for all long-running subsystems."""
        self._agent_task = asyncio.create_task(
            self._supervised(self._agent.run(), "agent_loop"),
        )
        self._channel_task = asyncio.create_task(
            self._supervised(self._channel_manager.start_all(), "channel_manager"),
        )
        if self._heartbeat_daemon:
            self._heartbeat_task = asyncio.create_task(
                self._supervised(self._heartbeat_daemon.start(), "heartbeat"),
            )
        self._health_task = asyncio.create_task(self._health_loop())

        logger.info("All tasks launched")

    async def _supervised(self, coro, name: str) -> None:
        """Run *coro* and log if it exits unexpectedly."""
        try:
            await coro
        except asyncio.CancelledError:
            logger.info("Task '%s' cancelled", name)
        except Exception:
            logger.exception("Task '%s' crashed", name)

    # ------------------------------------------------------------------
    # Health monitor
    # ------------------------------------------------------------------

    async def _health_loop(self) -> None:
        """Periodic health check — restarts crashed components."""
        while self._running:
            try:
                await asyncio.sleep(self.HEALTH_CHECK_INTERVAL)
                await self._health_check()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Health check error")

    async def _health_check(self) -> None:
        """Inspect each subsystem, attempt recovery, and log status."""
        report: dict[str, str] = {}

        # 1. Agent loop
        if self._agent_task and self._agent_task.done():
            logger.warning("Agent loop died — restarting")
            self._agent_task = asyncio.create_task(
                self._supervised(self._agent.run(), "agent_loop"),
            )
            report["agent_loop"] = "restarted"
        else:
            report["agent_loop"] = "ok"

        # 2. Channel manager
        if self._channel_task and self._channel_task.done():
            logger.warning("Channel manager died — restarting")
            self._channel_task = asyncio.create_task(
                self._supervised(self._channel_manager.start_all(), "channel_manager"),
            )
            report["channel_manager"] = "restarted"
        else:
            report["channel_manager"] = "ok"

        # 3. Heartbeat
        if self._heartbeat_daemon:
            if self._heartbeat_task and self._heartbeat_task.done():
                logger.warning("Heartbeat died — restarting")
                self._heartbeat_task = asyncio.create_task(
                    self._supervised(self._heartbeat_daemon.start(), "heartbeat"),
                )
                report["heartbeat"] = "restarted"
            else:
                report["heartbeat"] = "ok"

        # 4. Provider responsiveness (best-effort)
        try:
            if hasattr(self._provider, "ping"):
                await asyncio.wait_for(self._provider.ping(), timeout=10)
            report["provider"] = "ok"
        except Exception as exc:
            report["provider"] = f"degraded ({exc})"

        # 5. Memory usage
        try:
            import resource  # Unix only
            mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            report["memory_mb"] = f"{mem_mb:.1f}"
        except ImportError:
            # Windows fallback
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

                counters = PROCESS_MEMORY_COUNTERS()
                counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
                ctypes.windll.psapi.GetProcessMemoryInfo(
                    ctypes.windll.kernel32.GetCurrentProcess(),
                    ctypes.byref(counters),
                    counters.cb,
                )
                mem_mb = counters.WorkingSetSize / (1024 * 1024)
                report["memory_mb"] = f"{mem_mb:.1f}"
            except Exception:
                report["memory_mb"] = "unknown"

        self._write_status("running", health=report)
        logger.info("Health check: %s", json.dumps(report))

    # ------------------------------------------------------------------
    # Signal handling & shutdown
    # ------------------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        """Register OS signals for graceful shutdown."""
        loop = asyncio.get_running_loop()

        if sys.platform != "win32":
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, self._request_shutdown)
        else:
            # Windows: signal module works for SIGINT in the main thread
            signal.signal(signal.SIGINT, lambda *_: self._request_shutdown())
            signal.signal(signal.SIGTERM, lambda *_: self._request_shutdown())

    def _request_shutdown(self) -> None:
        logger.info("Shutdown signal received")
        self._running = False
        if self._shutdown_event:
            self._shutdown_event.set()

    async def _shutdown(self) -> None:
        """Graceful shutdown — stop components in reverse order."""
        logger.info("Shutting down daemon...")

        # Cancel tasks
        for task in (self._health_task, self._heartbeat_task,
                     self._channel_task, self._agent_task):
            if task and not task.done():
                task.cancel()

        # Wait briefly for clean cancellation
        pending = [t for t in (self._health_task, self._heartbeat_task,
                               self._channel_task, self._agent_task)
                   if t and not t.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        # Stop components
        if self._agent:
            try:
                self._agent.stop()
            except Exception:
                logger.exception("Error stopping agent")

        if self._channel_manager:
            try:
                await self._channel_manager.stop_all()
            except Exception:
                logger.exception("Error stopping channels")

        if self._heartbeat_daemon:
            try:
                await self._heartbeat_daemon.stop()
            except Exception:
                logger.exception("Error stopping heartbeat")

        if self._provider:
            try:
                await self._provider.close()
            except Exception:
                logger.exception("Error closing provider")

        if self._mcp_manager:
            try:
                await self._mcp_manager.stop_all()
            except Exception:
                logger.exception("Error stopping MCP")

        self._write_status("stopped")
        self._cleanup()
        logger.info("Daemon stopped cleanly")

    # ------------------------------------------------------------------
    # PID file management
    # ------------------------------------------------------------------

    def _write_pid(self) -> None:
        path = _pid_path()
        path.write_text(str(os.getpid()), encoding="utf-8")
        logger.debug("PID file written: %s (pid=%d)", path, os.getpid())

    def _cleanup(self) -> None:
        path = _pid_path()
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Status file
    # ------------------------------------------------------------------

    def _write_status(self, state: str, health: dict | None = None) -> None:
        channels = []
        if self._channel_manager:
            channels = list(getattr(self._channel_manager, "_channels", {}).keys())

        data = {
            "state": state,
            "pid": os.getpid(),
            "started_at": self._started_at,
            "uptime_seconds": (time.time() - self._started_at) if self._started_at else 0,
            "channels": channels,
            "last_health_check": datetime.now(timezone.utc).isoformat(),
        }
        if health:
            data["health"] = health

        try:
            _status_path().write_text(
                json.dumps(data, indent=2), encoding="utf-8",
            )
        except OSError:
            logger.warning("Could not write status file")

    # ------------------------------------------------------------------
    # Logging setup
    # ------------------------------------------------------------------

    def _setup_logging(self) -> None:
        log_file = _log_path()
        root = logging.getLogger()
        root.setLevel(logging.INFO)

        # File handler — append
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        ))
        root.addHandler(fh)

        # Also keep stderr for debugging when run in foreground
        if sys.stderr and sys.stderr.writable():
            sh = logging.StreamHandler(sys.stderr)
            sh.setLevel(logging.WARNING)
            sh.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s: %(message)s",
            ))
            root.addHandler(sh)

    # ------------------------------------------------------------------
    # Static helpers (used by CLI)
    # ------------------------------------------------------------------

    @staticmethod
    def is_running() -> tuple[bool, int | None]:
        """Check if a trio daemon is running. Returns ``(running, pid)``."""
        pid_file = _pid_path()
        if not pid_file.exists():
            return False, None

        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            return False, None

        if _pid_alive(pid):
            return True, pid

        # Stale PID file — clean up
        try:
            pid_file.unlink()
        except OSError:
            pass
        return False, None

    @staticmethod
    def stop() -> bool:
        """Stop the running daemon. Returns True if it was stopped."""
        running, pid = TrioDaemon.is_running()
        if not running or pid is None:
            return False

        # Send termination signal
        if sys.platform == "win32":
            # Windows: use taskkill (handles both console and pythonw)
            import subprocess
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True,
            )
        else:
            os.kill(pid, signal.SIGTERM)

        # Wait for process to exit (up to 15 seconds)
        for _ in range(30):
            if not _pid_alive(pid):
                # Clean up PID file if still there
                try:
                    _pid_path().unlink(missing_ok=True)
                except OSError:
                    pass
                return True
            time.sleep(0.5)

        # Force kill after timeout
        if _pid_alive(pid):
            if sys.platform == "win32":
                import subprocess
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    capture_output=True,
                )
            else:
                os.kill(pid, signal.SIGKILL)
            time.sleep(1)

        try:
            _pid_path().unlink(missing_ok=True)
        except OSError:
            pass
        return True

    @staticmethod
    def get_status() -> dict | None:
        """Read the daemon status.json file."""
        path = _status_path()
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def get_logs(lines: int = 50) -> str:
        """Read last *lines* lines from the daemon log."""
        log_file = _log_path()
        if not log_file.exists():
            return "(no log file yet)"
        try:
            all_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(all_lines[-lines:])
        except OSError:
            return "(could not read log file)"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    """Check whether a process with *pid* is alive (cross-platform)."""
    if sys.platform == "win32":
        # Use OpenProcess with PROCESS_QUERY_LIMITED_INFORMATION
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid,
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # process exists but we can't signal it


def run_daemon_process() -> None:
    """Entry point for starting the daemon in-process (called by CLI)."""
    config = load_config()
    daemon = TrioDaemon(config)
    asyncio.run(daemon.start())


if __name__ == "__main__":
    run_daemon_process()
