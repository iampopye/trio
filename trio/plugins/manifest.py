"""Plugin manifest — parsed from plugin.json."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PluginManifest:
    """Represents a plugin's metadata from plugin.json."""

    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    enabled: bool = True
    path: Path = field(default_factory=lambda: Path("."))

    @classmethod
    def from_file(cls, plugin_json: Path) -> "PluginManifest":
        """Load manifest from a plugin.json file."""
        data = json.loads(plugin_json.read_text(encoding="utf-8"))
        return cls(
            name=data.get("name", plugin_json.parent.name),
            version=data.get("version", "0.1.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            tools=data.get("tools", []),
            skills=data.get("skills", []),
            enabled=data.get("enabled", True),
            path=plugin_json.parent,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "tools": self.tools,
            "skills": self.skills,
            "enabled": self.enabled,
        }
