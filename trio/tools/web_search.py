"""Web search tool — DuckDuckGo search with formatted results."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import logging
from typing import Any

from trio.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    """Search the web using DuckDuckGo."""

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

        try:
            results = await asyncio.to_thread(self._search, query, max_results)
            if not results:
                return ToolResult(output=f"No results found for: {query}")

            formatted = self._format_results(results)
            return ToolResult(output=formatted, metadata={"result_count": len(results)})

        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return ToolResult(output=f"Search error: {e}", success=False)

    def _search(self, query: str, max_results: int) -> list[dict]:
        import time
        from duckduckgo_search import DDGS

        for attempt in range(3):
            try:
                results = list(DDGS().text(query, max_results=max_results))
                if results:
                    return results
            except Exception as e:
                logger.warning(f"Search attempt {attempt + 1} failed: {e}")
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
