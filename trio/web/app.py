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

from trio.core.config import load_config
from trio.core.loop import AgentLoop

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


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
    config = request.app["config"]

    # Get or create agent loop for this session
    sessions = request.app["sessions"]
    if session_id not in sessions:
        loop = AgentLoop(config)
        sessions[session_id] = {"loop": loop, "history": []}

    session = sessions[session_id]
    session["history"].append({"role": "user", "content": message})

    try:
        response = await session["loop"].step(message, history=session["history"])
        content = response if isinstance(response, str) else str(response)
    except Exception as e:
        logger.error(f"Agent error: {e}")
        content = f"Error: {e}"

    session["history"].append({"role": "assistant", "content": content})

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
    config = request.app["config"]

    sessions = request.app["sessions"]
    if session_id not in sessions:
        loop = AgentLoop(config)
        sessions[session_id] = {"loop": loop, "history": []}

    session = sessions[session_id]
    session["history"].append({"role": "user", "content": message})

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

    try:
        full_response = await session["loop"].step(message, history=session["history"])
        content = full_response if isinstance(full_response, str) else str(full_response)

        # Send as chunks for streaming feel
        chunk_size = 4
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i + chunk_size]
            event = f"data: {json.dumps({'text': chunk})}\n\n"
            await resp.write(event.encode("utf-8"))
            await asyncio.sleep(0.02)

        await resp.write(f"data: {json.dumps({'done': True})}\n\n".encode("utf-8"))
    except Exception as e:
        await resp.write(f"data: {json.dumps({'error': str(e)})}\n\n".encode("utf-8"))

    session["history"].append({"role": "assistant", "content": content})
    return resp


async def api_status(request):
    """GET /api/status -- system info."""
    config = request.app["config"]
    return web.json_response({
        "status": "running",
        "provider": config.get("provider", "local"),
        "model": config.get("model", "trio-max"),
        "sessions": len(request.app["sessions"]),
        "version": "0.1.0",
    })


async def api_sessions_clear(request):
    """POST /api/sessions/clear -- clear all sessions."""
    request.app["sessions"].clear()
    return web.json_response({"status": "cleared"})


# ── App Factory ──────────────────────────────────────────────────────────────

def create_app(config: dict | None = None) -> web.Application:
    """Create the aiohttp web application."""
    app = web.Application()
    app["config"] = config or load_config()
    app["sessions"] = {}

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
