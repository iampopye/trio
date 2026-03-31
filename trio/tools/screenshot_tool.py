"""Screenshot tool — capture screen or specific regions."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any

from trio.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class ScreenshotTool(BaseTool):
    """Take screenshots of the screen or specific regions."""

    @property
    def name(self) -> str:
        return "screenshot"

    @property
    def description(self) -> str:
        return (
            "Take a screenshot of the entire screen or a specific region. "
            "Returns the file path of the saved screenshot."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "region": {
                    "type": "object",
                    "description": "Optional region to capture {x, y, width, height}",
                    "properties": {
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                },
                "save_path": {
                    "type": "string",
                    "description": "Optional file path to save screenshot (default: temp file)",
                },
            },
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        try:
            return await asyncio.to_thread(self._capture, params)
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return ToolResult(output=f"Screenshot error: {e}", success=False)

    def _capture(self, params: dict) -> ToolResult:
        import mss
        from PIL import Image

        save_path = params.get("save_path")
        if not save_path:
            save_path = str(Path(tempfile.gettempdir()) / "trio_screenshot.png")

        region = params.get("region")

        with mss.mss() as sct:
            if region:
                monitor = {
                    "left": region.get("x", 0),
                    "top": region.get("y", 0),
                    "width": region.get("width", 800),
                    "height": region.get("height", 600),
                }
            else:
                monitor = sct.monitors[0]  # Full screen

            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            img.save(save_path)

        size_kb = Path(save_path).stat().st_size / 1024
        return ToolResult(
            output=f"Screenshot saved: {save_path} ({size_kb:.0f}KB, {img.width}x{img.height})",
            metadata={"path": save_path, "width": img.width, "height": img.height},
        )
