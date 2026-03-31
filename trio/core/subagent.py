"""Sub-agent system — spawn specialized child agents for focused tasks.

The main AgentLoop can delegate work to sub-agents, each configured with
a specific role, model, and tool subset. Sub-agents run a mini agent loop
(up to max_iterations) and return their final response to the parent.

Architecture:
    AgentLoop → SubAgentTool → SubAgentRegistry → SubAgent.execute()
    SubAgent runs its own generate/tool-call loop using the shared provider.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from trio.core.memory import MemoryStore
from trio.providers.base import BaseProvider, LLMResponse
from trio.tools.base import ToolRegistry, ToolResult

logger = logging.getLogger(__name__)


@dataclass
class SubAgentConfig:
    """Configuration for a sub-agent."""

    name: str                       # e.g., "researcher", "coder", "reviewer"
    role: str                       # System prompt role description
    model: str | None = None        # Optional model override (use cheaper model for simple tasks)
    tools: list[str] = field(default_factory=list)  # Which tools this sub-agent can use
    max_iterations: int = 5         # Max think-act cycles before returning

    def __repr__(self) -> str:
        return f"SubAgentConfig(name={self.name!r}, model={self.model!r}, tools={self.tools})"


class SubAgent:
    """A child agent spawned by the main AgentLoop for a specific task.

    Runs a bounded generate → tool-call → observe loop, then returns the
    final textual response.  Does NOT publish to the MessageBus — all
    communication stays internal so the parent agent can post-process.
    """

    def __init__(
        self,
        config: SubAgentConfig,
        provider: BaseProvider,
        tools: ToolRegistry,
        memory: MemoryStore,
    ):
        self.config = config
        self.provider = provider
        self.tools = tools
        self.memory = memory

    async def execute(self, task: str, context: list[dict] | None = None) -> str:
        """Execute a task and return the result.

        Args:
            task: The task description / user instruction.
            context: Optional prior conversation messages for continuity.

        Returns:
            The sub-agent's final textual response.
        """
        system_prompt = self._build_system_prompt()

        # Start with system + optional context + the task itself
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        if context:
            messages.extend(context)
        messages.append({"role": "user", "content": task})

        # Determine which tool schemas this sub-agent may use
        allowed_schemas = self._get_allowed_tool_schemas()

        model = self.config.model  # None means provider default

        final_text = ""
        for iteration in range(self.config.max_iterations):
            logger.debug(
                "SubAgent '%s' iteration %d/%d",
                self.config.name,
                iteration + 1,
                self.config.max_iterations,
            )

            # --- Generate ---
            has_tools = (
                self.provider.supports_tools()
                and allowed_schemas
                and iteration < self.config.max_iterations - 1  # last iteration: no tools
            )

            response: LLMResponse = await self.provider.generate(
                messages=messages,
                model=model,
                tools=allowed_schemas if has_tools else None,
            )

            # --- Check for tool calls ---
            if response.tool_calls and has_tools:
                # Append the assistant message with tool calls
                messages.append({
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": tc.arguments,
                            },
                        }
                        for tc in response.tool_calls
                    ],
                })

                # Execute each tool call and feed results back
                for tc in response.tool_calls:
                    if tc.name not in [s["function"]["name"] for s in (allowed_schemas or [])]:
                        tool_output = f"Error: Tool '{tc.name}' is not available to this sub-agent."
                        success = False
                    else:
                        result: ToolResult = await self.tools.execute(tc.name, tc.arguments)
                        tool_output = result.output
                        success = result.success

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_output,
                    })

                    logger.debug(
                        "SubAgent '%s' tool '%s' %s",
                        self.config.name,
                        tc.name,
                        "succeeded" if success else "failed",
                    )

                # Continue the loop to let the LLM process tool results
                continue

            # --- No tool calls — we have the final answer ---
            final_text = response.content or ""
            break
        else:
            # Exhausted iterations — return whatever we have
            if not final_text:
                final_text = response.content or "(Sub-agent reached iteration limit with no final response)"

        logger.info(
            "SubAgent '%s' completed in %d iteration(s), response length %d",
            self.config.name,
            iteration + 1,
            len(final_text),
        )
        return final_text

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """Build a focused system prompt from the config role."""
        # Include long-term memory context if available
        memory_context = ""
        mem_text = self.memory.read_memory()
        if mem_text and len(mem_text) > 50:
            memory_context = (
                "\n\n## Long-term Memory\n"
                f"{mem_text[:2000]}\n"
            )

        return (
            f"You are a specialized sub-agent named '{self.config.name}'.\n\n"
            f"## Your Role\n{self.config.role}\n\n"
            "## Instructions\n"
            "- Focus exclusively on the task you are given.\n"
            "- Be thorough but concise in your response.\n"
            "- Use available tools when they would help accomplish the task.\n"
            "- When finished, provide a clear, complete answer.\n"
            f"{memory_context}"
        )

    def _get_allowed_tool_schemas(self) -> list[dict] | None:
        """Return tool schemas filtered to only the tools this sub-agent can use."""
        if not self.config.tools:
            return None

        schemas = []
        for tool_name in self.config.tools:
            tool = self.tools.get(tool_name)
            if tool is not None:
                schemas.append(tool.to_schema())
            else:
                logger.warning(
                    "SubAgent '%s' configured with unavailable tool '%s'",
                    self.config.name,
                    tool_name,
                )
        return schemas if schemas else None


class SubAgentRegistry:
    """Registry of available sub-agent configurations.

    Holds named configs that the main agent can reference via the
    ``delegate`` tool.  Ships with sensible built-in sub-agents and
    supports runtime registration for custom ones.
    """

    def __init__(self):
        self._configs: dict[str, SubAgentConfig] = {}

    def register(self, config: SubAgentConfig) -> None:
        """Register (or overwrite) a sub-agent configuration."""
        self._configs[config.name] = config
        logger.debug("Registered sub-agent config: %s", config.name)

    def get(self, name: str) -> SubAgentConfig | None:
        """Look up a sub-agent config by name."""
        return self._configs.get(name)

    def list_agents(self) -> list[SubAgentConfig]:
        """Return all registered sub-agent configs."""
        return list(self._configs.values())

    def names(self) -> list[str]:
        """Return all registered sub-agent names."""
        return list(self._configs.keys())


def register_default_subagents(registry: SubAgentRegistry) -> None:
    """Register the built-in sub-agent configurations."""

    registry.register(SubAgentConfig(
        name="researcher",
        role=(
            "You are a research specialist. Your job is to search the web, "
            "read documents, and gather information on a given topic. "
            "Synthesize findings into a clear, well-organized summary with "
            "sources cited where possible."
        ),
        tools=["web_search", "browser", "rag_search"],
        max_iterations=8,
    ))

    registry.register(SubAgentConfig(
        name="coder",
        role=(
            "You are an expert software engineer. Write clean, efficient, "
            "well-documented code. Follow best practices and modern patterns. "
            "When reviewing code, identify bugs, security issues, and "
            "improvement opportunities. You can use the shell and file tools "
            "to explore and modify code."
        ),
        tools=["shell", "file_ops"],
        max_iterations=10,
    ))

    registry.register(SubAgentConfig(
        name="reviewer",
        role=(
            "You are a quality reviewer. Carefully analyze content for "
            "accuracy, completeness, clarity, and correctness. Provide "
            "specific, actionable feedback. Flag any errors, inconsistencies, "
            "or areas that need improvement. Rate overall quality."
        ),
        tools=[],
        max_iterations=3,
    ))

    registry.register(SubAgentConfig(
        name="planner",
        role=(
            "You are a planning and decomposition specialist. Break complex "
            "tasks into clear, ordered steps. Identify dependencies between "
            "steps, estimate complexity, and suggest which sub-agent should "
            "handle each step. Output a structured plan."
        ),
        tools=[],
        max_iterations=3,
    ))

    registry.register(SubAgentConfig(
        name="summarizer",
        role=(
            "You are a summarization specialist. Condense long content into "
            "clear, accurate summaries. Preserve key facts, decisions, and "
            "action items. Adjust summary length to the complexity of the "
            "input — a few sentences for simple content, structured sections "
            "for complex material."
        ),
        tools=[],
        max_iterations=2,
    ))

    logger.info(
        "Registered %d default sub-agents: %s",
        len(registry.list_agents()),
        ", ".join(registry.names()),
    )
