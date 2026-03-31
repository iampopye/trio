"""TrioHub installer — downloads skills and plugins from the registry."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import json
import logging
import shutil
import tempfile
from pathlib import Path

from trio.core.config import get_skills_dir, get_plugins_dir

logger = logging.getLogger(__name__)

TRIOHUB_REPO = "trio-ai/triohub"
RAW_BASE = f"https://raw.githubusercontent.com/{TRIOHUB_REPO}/main"


class HubInstaller:
    """Download and install skills/plugins from TrioHub."""

    async def install_skill(self, name: str, metadata: dict | None = None) -> bool:
        """Download and install a skill from TrioHub."""
        skills_dir = get_skills_dir()
        url = f"{RAW_BASE}/skills/{name}.md"

        try:
            content = await self._download(url)
            if content is None:
                logger.error(f"Skill '{name}' not found in TrioHub")
                return False

            dest = skills_dir / f"{name}.md"
            dest.write_text(content, encoding="utf-8")
            logger.info(f"Installed skill: {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to install skill '{name}': {e}")
            return False

    async def install_plugin(self, name: str, metadata: dict | None = None) -> bool:
        """Download and install a plugin from TrioHub."""
        plugins_dir = get_plugins_dir()
        manifest_url = f"{RAW_BASE}/plugins/{name}/plugin.json"

        try:
            manifest_content = await self._download(manifest_url)
            if manifest_content is None:
                logger.error(f"Plugin '{name}' not found in TrioHub")
                return False

            manifest = json.loads(manifest_content)
            dest = plugins_dir / name
            dest.mkdir(parents=True, exist_ok=True)

            # Save manifest
            (dest / "plugin.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )

            # Download tool files
            for tool_file in manifest.get("tools", []):
                tool_url = f"{RAW_BASE}/plugins/{name}/tools/{tool_file}"
                content = await self._download(tool_url)
                if content:
                    tools_dir = dest / "tools"
                    tools_dir.mkdir(exist_ok=True)
                    (tools_dir / tool_file).write_text(content, encoding="utf-8")

            # Download skill files
            for skill_file in manifest.get("skills", []):
                skill_url = f"{RAW_BASE}/plugins/{name}/skills/{skill_file}"
                content = await self._download(skill_url)
                if content:
                    skills_subdir = dest / "skills"
                    skills_subdir.mkdir(exist_ok=True)
                    (skills_subdir / skill_file).write_text(content, encoding="utf-8")

            logger.info(f"Installed plugin: {name} v{manifest.get('version', '?')}")
            return True
        except Exception as e:
            logger.error(f"Failed to install plugin '{name}': {e}")
            return False

    async def _download(self, url: str) -> str | None:
        """Download a file from URL, return content as string."""
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        return await resp.text()
                    return None
        except ImportError:
            import urllib.request
            try:
                with urllib.request.urlopen(url, timeout=15) as resp:
                    return resp.read().decode("utf-8")
            except Exception:
                return None
