"""Agent Loop — the heart of trio. Perceive → Think → Act → Observe.

Unified processing loop that:
    1. Receives messages from MessageBus (any channel)
    2. Builds context (system prompt + memory + skills + tools)
    3. Calls LLM provider (with streaming)
    4. Executes tool calls if needed (bounded iteration)
    5. Publishes response back to MessageBus
"""

import asyncio
import logging
import time
from typing import Any

from trio.core.bus import InboundMessage, OutboundMessage, StreamChunk, MessageBus
from trio.core.config import get_agent_defaults, get_workspace_dir
from trio.core.context import build_system_prompt, build_messages
from trio.core.memory import MemoryStore
from trio.core.session import Session, SessionManager
from trio.providers.base import BaseProvider, LLMResponse
from trio.shared.guardrails import check_input, filter_output
from trio.shared.think_parser import ThinkTagParser
from trio.tools.base import ToolRegistry

logger = logging.getLogger(__name__)


class AgentLoop:
    """Main agent loop — processes messages from any channel."""

    def __init__(
        self,
        bus: MessageBus,
        sessions: SessionManager,
        memory: MemoryStore,
        provider: BaseProvider,
        tools: ToolRegistry,
        config: dict,
    ):
        self.bus = bus
        self.sessions = sessions
        self.memory = memory
        self.provider = provider
        self.tools = tools
        self.config = config

        defaults = get_agent_defaults(config)
        self.max_iterations = defaults.get("max_iterations", 20)
        self.memory_window = defaults.get("memory_window", 20)
        self.default_model = defaults.get("model", "llama3.1:8b")

        # Per-user state
        self._user_modes: dict[str, str] = {}          # session_key → mode
        self._user_models: dict[str, str] = {}          # session_key → model override
        self._deep_thinking: dict[str, bool] = {}       # session_key → show thinking
        self._running = True

        # Load workspace files
        self._soul_content = self._load_workspace_file("SOUL.md")
        self._user_context = self._load_workspace_file("USER.md")

    async def run(self) -> None:
        """Main loop — consume inbound messages and process them."""
        logger.info("Agent loop started")
        while self._running:
            msg = await self.bus.consume_inbound(timeout=1.0)
            if msg is None:
                continue
            try:
                await self._process_message(msg)
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                await self.bus.publish_outbound(OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=f"Sorry, an error occurred: {e}",
                ))

    def stop(self) -> None:
        self._running = False

    async def _process_message(self, msg: InboundMessage) -> None:
        """Process a single inbound message through the full pipeline."""
        session_key = msg.session_key
        start_time = time.time()

        # 1. Check for commands
        command_result = self._handle_command(msg)
        if command_result is not None:
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=command_result,
            ))
            return

        # 2. Guardrails — input check
        is_safe, warning, cleaned = check_input(msg.content, msg.user_id)
        if not is_safe:
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=warning or "I can't process that request.",
            ))
            return

        # 3. Get/create session
        session = self.sessions.get(session_key)
        session.add_message("user", cleaned)
        self.sessions.save_message(session_key, session.history[-1])

        # 4. Log to memory history
        self.memory.append_to_history(msg.channel, msg.user_id, "user", cleaned[:200])

        # 5. Build context
        mode = self._user_modes.get(session_key, "general")
        model = self._user_models.get(session_key, self.default_model)

        system_prompt = build_system_prompt(
            mode=mode,
            memory=self.memory,
            session=session,
            soul_content=self._soul_content,
            user_context=self._user_context,
            tool_schemas=self.tools.get_schemas() if self.tools.list_tools() else None,
        )

        messages = build_messages(session, system_prompt, max_history=self.memory_window)

        # 6. Agent loop — think + act with bounded iteration
        final_response = ""
        for iteration in range(self.max_iterations):
            # Check if provider supports tool calling
            has_tools = self.provider.supports_tools() and self.tools.list_tools()
            tool_schemas = self.tools.get_schemas() if has_tools else None

            # Generate response (streaming)
            accumulated = ""
            think_parser = ThinkTagParser() if mode == "reasoning" else None
            show_thinking = self._deep_thinking.get(session_key, False)

            async for chunk in self.provider.stream_generate(
                messages=messages,
                model=model,
                tools=tool_schemas,
            ):
                if chunk.text:
                    if think_parser:
                        thinking_delta, response_delta = think_parser.feed(chunk.text)
                        display_text = ""
                        if show_thinking and thinking_delta:
                            display_text += thinking_delta
                        if response_delta:
                            display_text += response_delta
                        accumulated += chunk.text
                        if display_text:
                            await self.bus.publish_outbound(StreamChunk(
                                channel=msg.channel,
                                chat_id=msg.chat_id,
                                chunk=display_text,
                                accumulated=accumulated,
                            ))
                    else:
                        accumulated += chunk.text
                        await self.bus.publish_outbound(StreamChunk(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            chunk=chunk.text,
                            accumulated=accumulated,
                        ))

                if chunk.is_final:
                    if think_parser:
                        think_parser.finish()
                    break

            # For non-tool-calling providers, we're done
            if not has_tools:
                final_response = accumulated
                break

            # Check for tool calls in response
            # For now, use the accumulated text as the response
            # Tool calling via OpenAI-compat providers returns structured tool_calls
            # which we handle via the non-streaming path
            final_response = accumulated
            break  # TODO: implement tool call loop for tool-calling providers

        # 7. Guardrails — output check
        output_result = filter_output(final_response)
        final_text = output_result.filtered_text

        # 8. Append stats
        duration = time.time() - start_time
        if final_text and not final_text.startswith("Error:"):
            stats = f"\n\n_({duration:.1f}s | {model})_"
            final_text += stats

        # 9. Send final response
        await self.bus.publish_outbound(OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_text,
            is_final=True,
        ))

        # 10. Save to session
        if final_response:
            clean_response = ThinkTagParser.strip_think_tags(final_response) if mode == "reasoning" else final_response
            session.add_message("assistant", clean_response)
            self.sessions.save_message(session_key, session.history[-1])
            self.memory.append_to_history(msg.channel, msg.user_id, "assistant", clean_response[:200])

        # 11. Check if memory consolidation needed
        if session.message_count > self.memory_window * 2:
            old_messages = session.history[:-self.memory_window]
            await self.memory.consolidate(old_messages, self.provider)
            session.history = session.history[-self.memory_window:]
            self.sessions.save_session(session)

    def _handle_command(self, msg: InboundMessage) -> str | None:
        """Handle bot commands. Returns response string or None if not a command."""
        text = msg.content.strip()
        session_key = msg.session_key

        # Normalize command prefix
        cmd = text.lower()
        if cmd.startswith("/") or cmd.startswith("!"):
            cmd = cmd[1:]
        else:
            return None  # Not a command

        parts = cmd.split(None, 1)
        command = parts[0] if parts else ""
        arg = parts[1].strip() if len(parts) > 1 else ""

        if command in ("chat", "general"):
            self._user_modes[session_key] = "general"
            return "Switched to **General** mode."

        elif command in ("coder", "code", "coding"):
            self._user_modes[session_key] = "coding"
            return "Switched to **Coding** mode."

        elif command in ("think", "reason", "reasoning"):
            self._user_modes[session_key] = "reasoning"
            return "Switched to **Reasoning** mode."

        elif command == "reset":
            self.sessions.delete(session_key)
            self._user_modes.pop(session_key, None)
            self._user_models.pop(session_key, None)
            return "Conversation reset."

        elif command == "setmodel":
            if arg:
                self._user_models[session_key] = arg
                return f"Model set to **{arg}**."
            return "Usage: /setmodel <model_name>"

        elif command == "model":
            model = self._user_models.get(session_key, self.default_model)
            mode = self._user_modes.get(session_key, "general")
            return f"Current model: **{model}** | Mode: **{mode}**"

        elif command == "models":
            return "Use `/models` to list available models (fetching...)"

        elif command == "deepthink":
            current = self._deep_thinking.get(session_key, False)
            self._deep_thinking[session_key] = not current
            state = "ON" if not current else "OFF"
            return f"Deep thinking display: **{state}**"

        elif command == "help":
            return (
                "**trio Commands:**\n"
                "/chat — General mode\n"
                "/coder — Coding mode\n"
                "/think — Reasoning mode\n"
                "/reset — Clear conversation\n"
                "/setmodel <name> — Set custom model\n"
                "/model — Show current model\n"
                "/deepthink — Toggle reasoning display\n"
                "/help — Show this help"
            )

        return None  # Not a recognized command, process as message

    def _load_workspace_file(self, filename: str) -> str | None:
        """Load a workspace file (SOUL.md, USER.md, etc.)."""
        workspace = get_workspace_dir()
        path = workspace / filename
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except Exception:
                pass
        return None
