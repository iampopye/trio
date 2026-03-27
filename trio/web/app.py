"""trio.ai web UI -- browser-based chat interface.

Run with:  trio serve
Or:        python -m trio.web.app
"""

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path

from aiohttp import web

from trio.core.config import load_config, get_workspace_dir

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

SYSTEM_PROMPT = (
    "You are trio-max, an advanced AI assistant created by trio.ai. "
    "You are helpful, accurate, and thorough. You can help with coding, "
    "writing, analysis, math, search, and general questions. "
    "Keep responses clear and well-formatted using markdown."
)


def _load_workspace_prompt():
    """Load SOUL.md and USER.md from workspace if available."""
    workspace = get_workspace_dir()
    parts = [SYSTEM_PROMPT]
    for fname in ("SOUL.md", "USER.md"):
        path = workspace / fname
        if path.exists():
            try:
                parts.append(path.read_text(encoding="utf-8"))
            except Exception:
                pass
    return "\n\n".join(parts)


def _create_provider(config: dict):
    """Create the appropriate LLM provider based on config."""
    provider_name = config.get("provider", "local")

    if provider_name == "local":
        from trio.providers.local import LocalProvider
        provider_config = config.get("providers", {}).get("local", {})
        provider_config.setdefault("default_model", "trio-max")
        return LocalProvider(provider_config)

    elif provider_name in ("ollama", "trio"):
        from trio.providers.ollama import OllamaProvider
        provider_config = config.get("providers", {}).get("ollama", {})
        return OllamaProvider(provider_config)

    elif provider_name == "openai":
        from trio.providers.openai import OpenAIProvider
        provider_config = config.get("providers", {}).get("openai", {})
        return OpenAIProvider(provider_config)

    else:
        # Fallback to local
        from trio.providers.local import LocalProvider
        return LocalProvider(config.get("providers", {}).get("local", {}))


# ── Routes ───────────────────────────────────────────────────────────────────

async def index(request):
    """Serve the main chat UI."""
    return web.FileResponse(STATIC_DIR / "index.html")


async def api_chat(request):
    """POST /api/chat -- send a message, get a response."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    message = data.get("message", "").strip()
    if not message:
        return web.json_response({"error": "Empty message"}, status=400)

    session_id = data.get("session_id", str(uuid.uuid4()))
    provider = request.app["provider"]
    system_prompt = request.app["system_prompt"]

    # Get or create session history
    sessions = request.app["sessions"]
    if session_id not in sessions:
        sessions[session_id] = []

    history = sessions[session_id]
    history.append({"role": "user", "content": message})

    # Build messages for LLM
    messages = [{"role": "system", "content": system_prompt}] + history[-20:]

    try:
        response = await provider.generate(messages=messages)
        content = response.content or "I couldn't generate a response."
    except Exception as e:
        logger.error(f"Provider error: {e}")
        content = f"Error: {e}"

    history.append({"role": "assistant", "content": content})

    return web.json_response({
        "response": content,
        "session_id": session_id,
    })


async def api_chat_stream(request):
    """POST /api/chat/stream -- SSE streaming response."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    message = data.get("message", "").strip()
    if not message:
        return web.json_response({"error": "Empty message"}, status=400)

    session_id = data.get("session_id", str(uuid.uuid4()))
    provider = request.app["provider"]
    system_prompt = request.app["system_prompt"]

    sessions = request.app["sessions"]
    if session_id not in sessions:
        sessions[session_id] = []

    history = sessions[session_id]
    history.append({"role": "user", "content": message})

    # Build messages for LLM
    messages = [{"role": "system", "content": system_prompt}] + history[-20:]

    resp = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Session-Id": session_id,
        },
    )
    await resp.prepare(request)

    content = ""
    try:
        async for chunk in provider.stream_generate(messages=messages):
            if chunk.text:
                content += chunk.text
                event = f"data: {json.dumps({'text': chunk.text})}\n\n"
                await resp.write(event.encode("utf-8"))
            if chunk.is_final:
                break

        await resp.write(f"data: {json.dumps({'done': True})}\n\n".encode("utf-8"))
    except Exception as e:
        logger.error(f"Stream error: {e}")
        error_msg = str(e)
        content = f"Error: {error_msg}"
        await resp.write(f"data: {json.dumps({'error': error_msg})}\n\n".encode("utf-8"))

    history.append({"role": "assistant", "content": content})
    return resp


async def api_status(request):
    """GET /api/status -- system info."""
    config = request.app["config"]
    return web.json_response({
        "status": "running",
        "provider": config.get("provider", "local"),
        "model": config.get("model", "trio-max"),
        "sessions": len(request.app["sessions"]),
        "version": "0.1.1",
    })


async def api_sessions_clear(request):
    """POST /api/sessions/clear -- clear all sessions."""
    request.app["sessions"].clear()
    return web.json_response({"status": "cleared"})


# ── App Factory ──────────────────────────────────────────────────────────────

def create_app(config: dict | None = None) -> web.Application:
    """Create the aiohttp web application."""
    app = web.Application()
    cfg = config or load_config()
    app["config"] = cfg
    app["sessions"] = {}
    app["system_prompt"] = _load_workspace_prompt()
    app["provider"] = _create_provider(cfg)

    # API routes
    app.router.add_post("/api/chat", api_chat)
    app.router.add_post("/api/chat/stream", api_chat_stream)
    app.router.add_get("/api/status", api_status)
    app.router.add_post("/api/sessions/clear", api_sessions_clear)

    # Static files and index
    app.router.add_get("/", index)
    app.router.add_static("/static", STATIC_DIR, show_index=False)

    return app


def run_server(host: str = "0.0.0.0", port: int = 3000, config: dict | None = None):
    """Start the web server."""
    app = create_app(config)
    print(f"\n  trio.ai web UI")
    print(f"  ----------------------")
    print(f"  Local:   http://localhost:{port}")
    print(f"  Network: http://{host}:{port}")
    print(f"  Press Ctrl+C to stop\n")
    web.run_app(app, host=host, port=port, print=None)


if __name__ == "__main__":
    run_server()
