"""Web search tool — Firecrawl (preferred) or DuckDuckGo (free fallback)."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import logging
import os
from typing import Any

from trio.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    """Search the web using Firecrawl (if API key set) or DuckDuckGo (free fallback).

    Firecrawl is preferred for production because:
        - Handles JavaScript-rendered pages correctly
        - Not rate-limited like DDG scraping
        - Returns cleaner, more reliable results
        - Free tier: 500 credits/month

    Set FIRECRAWL_API_KEY environment variable to enable Firecrawl.
    Without it, falls back to DuckDuckGo (free, but less reliable).
    """

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for current information. Returns top results with titles, "
            "URLs, and snippets. Use this when you need up-to-date information."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        query = params.get("query", "")
        max_results = params.get("max_results", 5)

        if not query:
            return ToolResult(output="Error: No search query provided", success=False)

        # Try Firecrawl first if API key is configured
        firecrawl_key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
        if firecrawl_key:
            try:
                results = await self._firecrawl_search(query, max_results, firecrawl_key)
                if results:
                    formatted = self._format_results(results)
                    return ToolResult(
                        output=formatted,
                        metadata={"result_count": len(results), "backend": "firecrawl"},
                    )
                logger.info("Firecrawl returned no results, falling back to DuckDuckGo")
            except Exception as e:
                logger.warning(f"Firecrawl search failed, falling back to DuckDuckGo: {e}")

        # Fallback: DuckDuckGo
        try:
            results = await asyncio.to_thread(self._ddg_search, query, max_results)
            if not results:
                return ToolResult(output=f"No results found for: {query}")

            formatted = self._format_results(results)
            return ToolResult(
                output=formatted,
                metadata={"result_count": len(results), "backend": "duckduckgo"},
            )

        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return ToolResult(output=f"Search error: {e}", success=False)

    async def _firecrawl_search(
        self, query: str, max_results: int, api_key: str
    ) -> list[dict]:
        """Use Firecrawl's search API for high-quality results."""
        import aiohttp

        url = "https://api.firecrawl.dev/v1/search"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "query": query,
            "limit": max_results,
            "scrapeOptions": {"formats": ["markdown"]},
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning(f"Firecrawl HTTP {resp.status}: {body[:200]}")
                        return []
                    data = await resp.json()

            # Firecrawl returns: {"success": true, "data": [{title, url, description, markdown}, ...]}
            items = data.get("data", []) if isinstance(data, dict) else []
            results = []
            for item in items[:max_results]:
                results.append({
                    "title": item.get("title", "No title"),
                    "href": item.get("url", ""),
                    "body": item.get("description") or item.get("markdown", "")[:300] or "No description",
                })
            return results

        except asyncio.TimeoutError:
            logger.warning("Firecrawl request timed out")
            return []
        except Exception as e:
            logger.warning(f"Firecrawl error: {e}")
            return []

    def _ddg_search(self, query: str, max_results: int) -> list[dict]:
        """Fallback: DuckDuckGo via the duckduckgo_search package."""
        import time

        try:
            from duckduckgo_search import DDGS
        except ImportError:
            logger.error("duckduckgo_search not installed; install trio-ai[search]")
            return []

        for attempt in range(3):
            try:
                results = list(DDGS().text(query, max_results=max_results))
                if results:
                    return results
            except Exception as e:
                logger.warning(f"DDG search attempt {attempt + 1} failed: {e}")
            if attempt < 2:
                time.sleep(1)
        return []

    def _format_results(self, results: list[dict]) -> str:
        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "No title")
            url = r.get("href", "")
            snippet = r.get("body", "No description")
            lines.append(f"[{i}] {title}\n    URL: {url}\n    {snippet}")
        return "\n\n".join(lines)
