"""SubAgent delegation tool — lets the main agent spawn sub-agents for focused tasks."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import logging
from typing import Any

from trio.core.memory import MemoryStore
from trio.core.subagent import SubAgent, SubAgentRegistry
from trio.providers.base import BaseProvider
from trio.tools.base import BaseTool, ToolRegistry, ToolResult

logger = logging.getLogger(__name__)


class SubAgentTool(BaseTool):
    """Tool that the main AgentLoop can invoke to delegate work to a sub-agent.

    Usage by the LLM:
        delegate(agent_name="researcher", task="Find the latest Python 3.13 features")
        delegate(agent_name="coder", task="Write a Redis caching decorator", context="We use Python 3.12")
    """

    def __init__(
        self,
        registry: SubAgentRegistry,
        provider: BaseProvider,
        tools: ToolRegistry,
        memory: MemoryStore,
    ):
        self._registry = registry
        self._provider = provider
        self._tools = tools
        self._memory = memory

    @property
    def name(self) -> str:
        return "delegate"

    @property
    def description(self) -> str:
        agent_names = ", ".join(self._registry.names()) if self._registry.names() else "none registered"
        return (
            "Delegate a task to a specialized sub-agent. Each sub-agent has a "
            "specific role and toolset. Use this when a task benefits from "
            "focused expertise. "
            f"Available agents: {agent_names}"
        )

    @property
    def parameters(self) -> dict:
        agent_names = self._registry.names()
        return {
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": (
                        "Name of the sub-agent to delegate to. "
                        f"Available: {', '.join(agent_names)}"
                    ),
                    "enum": agent_names if agent_names else None,
                },
                "task": {
                    "type": "string",
                    "description": (
                        "Clear description of the task for the sub-agent. "
                        "Be specific about what you need."
                    ),
                },
                "context": {
                    "type": "string",
                    "description": (
                        "Optional additional context or background information "
                        "the sub-agent should know."
                    ),
                },
            },
            "required": ["agent_name", "task"],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Spawn a sub-agent and return its response."""
        agent_name = params.get("agent_name", "")
        task = params.get("task", "")
        context_str = params.get("context", "")

        if not agent_name:
            return ToolResult(
                output="Error: 'agent_name' is required.",
                success=False,
            )
        if not task:
            return ToolResult(
                output="Error: 'task' is required.",
                success=False,
            )

        # Look up the sub-agent config
        config = self._registry.get(agent_name)
        if config is None:
            available = ", ".join(self._registry.names()) or "none"
            return ToolResult(
                output=(
                    f"Error: Unknown sub-agent '{agent_name}'. "
                    f"Available: {available}"
                ),
                success=False,
            )

        # Build optional context messages
        context_messages: list[dict] | None = None
        if context_str:
            context_messages = [
                {"role": "user", "content": f"Background context:\n{context_str}"},
                {"role": "assistant", "content": "Understood. I'll keep this context in mind."},
            ]

        # Create and execute the sub-agent
        logger.info("Delegating to sub-agent '%s': %s", agent_name, task[:100])
        sub = SubAgent(
            config=config,
            provider=self._provider,
            tools=self._tools,
            memory=self._memory,
        )

        try:
            result = await sub.execute(task=task, context=context_messages)
            return ToolResult(
                output=result,
                success=True,
                metadata={
                    "agent_name": agent_name,
                    "model": config.model or "default",
                },
            )
        except Exception as e:
            logger.error("Sub-agent '%s' failed: %s", agent_name, e, exc_info=True)
            return ToolResult(
                output=f"Sub-agent '{agent_name}' encountered an error: {e}",
                success=False,
                metadata={"agent_name": agent_name},
            )
