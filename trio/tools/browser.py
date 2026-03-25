"""Browser automation tool — control a web browser via Playwright."""

import asyncio
import base64
import logging
import tempfile
from pathlib import Path
from typing import Any

from trio.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class BrowserTool(BaseTool):
    """Control a web browser: navigate, click, fill forms, take screenshots, extract content."""

    def __init__(self):
        self._browser = None
        self._context = None
        self._page = None

    @property
    def name(self) -> str:
        return "browser"

    @property
    def description(self) -> str:
        return (
            "Control a web browser to navigate pages, click elements, fill forms, "
            "take screenshots, extract text/HTML, and run JavaScript. "
            "Supports attaching to an existing Chrome session via CDP."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["navigate", "click", "fill", "screenshot", "get_text",
                             "get_html", "evaluate", "wait", "close"],
                    "description": "Browser action to perform",
                },
                "url": {
                    "type": "string",
                    "description": "URL to navigate to (for 'navigate' action)",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector for click/fill/get_text actions",
                },
                "value": {
                    "type": "string",
                    "description": "Value to fill (for 'fill' action)",
                },
                "javascript": {
                    "type": "string",
                    "description": "JavaScript code to evaluate (for 'evaluate' action)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 30)",
                    "default": 30,
                },
                "cdp_url": {
                    "type": "string",
                    "description": "CDP endpoint to attach to existing browser (e.g. http://localhost:9222)",
                },
            },
            "required": ["action"],
        }

    async def _ensure_browser(self, cdp_url: str | None = None) -> None:
        """Launch or connect to a browser."""
        if self._page is not None:
            return

        from playwright.async_api import async_playwright

        pw = await async_playwright().start()

        if cdp_url:
            self._browser = await pw.chromium.connect_over_cdp(cdp_url)
            contexts = self._browser.contexts
            self._context = contexts[0] if contexts else await self._browser.new_context()
        else:
            self._browser = await pw.chromium.launch(headless=True)
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )

        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        action = params.get("action", "")
        timeout = params.get("timeout", 30) * 1000  # ms

        if action == "close":
            if self._browser:
                await self._browser.close()
                self._browser = None
                self._context = None
                self._page = None
            return ToolResult(output="Browser closed.")

        try:
            await self._ensure_browser(params.get("cdp_url"))
        except Exception as e:
            return ToolResult(output=f"Browser launch failed: {e}", success=False)

        try:
            if action == "navigate":
                url = params.get("url", "")
                if not url:
                    return ToolResult(output="Error: URL required for navigate", success=False)
                await self._page.goto(url, timeout=timeout, wait_until="domcontentloaded")
                title = await self._page.title()
                return ToolResult(
                    output=f"Navigated to: {url}\nTitle: {title}",
                    metadata={"url": url, "title": title},
                )

            elif action == "click":
                selector = params.get("selector", "")
                if not selector:
                    return ToolResult(output="Error: selector required", success=False)
                await self._page.click(selector, timeout=timeout)
                return ToolResult(output=f"Clicked: {selector}")

            elif action == "fill":
                selector = params.get("selector", "")
                value = params.get("value", "")
                if not selector:
                    return ToolResult(output="Error: selector required", success=False)
                await self._page.fill(selector, value, timeout=timeout)
                return ToolResult(output=f"Filled '{selector}' with: {value}")

            elif action == "screenshot":
                tmp = Path(tempfile.gettempdir()) / "trio_screenshot.png"
                await self._page.screenshot(path=str(tmp), full_page=False)
                size_kb = tmp.stat().st_size / 1024
                return ToolResult(
                    output=f"Screenshot saved: {tmp} ({size_kb:.0f}KB)",
                    metadata={"path": str(tmp)},
                )

            elif action == "get_text":
                selector = params.get("selector", "body")
                el = await self._page.query_selector(selector)
                if not el:
                    return ToolResult(output=f"Element not found: {selector}", success=False)
                text = await el.inner_text()
                if len(text) > 4000:
                    text = text[:4000] + "\n... (truncated)"
                return ToolResult(output=text)

            elif action == "get_html":
                selector = params.get("selector", "body")
                el = await self._page.query_selector(selector)
                if not el:
                    return ToolResult(output=f"Element not found: {selector}", success=False)
                html = await el.inner_html()
                if len(html) > 4000:
                    html = html[:4000] + "\n... (truncated)"
                return ToolResult(output=html)

            elif action == "evaluate":
                js = params.get("javascript", "")
                if not js:
                    return ToolResult(output="Error: javascript required", success=False)
                result = await self._page.evaluate(js)
                return ToolResult(output=str(result))

            elif action == "wait":
                selector = params.get("selector", "")
                if selector:
                    await self._page.wait_for_selector(selector, timeout=timeout)
                    return ToolResult(output=f"Element found: {selector}")
                else:
                    ms = params.get("timeout", 2) * 1000
                    await self._page.wait_for_timeout(ms)
                    return ToolResult(output=f"Waited {params.get('timeout', 2)}s")

            else:
                return ToolResult(output=f"Unknown action: {action}", success=False)

        except Exception as e:
            logger.error(f"Browser action '{action}' failed: {e}")
            return ToolResult(output=f"Browser error: {e}", success=False)
