"""
Persistent access control store for trio.

Stores approved/pending users in JSON file, shared across all channels.
Thread-safe for mixed sync/async handlers.
"""

import json
import os
import time
import threading
import logging
from pathlib import Path

from trio.core.config import get_trio_dir

logger = logging.getLogger(__name__)

_FILE = str(get_trio_dir() / "approved_users.json")
_lock = threading.Lock()

_PLATFORMS = ("telegram", "signal", "discord", "whatsapp", "slack", "teams", "google_chat", "imessage")

_data = {p: {} for p in _PLATFORMS}
_data["pending"] = {p: {} for p in _PLATFORMS}


def _default_data():
    d = {p: {} for p in _PLATFORMS}
    d["pending"] = {p: {} for p in _PLATFORMS}
    return d


def load():
    """Load access data from disk. Creates file if missing."""
    global _data
    with _lock:
        if os.path.exists(_FILE):
            try:
                with open(_FILE, "r", encoding="utf-8") as f:
                    _data = json.load(f)
                for key in _PLATFORMS:
                    if key not in _data:
                        _data[key] = {}
                if "pending" not in _data:
                    _data["pending"] = {p: {} for p in _PLATFORMS}
                for key in _PLATFORMS:
                    if key not in _data["pending"]:
                        _data["pending"][key] = {}
                logger.info(f"Loaded access store: {sum(len(v) for k, v in _data.items() if k != 'pending')} users")
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Failed to load access store: {e}")
                _data = _default_data()
        else:
            _data = _default_data()
            _save_locked()


def _save_locked():
    try:
        with open(_FILE, "w", encoding="utf-8") as f:
            json.dump(_data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        logger.error(f"Failed to save access store: {e}")


def _save():
    with _lock:
        _save_locked()


# -- Query --

def is_approved(platform, user_id):
    with _lock:
        return str(user_id) in _data.get(platform, {})


def get_approved(platform):
    with _lock:
        return dict(_data.get(platform, {}))


def get_pending(platform):
    with _lock:
        return dict(_data.get("pending", {}).get(platform, {}))


def is_pending(platform, user_id):
    with _lock:
        return str(user_id) in _data.get("pending", {}).get(platform, {})


# -- Mutations --

def approve_user(platform, user_id, info=None):
    uid = str(user_id)
    with _lock:
        if info is None:
            info = _data.get("pending", {}).get(platform, {}).pop(uid, {})
        else:
            _data.get("pending", {}).get(platform, {}).pop(uid, None)
        info["approved_at"] = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        _data[platform][uid] = info
        _save_locked()
    logger.info(f"Approved {platform} user {uid}")


def revoke_user(platform, user_id):
    uid = str(user_id)
    with _lock:
        removed = _data.get(platform, {}).pop(uid, None)
        _save_locked()
    if removed:
        logger.info(f"Revoked {platform} user {uid}")
    return removed is not None


def add_pending(platform, user_id, info):
    uid = str(user_id)
    with _lock:
        info["request_time"] = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        _data["pending"][platform][uid] = info
        _save_locked()


def update_pending(platform, user_id, updates):
    uid = str(user_id)
    with _lock:
        pending = _data.get("pending", {}).get(platform, {})
        if uid in pending:
            pending[uid].update(updates)
            _save_locked()


def remove_pending(platform, user_id):
    uid = str(user_id)
    with _lock:
        _data.get("pending", {}).get(platform, {}).pop(uid, None)
        _save_locked()


# Load on import
load()
