"""TrioHub registry -- fetches skill/plugin index from GitHub or local bundle."""

import json
import logging
import ssl
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# GitHub-based registry
TRIOHUB_REPO = "trio-ai/triohub"
INDEX_URL = f"https://raw.githubusercontent.com/{TRIOHUB_REPO}/main/index.json"

# Local bundled index (ships with trio)
_BUNDLED_INDEX = Path(__file__).resolve().parent.parent.parent / "triohub" / "index.json"


class TrioHubRegistry:
    """Fetches and searches the community skill/plugin index."""

    def __init__(self):
        self._index: dict[str, Any] = {}
        self._loaded = False

    def _load_bundled(self) -> dict:
        """Load the bundled index.json shipped with trio."""
        if _BUNDLED_INDEX.is_file():
            try:
                self._index = json.loads(_BUNDLED_INDEX.read_text(encoding="utf-8"))
                self._loaded = True
                logger.debug(f"Loaded bundled TrioHub index ({len(self._index.get('skills', []))} skills)")
                return self._index
            except Exception as e:
                logger.warning(f"Failed to load bundled index: {e}")
        return {}

    async def fetch_index(self) -> dict:
        """Fetch the latest index from GitHub, falling back to local bundle."""
        # Try remote first
        try:
            import aiohttp

            # SSL context with fallback for Windows cert issues
            ssl_ctx = ssl.create_default_context()
            try:
                connector = aiohttp.TCPConnector(ssl=ssl_ctx)
            except Exception:
                connector = None

            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(INDEX_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        self._index = await resp.json()
                        self._loaded = True
                        return self._index
                    else:
                        logger.debug(f"TrioHub remote fetch: HTTP {resp.status}")
        except ImportError:
            # Fallback to urllib
            import urllib.request
            try:
                ctx = ssl.create_default_context()
                with urllib.request.urlopen(INDEX_URL, timeout=10, context=ctx) as resp:
                    self._index = json.loads(resp.read().decode())
                    self._loaded = True
                    return self._index
            except Exception:
                # Try without SSL verification (Windows cert issue)
                try:
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    with urllib.request.urlopen(INDEX_URL, timeout=10, context=ctx) as resp:
                        self._index = json.loads(resp.read().decode())
                        self._loaded = True
                        return self._index
                except Exception as e:
                    logger.debug(f"TrioHub remote fetch failed: {e}")
        except Exception as e:
            logger.debug(f"TrioHub remote fetch failed: {e}")

        # Fall back to bundled index
        return self._load_bundled()

    def _all_skills(self) -> list[dict]:
        """Flatten skills from categories or top-level 'skills' key."""
        # Support both formats: categories[].skills[] and flat skills[]
        skills = []
        for cat in self._index.get("categories", []):
            cat_name = cat.get("name", "")
            for skill in cat.get("skills", []):
                skills.append({**skill, "category": cat_name})
        # Also check flat skills key
        skills.extend(self._index.get("skills", []))
        return skills

    async def search(self, query: str) -> list[dict]:
        """Search for skills/plugins matching query."""
        if not self._loaded:
            await self.fetch_index()

        query_lower = query.lower()
        results = []

        for item in self._all_skills():
            if (
                query_lower in item.get("name", "").lower()
                or query_lower in item.get("description", "").lower()
                or query_lower in " ".join(item.get("tags", [])).lower()
                or query_lower in item.get("category", "").lower()
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
        for item in self._all_skills():
            all_items.append({**item, "type": "skill"})
        for item in self._index.get("plugins", []):
            all_items.append({**item, "type": "plugin"})

        all_items.sort(key=lambda x: x.get("downloads", 0), reverse=True)
        return all_items[:limit]
