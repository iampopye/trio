"""Context builder — assembles system prompt + memory + skills + tools for the LLM."""

import time
from typing import Any

from trio.core.memory import MemoryStore
from trio.core.session import Session
from trio.shared.context_analyzer import analyze_context


DEFAULT_SYSTEM_PROMPT = (
    "You are trio, a helpful AI assistant. You are friendly, concise, and knowledgeable. "
    "Answer questions clearly and provide helpful information. "
    "If you don't know something, say so honestly."
)

MODE_PROMPTS = {
    "general": DEFAULT_SYSTEM_PROMPT,
    "coding": (
        "You are trio in coding mode. You are an expert software engineer. "
        "Write clean, efficient, well-documented code. Explain your reasoning. "
        "Use best practices and modern patterns. If asked to debug, identify the root cause first."
    ),
    "reasoning": (
        "You are trio in reasoning mode. Think step by step through problems. "
        "Break complex questions into smaller parts. Show your reasoning process. "
        "Use <think>...</think> tags to show your internal reasoning before giving the final answer."
    ),
}


def build_system_prompt(
    mode: str = "general",
    memory: MemoryStore | None = None,
    session: Session | None = None,
    soul_content: str | None = None,
    user_context: str | None = None,
    tool_schemas: list[dict] | None = None,
    skill_prompts: list[str] | None = None,
) -> str:
    """Build the complete system prompt for the LLM.

    Assembles from:
        1. Soul (personality) — from SOUL.md or mode prompt
        2. User context — from USER.md
        3. Memory — from MEMORY.md (long-term facts)
        4. Conversation analysis — from context_analyzer
        5. Tool descriptions — from tool schemas
        6. Skill instructions — from loaded skills
    """
    parts = []

    # 1. Soul / personality
    if soul_content:
        parts.append(soul_content)
    else:
        parts.append(MODE_PROMPTS.get(mode, DEFAULT_SYSTEM_PROMPT))

    # 2. User context
    if user_context:
        parts.append(f"\n## About the User\n{user_context}")

    # 3. Long-term memory
    if memory:
        mem_content = memory.read_memory()
        if mem_content and len(mem_content) > 50:  # Skip if just the header
            parts.append(f"\n## Your Memory\n{mem_content}")

    # 4. Conversation analysis
    if session and session.history:
        context = analyze_context(session.history)
        if context:
            context_lines = []
            if context.get("topic"):
                context_lines.append(f"Topic: {context['topic']}")
            if context.get("conversation_type") and context["conversation_type"] != "general":
                context_lines.append(f"Conversation type: {context['conversation_type']}")
            if context.get("key_entities"):
                context_lines.append(f"Key subjects: {', '.join(context['key_entities'][:5])}")
            if context.get("referent"):
                context_lines.append(f'"it"/"that" likely refers to: {context["referent"]}')
            if context_lines:
                parts.append("\n## Conversation Context\n" + "\n".join(f"- {l}" for l in context_lines))

    # 5. Tool descriptions
    if tool_schemas:
        tool_list = []
        for schema in tool_schemas:
            func = schema.get("function", {})
            tool_list.append(f"- **{func.get('name', '?')}**: {func.get('description', '')}")
        if tool_list:
            parts.append("\n## Available Tools\n" + "\n".join(tool_list))

    # 6. Skill instructions
    if skill_prompts:
        for skill in skill_prompts:
            parts.append(f"\n{skill}")

    # 7. Current date
    parts.append(f"\nCurrent date: {time.strftime('%Y-%m-%d')}")

    return "\n\n".join(parts)


def build_messages(
    session: Session,
    system_prompt: str,
    max_history: int = 20,
) -> list[dict]:
    """Build the full message list for the LLM.

    Returns:
        [{"role": "system", "content": ...}, {"role": "user", ...}, ...]
    """
    messages = [{"role": "system", "content": system_prompt}]

    # Add recent conversation history
    recent = session.get_recent(max_history)
    for msg in recent:
        messages.append({
            "role": msg["role"],
            "content": msg["content"],
        })

    return messages
