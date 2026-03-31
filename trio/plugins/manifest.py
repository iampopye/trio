"""Plugin manifest — parsed from plugin.json with integrity verification."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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
    checksum: str = ""           # SHA-256 of plugin contents
    verified: bool = False       # Whether checksum was validated
    trusted: bool = False        # Whether author is in trusted list

    @classmethod
    def from_file(cls, plugin_json: Path) -> "PluginManifest":
        """Load manifest from a plugin.json file."""
        data = json.loads(plugin_json.read_text(encoding="utf-8"))
        manifest = cls(
            name=data.get("name", plugin_json.parent.name),
            version=data.get("version", "0.1.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            tools=data.get("tools", []),
            skills=data.get("skills", []),
            enabled=data.get("enabled", True),
            path=plugin_json.parent,
            checksum=data.get("checksum", ""),
        )
        # Verify integrity if checksum is provided
        if manifest.checksum:
            computed = manifest.compute_checksum()
            manifest.verified = (computed == manifest.checksum)
            if not manifest.verified:
                logger.warning(
                    f"Plugin '{manifest.name}' checksum mismatch! "
                    f"Expected {manifest.checksum[:16]}..., got {computed[:16]}... "
                    f"Plugin may have been tampered with."
                )
        return manifest

    def compute_checksum(self) -> str:
        """Compute SHA-256 checksum of all plugin source files."""
        hasher = hashlib.sha256()
        plugin_dir = self.path
        # Hash all .py and .md files in sorted order for determinism
        source_files = sorted(
            list(plugin_dir.rglob("*.py")) + list(plugin_dir.rglob("*.md"))
        )
        for f in source_files:
            if f.name == "__pycache__":
                continue
            try:
                hasher.update(f.name.encode())
                hasher.update(f.read_bytes())
            except Exception:
                pass
        return hasher.hexdigest()

    def generate_checksum(self) -> str:
        """Generate and store checksum in plugin.json."""
        self.checksum = self.compute_checksum()
        # Update plugin.json with new checksum
        manifest_file = self.path / "plugin.json"
        if manifest_file.exists():
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
            data["checksum"] = self.checksum
            manifest_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.verified = True
        return self.checksum

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "tools": self.tools,
            "skills": self.skills,
            "enabled": self.enabled,
            "checksum": self.checksum,
            "verified": self.verified,
        }
