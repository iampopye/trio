"""Allow running the daemon directly: ``python -m trio.cron.daemon``."""

from trio.cron.daemon import run_daemon_process

if __name__ == "__main__":
    run_daemon_process()
