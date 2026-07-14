"""Command package — importing this imports every category module so their
@command decorators run and populate the REGISTRY (import side effect).

Adding a command in a later phase = adding a decorated function inside one of
these already-imported category modules; no wiring change anywhere.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

from triobot.cli.slash.commands import (  # noqa: F401
    agents_tools,
    dev_workflow,
    model_provider,
    session_context,
    system_config,
    triobot_native,
)
