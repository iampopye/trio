"""Base tool interface and registry for agent tool calling."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """Result from executing a tool."""
    output: str
    success: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseTool(ABC):
    """Abstract base for all agent tools.

    Each tool provides:
        - name: Unique identifier
        - description: What the tool does (shown to LLM)
        - parameters: JSON Schema defining expected params
        - execute(): Async execution returning ToolResult
    """

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict:
        """JSON Schema for tool parameters."""
        ...

    @abstractmethod
    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Execute the tool with given parameters."""
        ...

    def to_schema(self) -> dict:
        """Convert to OpenAI-compatible tool schema for LLM."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registry and executor for agent tools."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def get_schemas(self) -> list[dict]:
        """Get all tool schemas for LLM context."""
        return [tool.to_schema() for tool in self._tools.values()]

    async def execute(self, name: str, params: dict[str, Any]) -> ToolResult:
        """Execute a tool by name."""
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                output=f"Error: Unknown tool '{name}'. Available: {', '.join(self._tools.keys())}",
                success=False,
            )
        try:
            return await tool.execute(params)
        except Exception as e:
            logger.error(f"Tool '{name}' execution failed: {e}")
            return ToolResult(output=f"Error executing {name}: {e}", success=False)

    def register_builtins(self, config: dict) -> None:
        """Register built-in tools based on config."""
        enabled = config.get("tools", {}).get("builtin", [])

        if "web_search" in enabled:
            try:
                from trio.tools.web_search import WebSearchTool
                self.register(WebSearchTool())
            except ImportError:
                logger.warning("web_search tool unavailable (install duckduckgo-search)")

        if "math_solver" in enabled:
            try:
                from trio.tools.math_solver import MathSolverTool
                self.register(MathSolverTool())
            except ImportError:
                logger.warning("math_solver tool unavailable (install sympy)")

        if "shell" in enabled:
            from trio.tools.shell import ShellTool
            restrict = config.get("tools", {}).get("restrictToWorkspace", False)
            self.register(ShellTool(restrict_to_workspace=restrict))

        if "file_ops" in enabled:
            from trio.tools.file_ops import FileOpsTool
            restrict = config.get("tools", {}).get("restrictToWorkspace", False)
            self.register(FileOpsTool(restrict_to_workspace=restrict))

        if "rag_search" in enabled:
            from trio.tools.rag_tool import RAGSearchTool
            self.register(RAGSearchTool())

        if "browser" in enabled:
            try:
                from trio.tools.browser import BrowserTool
                self.register(BrowserTool())
            except ImportError:
                logger.warning("browser tool unavailable (install playwright)")

        if "email" in enabled:
            from trio.tools.email_tool import EmailTool
            email_cfg = config.get("tools", {}).get("email", {})
            self.register(EmailTool(config=email_cfg))

        if "calendar" in enabled:
            from trio.tools.calendar_tool import CalendarTool
            self.register(CalendarTool())

        if "notes" in enabled:
            from trio.tools.notes_tool import NotesTool
            self.register(NotesTool())

        if "screenshot" in enabled:
            try:
                from trio.tools.screenshot_tool import ScreenshotTool
                self.register(ScreenshotTool())
            except ImportError:
                logger.warning("screenshot tool unavailable (install mss, Pillow)")

        if "delegate" in enabled:
            # Sub-agent tool requires extra dependencies — registered via
            # register_subagent_tool() after the agent loop is constructed.
            # We just note the intent here; actual registration happens in AgentLoop.__init__.
            logger.debug("delegate tool enabled — will be registered by AgentLoop")

        logger.info(f"Registered {len(self._tools)} tools: {', '.join(self._tools.keys())}")
