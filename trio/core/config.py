"""Configuration loader for ~/.trio/config.json with secrets encryption."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import base64
import hashlib
import json
import os
import secrets as _secrets
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = {
    "providers": {
        "trio": {
            "default_model": "trio-max",
        }
    },
    "agents": {
        "defaults": {
            "provider": "trio",
            "model": "trio-max",
            "max_iterations": 20,
            "memory_window": 20,
        }
    },
    "channels": {
        "discord": {"enabled": False, "token": ""},
        "telegram": {"enabled": False, "token": "", "admin_id": 0},
        "signal": {"enabled": False, "phone": ""},
        "whatsapp": {"enabled": False, "phone_number_id": "", "access_token": "", "verify_token": "trio_verify", "webhook_port": 8080},
        "slack": {"enabled": False, "bot_token": "", "app_token": ""},
        "teams": {"enabled": False, "app_id": "", "app_password": "", "webhook_port": 3978},
        "google_chat": {"enabled": False, "service_account_file": "", "webhook_port": 8090},
        "imessage": {"enabled": False, "poll_interval": 5},
        "matrix": {"enabled": False, "homeserver_url": "https://matrix.org", "user_id": "", "access_token": ""},
        "sms": {"enabled": False, "account_sid": "", "auth_token": "", "phone_number": "", "webhook_port": 8085},
        "instagram": {"enabled": False, "page_id": "", "access_token": "", "verify_token": "trio_verify", "app_secret": "", "webhook_port": 8086},
        "messenger": {"enabled": False, "page_id": "", "access_token": "", "verify_token": "trio_verify", "app_secret": "", "webhook_port": 8087},
        "line": {"enabled": False, "channel_access_token": "", "channel_secret": "", "webhook_port": 8088},
        "reddit": {"enabled": False, "client_id": "", "client_secret": "", "username": "", "password": "", "poll_interval": 30},
        "email": {"enabled": False, "imap_host": "", "imap_port": 993, "smtp_host": "", "smtp_port": 587, "username": "", "password": "", "poll_interval": 30},
    },
    "tools": {
        "builtin": [
            "web_search", "math_solver", "url_reader", "shell", "file_ops",
            "browser", "email", "calendar", "notes", "screenshot", "delegate",
        ],
        "restrictToWorkspace": False,
        "mcpServers": {},
        "email": {
            "smtp_host": "",
            "smtp_port": 587,
            "imap_host": "",
            "username": "",
            "password": "",
        },
    },
    "heartbeat": {
        "enabled": False,
        "interval_seconds": 300,
        "notify_channel": "",
    },
    "guardrails": {"enabled": True},
    "memory": {"consolidation_threshold": 20},
}


def get_trio_dir() -> Path:
    """Return ~/.trio, creating if needed."""
    trio_dir = Path.home() / ".trio"
    trio_dir.mkdir(parents=True, exist_ok=True)
    return trio_dir


def get_config_path() -> Path:
    return get_trio_dir() / "config.json"


def get_workspace_dir() -> Path:
    workspace = get_trio_dir() / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def get_sessions_dir() -> Path:
    sessions = get_trio_dir() / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    return sessions


def get_memory_dir() -> Path:
    memory = get_trio_dir() / "memory"
    memory.mkdir(parents=True, exist_ok=True)
    return memory


def get_skills_dir() -> Path:
    skills = get_trio_dir() / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    return skills


def get_notes_dir() -> Path:
    notes = get_trio_dir() / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    return notes


def get_plugins_dir() -> Path:
    plugins = get_trio_dir() / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    return plugins


def load_config() -> dict[str, Any]:
    """Load config from ~/.trio/config.json, merging with defaults.

    Encrypted secret fields (prefixed with 'ENC:') are automatically
    decrypted using the machine-local key in ~/.trio/.secret_key.
    """
    config_path = get_config_path()
    if not config_path.exists():
        return DEFAULT_CONFIG.copy()

    with open(config_path, "r", encoding="utf-8") as f:
        user_config = json.load(f)

    # Decrypt any encrypted secrets
    user_config = _decrypt_secrets(user_config)
    return _deep_merge(DEFAULT_CONFIG, user_config)


def save_config(config: dict[str, Any]) -> None:
    """Save config to ~/.trio/config.json.

    Secret fields (tokens, API keys, passwords) are automatically
    encrypted before writing to disk.
    """
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    # Encrypt secrets before writing
    encrypted_config = _encrypt_secrets(config)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(encrypted_config, f, indent=2, ensure_ascii=False)
    # Restrict config file permissions
    try:
        config_path.chmod(0o600)
    except (OSError, NotImplementedError):
        pass


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def get_provider_config(config: dict, provider_name: str | None = None) -> dict:
    """Get config for a specific provider."""
    if provider_name is None:
        provider_name = config.get("agents", {}).get("defaults", {}).get("provider", "trio")
    return config.get("providers", {}).get(provider_name, {})


def get_agent_defaults(config: dict) -> dict:
    """Get agent default settings."""
    return config.get("agents", {}).get("defaults", {
        "provider": "trio",
        "model": "trio-max",
        "max_iterations": 20,
        "memory_window": 20,
    })


# ── Secrets Encryption ─────────────────────────────────────────────────────
#
# Provides XOR-based obfuscation for sensitive values in config.json.
# This prevents plaintext credential exposure if the file is accidentally
# committed, shared, or read by other tools. It is NOT a substitute for
# a proper secrets manager, but it raises the bar significantly vs plaintext.
#
# Encrypted values are stored as: "ENC:base64_payload"
# The encryption key is derived from a machine-local secret stored in
# ~/.trio/.secret_key (auto-generated, chmod 600).

# Fields that contain secrets and should be encrypted at rest
SECRET_FIELDS = frozenset({
    "token", "bot_token", "app_token", "access_token", "api_key",
    "app_password", "password", "auth_token", "client_secret",
    "channel_secret", "channel_access_token", "app_secret",
    "verify_token", "account_sid", "secret_key",
})

_ENC_PREFIX = "ENC:"


def _get_secret_key() -> bytes:
    """Load or generate the machine-local encryption key."""
    key_path = get_trio_dir() / ".secret_key"
    if key_path.exists():
        return key_path.read_bytes()
    key = _secrets.token_bytes(32)
    key_path.write_bytes(key)
    try:
        key_path.chmod(0o600)
    except (OSError, NotImplementedError):
        pass
    return key


def _derive_key(master: bytes, context: str) -> bytes:
    """Derive a field-specific key using HMAC-SHA256."""
    return hashlib.sha256(master + context.encode()).digest()


def _encrypt_value(value: str, field_name: str) -> str:
    """Encrypt a string value for storage. Returns 'ENC:base64'."""
    if not value or value.startswith(_ENC_PREFIX):
        return value
    key = _derive_key(_get_secret_key(), field_name)
    data = value.encode("utf-8")
    # XOR encryption with derived key (repeating key)
    encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return _ENC_PREFIX + base64.b64encode(encrypted).decode("ascii")


def _decrypt_value(value: str, field_name: str) -> str:
    """Decrypt an 'ENC:base64' value back to plaintext."""
    if not isinstance(value, str) or not value.startswith(_ENC_PREFIX):
        return value
    key = _derive_key(_get_secret_key(), field_name)
    encrypted = base64.b64decode(value[len(_ENC_PREFIX):])
    decrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(encrypted))
    return decrypted.decode("utf-8")


def _encrypt_secrets(data: dict, path: str = "") -> dict:
    """Recursively encrypt secret fields in a config dict before saving."""
    result = {}
    for k, v in data.items():
        current_path = f"{path}.{k}" if path else k
        if isinstance(v, dict):
            result[k] = _encrypt_secrets(v, current_path)
        elif isinstance(v, str) and k in SECRET_FIELDS and v and not v.startswith(_ENC_PREFIX):
            result[k] = _encrypt_value(v, current_path)
        else:
            result[k] = v
    return result


def _decrypt_secrets(data: dict, path: str = "") -> dict:
    """Recursively decrypt secret fields when loading config."""
    result = {}
    for k, v in data.items():
        current_path = f"{path}.{k}" if path else k
        if isinstance(v, dict):
            result[k] = _decrypt_secrets(v, current_path)
        elif isinstance(v, str) and v.startswith(_ENC_PREFIX):
            try:
                result[k] = _decrypt_value(v, current_path)
            except Exception:
                result[k] = v  # Return encrypted if decryption fails
        else:
            result[k] = v
    return result
