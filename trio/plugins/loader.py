"""Plugin loader — discovers and loads plugins from ~/.trio/plugins/."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

from trio.plugins.manifest import PluginManifest
from trio.tools.base import BaseTool, ToolRegistry

logger = logging.getLogger(__name__)


class PluginLoader:
    """Discovers and loads plugins from the plugins directory."""

    def __init__(self, plugins_dir: Path):
        self._plugins_dir = plugins_dir
        self._manifests: dict[str, PluginManifest] = {}

    def discover(self) -> list[PluginManifest]:
        """Scan plugins directory for plugin.json files."""
        self._manifests.clear()
        if not self._plugins_dir.exists():
            return []

        manifests = []
        for plugin_dir in self._plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue
            manifest_file = plugin_dir / "plugin.json"
            if not manifest_file.exists():
                continue
            try:
                manifest = PluginManifest.from_file(manifest_file)
                self._manifests[manifest.name] = manifest
                manifests.append(manifest)
                logger.debug(f"Discovered plugin: {manifest.name} v{manifest.version}")
            except Exception as e:
                logger.warning(f"Failed to load plugin manifest from {plugin_dir.name}: {e}")

        return manifests

    def load_tools(self, manifest: PluginManifest, registry: ToolRegistry) -> int:
        """Load tool classes from a plugin and register them.

        Security: if the plugin has a checksum but verification failed,
        tools are NOT loaded to prevent execution of tampered code.
        """
        if not manifest.enabled:
            return 0

        # Security check: reject tampered or unverified plugins
        if manifest.checksum and not manifest.verified:
            logger.error(
                f"SECURITY: Refusing to load tools from plugin '{manifest.name}' — "
                f"checksum verification FAILED. The plugin may have been tampered with. "
                f"Re-install the plugin or run 'trio plugin verify {manifest.name}'."
            )
            return 0

        if not manifest.checksum:
            logger.warning(
                f"SECURITY: Plugin '{manifest.name}' has no checksum. "
                f"Run 'trio plugin sign {manifest.name}' to generate one. "
                f"Unverified plugins will be blocked in a future release."
            )

        tools_dir = manifest.path / "tools"
        if not tools_dir.exists():
            return 0

        count = 0
        for py_file in tools_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            try:
                tool = self._load_tool_from_file(py_file, manifest.name)
                if tool:
                    registry.register(tool)
                    count += 1
                    verified_tag = " [verified]" if manifest.verified else " [unverified]"
                    logger.info(f"Loaded plugin tool: {tool.name} (from {manifest.name}){verified_tag}")
            except Exception as e:
                logger.error(f"Failed to load tool from {py_file}: {e}")

        return count

    def _load_tool_from_file(self, py_file: Path, plugin_name: str) -> BaseTool | None:
        """Dynamically load a BaseTool subclass from a Python file."""
        module_name = f"trio_plugin_{plugin_name}_{py_file.stem}"

        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # Find BaseTool subclass
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseTool)
                and attr is not BaseTool
            ):
                return attr()

        return None

    def load_skills(self, manifest: PluginManifest) -> list[Path]:
        """Return paths to skill files from a plugin."""
        if not manifest.enabled:
            return []

        skills_dir = manifest.path / "skills"
        if not skills_dir.exists():
            return []

        return list(skills_dir.glob("*.md"))

    def get_manifest(self, name: str) -> PluginManifest | None:
        return self._manifests.get(name)

    @property
    def manifests(self) -> dict[str, PluginManifest]:
        return dict(self._manifests)
