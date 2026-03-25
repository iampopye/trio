"""Plugin manager — install, uninstall, enable, disable plugins."""

import json
import logging
import shutil
from pathlib import Path

from trio.core.config import get_plugins_dir
from trio.plugins.manifest import PluginManifest

logger = logging.getLogger(__name__)


class PluginManager:
    """Manage plugin lifecycle: install, uninstall, enable, disable."""

    def __init__(self):
        self._plugins_dir = get_plugins_dir()

    def list_plugins(self) -> list[PluginManifest]:
        """List all installed plugins."""
        plugins = []
        if not self._plugins_dir.exists():
            return plugins

        for plugin_dir in sorted(self._plugins_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue
            manifest_file = plugin_dir / "plugin.json"
            if manifest_file.exists():
                try:
                    plugins.append(PluginManifest.from_file(manifest_file))
                except Exception as e:
                    logger.warning(f"Bad manifest in {plugin_dir.name}: {e}")
        return plugins

    def install(self, source: str) -> str:
        """Install a plugin from a local path.

        Returns the plugin name on success.
        """
        source_path = Path(source).resolve()
        if not source_path.is_dir():
            raise FileNotFoundError(f"Plugin source not found: {source}")

        manifest_file = source_path / "plugin.json"
        if not manifest_file.exists():
            raise ValueError(f"No plugin.json found in {source}")

        manifest = PluginManifest.from_file(manifest_file)
        dest = self._plugins_dir / manifest.name

        if dest.exists():
            shutil.rmtree(dest)

        shutil.copytree(source_path, dest)
        logger.info(f"Installed plugin: {manifest.name} v{manifest.version}")
        return manifest.name

    def uninstall(self, name: str) -> bool:
        """Remove an installed plugin."""
        plugin_dir = self._plugins_dir / name
        if not plugin_dir.exists():
            return False

        shutil.rmtree(plugin_dir)
        logger.info(f"Uninstalled plugin: {name}")
        return True

    def enable(self, name: str) -> bool:
        """Enable a disabled plugin."""
        return self._set_enabled(name, True)

    def disable(self, name: str) -> bool:
        """Disable a plugin."""
        return self._set_enabled(name, False)

    def _set_enabled(self, name: str, enabled: bool) -> bool:
        """Update the enabled flag in plugin.json."""
        manifest_file = self._plugins_dir / name / "plugin.json"
        if not manifest_file.exists():
            return False

        data = json.loads(manifest_file.read_text(encoding="utf-8"))
        data["enabled"] = enabled
        manifest_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"Plugin '{name}' {'enabled' if enabled else 'disabled'}")
        return True
