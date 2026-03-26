"""Configuration loader for ~/.trio/config.json."""

import json
import os
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
    """Load config from ~/.trio/config.json, merging with defaults."""
    config_path = get_config_path()
    if not config_path.exists():
        return DEFAULT_CONFIG.copy()

    with open(config_path, "r", encoding="utf-8") as f:
        user_config = json.load(f)

    return _deep_merge(DEFAULT_CONFIG, user_config)


def save_config(config: dict[str, Any]) -> None:
    """Save config to ~/.trio/config.json."""
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


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
