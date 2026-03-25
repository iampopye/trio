"""TrioHub registry — fetches skill/plugin index from GitHub."""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# GitHub-based registry
TRIOHUB_REPO = "trio-ai/triohub"
INDEX_URL = f"https://raw.githubusercontent.com/{TRIOHUB_REPO}/main/index.json"


class TrioHubRegistry:
    """Fetches and searches the community skill/plugin index."""

    def __init__(self):
        self._index: dict[str, Any] = {}
        self._loaded = False

    async def fetch_index(self) -> dict:
        """Fetch the latest index from GitHub."""
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.get(INDEX_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        self._index = await resp.json()
                        self._loaded = True
                        return self._index
                    else:
                        logger.warning(f"TrioHub fetch failed: HTTP {resp.status}")
        except ImportError:
            # Fallback to urllib
            import urllib.request
            try:
                with urllib.request.urlopen(INDEX_URL, timeout=10) as resp:
                    self._index = json.loads(resp.read().decode())
                    self._loaded = True
                    return self._index
            except Exception as e:
                logger.warning(f"TrioHub fetch failed: {e}")
        except Exception as e:
            logger.warning(f"TrioHub fetch failed: {e}")

        return {}

    async def search(self, query: str) -> list[dict]:
        """Search for skills/plugins matching query."""
        if not self._loaded:
            await self.fetch_index()

        query_lower = query.lower()
        results = []

        for item in self._index.get("skills", []):
            if (
                query_lower in item.get("name", "").lower()
                or query_lower in item.get("description", "").lower()
                or query_lower in " ".join(item.get("tags", [])).lower()
            ):
                results.append({**item, "type": "skill"})

        for item in self._index.get("plugins", []):
            if (
                query_lower in item.get("name", "").lower()
                or query_lower in item.get("description", "").lower()
            ):
                results.append({**item, "type": "plugin"})

        return results

    async def get_trending(self, limit: int = 20) -> list[dict]:
        """Get trending skills and plugins (sorted by downloads)."""
        if not self._loaded:
            await self.fetch_index()

        all_items = []
        for item in self._index.get("skills", []):
            all_items.append({**item, "type": "skill"})
        for item in self._index.get("plugins", []):
            all_items.append({**item, "type": "plugin"})

        all_items.sort(key=lambda x: x.get("downloads", 0), reverse=True)
        return all_items[:limit]
