"""Human-in-the-loop approval system for dangerous agent actions.

Before shell commands, file writes, web requests, and other sensitive operations,
the agent pauses and asks the user for approval. Supports CLI prompts, Web UI
(via async event signaling), and auto-approve mode for daemon use.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import enum
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Approval Levels ──────────────────────────────────────────────────────────

class ApprovalLevel(enum.Enum):
    """How an action type should be handled by the approval system."""
    AUTO = "auto"          # No approval needed — execute immediately
    CONFIRM = "confirm"    # Show what will happen, ask y/n
    DENY = "deny"          # Always blocked — never execute


# ── Default tool → approval level mapping ────────────────────────────────────

DEFAULT_POLICY: dict[str, ApprovalLevel] = {
    # Dangerous — require confirmation
    "shell":        ApprovalLevel.CONFIRM,
    "file_ops":     ApprovalLevel.CONFIRM,   # file write/delete
    "browser":      ApprovalLevel.CONFIRM,   # web requests
    "email":        ApprovalLevel.CONFIRM,
    "delegate":     ApprovalLevel.CONFIRM,   # sub-agent delegation

    # Safe — auto-approve
    "web_search":   ApprovalLevel.AUTO,
    "math_solver":  ApprovalLevel.AUTO,
    "calendar":     ApprovalLevel.AUTO,
    "notes":        ApprovalLevel.AUTO,
    "screenshot":   ApprovalLevel.AUTO,
    "rag_search":   ApprovalLevel.AUTO,
    "rag_ingest":   ApprovalLevel.AUTO,
}


# ── Approval Request / Record ────────────────────────────────────────────────

@dataclass
class ApprovalRequest:
    """A pending approval request waiting for user response."""
    id: str
    action_type: str
    description: str
    details: dict[str, Any]
    timestamp: float
    event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    approved: bool | None = None        # None = pending, True/False = resolved

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "action_type": self.action_type,
            "description": self.description,
            "details": self.details,
            "timestamp": self.timestamp,
            "status": "pending" if self.approved is None else (
                "approved" if self.approved else "denied"
            ),
        }


@dataclass
class ApprovalRecord:
    """Historical record of an approval decision."""
    id: str
    action_type: str
    description: str
    approved: bool
    timestamp: float
    decided_at: float


# ── Approval Policy ──────────────────────────────────────────────────────────

class ApprovalPolicy:
    """Maps action types (tool names) to approval levels.

    Reads overrides from config["approvals"]:
        - auto_approve_types: list[str]  — tool names that skip approval
        - deny_types: list[str]          — tool names that are always blocked
    Anything not overridden falls back to DEFAULT_POLICY, then CONFIRM.
    """

    def __init__(self, config: dict | None = None):
        self._policy = dict(DEFAULT_POLICY)
        if config:
            self._apply_config(config)

    def _apply_config(self, config: dict) -> None:
        approvals_cfg = config.get("approvals", {})
        for name in approvals_cfg.get("auto_approve_types", []):
            self._policy[name] = ApprovalLevel.AUTO
        for name in approvals_cfg.get("deny_types", []):
            self._policy[name] = ApprovalLevel.DENY

    def get_level(self, action_type: str) -> ApprovalLevel:
        """Return the approval level for a tool / action type."""
        return self._policy.get(action_type, ApprovalLevel.CONFIRM)

    def set_level(self, action_type: str, level: ApprovalLevel) -> None:
        self._policy[action_type] = level

    def all_levels(self) -> dict[str, str]:
        """Return a serialisable copy of the full policy."""
        return {k: v.value for k, v in self._policy.items()}


# ── Approval Manager ─────────────────────────────────────────────────────────

class ApprovalManager:
    """Manages approval requests across CLI and Web UI modes.

    Parameters
    ----------
    policy : ApprovalPolicy
        Defines which actions need approval.
    auto_approve : bool
        When True every action is auto-approved (daemon / automated mode).
    mode : str
        "cli" — prompt in terminal; "web" — wait for Web UI response via event.
    config : dict | None
        Raw config dict; ``config["approvals"]["enabled"]`` can disable the
        entire system (equivalent to auto_approve=True).
    """

    def __init__(
        self,
        policy: ApprovalPolicy | None = None,
        auto_approve: bool = False,
        mode: str = "cli",
        config: dict | None = None,
    ):
        cfg = (config or {}).get("approvals", {})
        enabled = cfg.get("enabled", True)

        self.policy = policy or ApprovalPolicy(config)
        self.auto_approve = auto_approve or not enabled
        self.mode = mode

        # Pending requests keyed by request id (for Web UI async flow)
        self._pending: dict[str, ApprovalRequest] = {}
        # History of all decisions
        self._history: list[ApprovalRecord] = []

    # ── Public API ───────────────────────────────────────────────────────

    async def request_approval(
        self,
        action_type: str,
        description: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        """Request approval for an action. Returns True if approved.

        Behaviour depends on the policy level for *action_type*:
            AUTO   → always True
            DENY   → always False
            CONFIRM → prompt user (CLI) or wait for web response
        """
        level = self.policy.get_level(action_type)

        # Fast paths
        if level == ApprovalLevel.AUTO or self.auto_approve:
            self._record(action_type, description, approved=True)
            return True

        if level == ApprovalLevel.DENY:
            logger.warning("Action DENIED by policy: %s — %s", action_type, description)
            self._record(action_type, description, approved=False)
            return False

        # CONFIRM path
        if self.mode == "cli":
            return await self._prompt_cli(action_type, description, details or {})
        else:
            return await self._prompt_web(action_type, description, details or {})

    def get_pending(self) -> list[dict]:
        """Return all pending approval requests (for Web UI polling)."""
        return [r.to_dict() for r in self._pending.values() if r.approved is None]

    def respond(self, request_id: str, approved: bool) -> bool:
        """Resolve a pending web approval request. Returns False if not found."""
        req = self._pending.get(request_id)
        if req is None or req.approved is not None:
            return False
        req.approved = approved
        req.event.set()
        self._record(req.action_type, req.description, approved=approved)
        logger.info("Approval %s: %s — %s", "granted" if approved else "denied",
                     req.action_type, req.description)
        return True

    def get_history(self, limit: int = 50) -> list[dict]:
        """Return recent approval history."""
        records = self._history[-limit:]
        return [
            {
                "id": r.id,
                "action_type": r.action_type,
                "description": r.description,
                "approved": r.approved,
                "timestamp": r.timestamp,
                "decided_at": r.decided_at,
            }
            for r in records
        ]

    # ── Internal ─────────────────────────────────────────────────────────

    def _record(self, action_type: str, description: str, approved: bool) -> None:
        now = time.time()
        self._history.append(ApprovalRecord(
            id=uuid.uuid4().hex[:12],
            action_type=action_type,
            description=description,
            approved=approved,
            timestamp=now,
            decided_at=now,
        ))

    async def _prompt_cli(
        self, action_type: str, description: str, details: dict
    ) -> bool:
        """Prompt the user in the terminal and wait for y/n."""
        print()
        print("=" * 60)
        print(f"  APPROVAL REQUIRED — {action_type}")
        print("=" * 60)
        print(f"  Action:  {description}")
        if details:
            for key, value in details.items():
                val_str = str(value)
                if len(val_str) > 200:
                    val_str = val_str[:200] + "..."
                print(f"  {key}: {val_str}")
        print("-" * 60)

        # Run blocking input() in a thread so we don't block the event loop
        loop = asyncio.get_running_loop()
        try:
            answer = await loop.run_in_executor(
                None, lambda: input("  Approve? [y/n]: ").strip().lower()
            )
        except (EOFError, KeyboardInterrupt):
            answer = "n"

        approved = answer in ("y", "yes")
        self._record(action_type, description, approved=approved)
        status = "APPROVED" if approved else "DENIED"
        print(f"  → {status}")
        print("=" * 60)
        print()
        return approved

    async def _prompt_web(
        self, action_type: str, description: str, details: dict
    ) -> bool:
        """Create a pending request and wait for the Web UI to respond."""
        req = ApprovalRequest(
            id=uuid.uuid4().hex[:12],
            action_type=action_type,
            description=description,
            details=details,
            timestamp=time.time(),
        )
        self._pending[req.id] = req
        logger.info("Approval request created [%s]: %s — %s", req.id, action_type, description)

        # Wait for the Web UI to call respond()
        try:
            await asyncio.wait_for(req.event.wait(), timeout=300)  # 5 min timeout
        except asyncio.TimeoutError:
            logger.warning("Approval request %s timed out", req.id)
            req.approved = False
            self._record(action_type, description, approved=False)
        finally:
            self._pending.pop(req.id, None)

        return req.approved is True
