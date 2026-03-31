"""DM pairing security — code-based approval for unknown senders."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import json
import logging
import secrets
import time
import threading
from pathlib import Path

from trio.core.config import get_trio_dir

logger = logging.getLogger(__name__)

# Human-friendly alphabet (no ambiguous chars: 0/O/1/I removed)
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8
_PAIRING_TTL = 3600  # 1 hour
_MAX_PENDING = 10

_lock = threading.Lock()


def _get_pairing_path(channel: str) -> Path:
    p = get_trio_dir() / "pairing"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{channel}_pending.json"


def _get_allowlist_path(channel: str) -> Path:
    p = get_trio_dir() / "pairing"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{channel}_allowed.json"


def _generate_code() -> str:
    """Generate human-friendly pairing code."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Public API ────────────────────────────────────────────────────────────────


def is_allowed(channel: str, user_id: str) -> bool:
    """Check if a user is in the channel's allowlist."""
    with _lock:
        data = _load_json(_get_allowlist_path(channel))
        allowed = data.get("allowed", {})
        return str(user_id) in allowed


def get_dm_policy(config: dict, channel: str) -> str:
    """Get the DM policy for a channel. Default: 'pairing'."""
    return config.get("channels", {}).get(channel, {}).get("dm_policy", "pairing")


def create_pairing_request(channel: str, user_id: str, user_info: dict | None = None) -> str:
    """Create a pairing request for an unknown sender. Returns the pairing code."""
    with _lock:
        path = _get_pairing_path(channel)
        data = _load_json(path)
        pending = data.get("pending", {})

        # Prune expired
        now = time.time()
        pending = {k: v for k, v in pending.items()
                   if now - v.get("created_at", 0) < _PAIRING_TTL}

        # Check if user already has a pending request
        for code, req in pending.items():
            if req.get("user_id") == str(user_id):
                req["last_seen"] = now
                data["pending"] = pending
                _save_json(path, data)
                return code

        # Prune oldest if at max
        if len(pending) >= _MAX_PENDING:
            oldest_code = min(pending, key=lambda k: pending[k].get("created_at", 0))
            del pending[oldest_code]

        # Generate new code
        code = _generate_code()
        while code in pending:
            code = _generate_code()

        pending[code] = {
            "user_id": str(user_id),
            "channel": channel,
            "created_at": now,
            "last_seen": now,
            "info": user_info or {},
        }

        data["pending"] = pending
        _save_json(path, data)

        logger.info(f"Pairing request created for {channel}:{user_id} → code {code}")
        return code


def approve_pairing(channel: str, code: str) -> dict | None:
    """Approve a pairing request by code. Returns the request info or None if not found."""
    code = code.upper().strip()

    with _lock:
        # Find and remove from pending
        path = _get_pairing_path(channel)
        data = _load_json(path)
        pending = data.get("pending", {})

        req = pending.pop(code, None)
        if req is None:
            # Try case-insensitive search
            for k, v in list(pending.items()):
                if k.upper() == code:
                    req = pending.pop(k)
                    break

        if req is None:
            return None

        data["pending"] = pending
        _save_json(path, data)

        # Add to allowlist
        user_id = req.get("user_id", "")
        allow_path = _get_allowlist_path(channel)
        allow_data = _load_json(allow_path)
        allowed = allow_data.get("allowed", {})

        allowed[user_id] = {
            "approved_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
            "info": req.get("info", {}),
        }

        allow_data["allowed"] = allowed
        _save_json(allow_path, allow_data)

        logger.info(f"Approved pairing for {channel}:{user_id}")
        return req


def revoke_pairing(channel: str, user_id: str) -> bool:
    """Remove a user from the allowlist."""
    with _lock:
        path = _get_allowlist_path(channel)
        data = _load_json(path)
        allowed = data.get("allowed", {})

        if str(user_id) in allowed:
            del allowed[str(user_id)]
            data["allowed"] = allowed
            _save_json(path, data)
            logger.info(f"Revoked pairing for {channel}:{user_id}")
            return True
        return False


def list_pending(channel: str) -> list[dict]:
    """List pending pairing requests for a channel."""
    with _lock:
        data = _load_json(_get_pairing_path(channel))
        pending = data.get("pending", {})

        now = time.time()
        results = []
        for code, req in pending.items():
            if now - req.get("created_at", 0) < _PAIRING_TTL:
                results.append({
                    "code": code,
                    "user_id": req.get("user_id"),
                    "channel": channel,
                    "created_at": req.get("created_at"),
                    "age_minutes": int((now - req.get("created_at", now)) / 60),
                })
        return results


def list_allowed(channel: str) -> list[dict]:
    """List approved users for a channel."""
    with _lock:
        data = _load_json(_get_allowlist_path(channel))
        allowed = data.get("allowed", {})
        return [
            {"user_id": uid, "approved_at": info.get("approved_at", "?")}
            for uid, info in allowed.items()
        ]


def get_pairing_message(code: str) -> str:
    """Generate the message to send to an unknown DM sender."""
    return (
        "trio.ai: access not configured.\n\n"
        f"Pairing code: **{code}**\n\n"
        "Ask the bot owner to approve with:\n"
        f"  `trio pairing approve <channel> {code}`"
    )
