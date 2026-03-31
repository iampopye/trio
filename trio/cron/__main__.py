"""Allow running the daemon directly: ``python -m trio.cron.daemon``."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from trio.cron.daemon import run_daemon_process

if __name__ == "__main__":
    run_daemon_process()
