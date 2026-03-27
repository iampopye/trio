"""trio.ai web UI -- browser-based chat interface with full dashboard.

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
CONFIG_PATH = Path.home() / ".trio" / "config.json"

SYSTEM_PROMPT = (
    "You are trio-max, an advanced AI assistant created by trio.ai. "
    "You are helpful, accurate, and thorough. You can help with coding, "
    "writing, analysis, math, search, and general questions. "
    "Keep responses clear and well-formatted using markdown."
)


def _load_workspace_prompt():
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
    provider_name = config.get("provider", "local")
    if provider_name == "local":
        from trio.providers.local import LocalProvider
        pc = config.get("providers", {}).get("local", {})
        pc.setdefault("default_model", "trio-max")
        return LocalProvider(pc)
    elif provider_name in ("ollama", "trio"):
        from trio.providers.ollama import OllamaProvider
        return OllamaProvider(config.get("providers", {}).get("ollama", {}))
    else:
        from trio.providers.local import LocalProvider
        return LocalProvider(config.get("providers", {}).get("local", {}))


def _save_config(config: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


# ── Chat Routes ──────────────────────────────────────────────────────────────

async def index(request):
    return web.FileResponse(STATIC_DIR / "index.html")


async def api_chat(request):
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
    messages = [{"role": "system", "content": system_prompt}] + history[-20:]

    try:
        response = await provider.generate(messages=messages)
        content = response.content or "I couldn't generate a response."
    except Exception as e:
        content = f"Error: {e}"

    history.append({"role": "assistant", "content": content})
    return web.json_response({"response": content, "session_id": session_id})


async def api_chat_stream(request):
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
    messages = [{"role": "system", "content": system_prompt}] + history[-20:]

    resp = web.StreamResponse(
        status=200, reason="OK",
        headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache",
                 "Connection": "keep-alive", "X-Session-Id": session_id},
    )
    await resp.prepare(request)

    content = ""
    try:
        async for chunk in provider.stream_generate(messages=messages):
            if chunk.text:
                content += chunk.text
                await resp.write(f"data: {json.dumps({'text': chunk.text})}\n\n".encode())
            if chunk.is_final:
                break
        await resp.write(f"data: {json.dumps({'done': True})}\n\n".encode())
    except Exception as e:
        content = f"Error: {e}"
        await resp.write(f"data: {json.dumps({'error': str(e)})}\n\n".encode())

    history.append({"role": "assistant", "content": content})
    return resp


async def api_sessions_clear(request):
    request.app["sessions"].clear()
    return web.json_response({"status": "cleared"})


async def api_upload(request):
    """POST /api/upload -- upload a file, extract text, return content."""
    reader = await request.multipart()
    field = await reader.next()

    if not field or field.name != "file":
        return web.json_response({"error": "No file uploaded"}, status=400)

    filename = field.filename or "unknown"
    data = await field.read()  # read full file

    from trio.web.file_handler import extract_text
    result = extract_text(data, filename)

    # Save to temp uploads dir
    uploads_dir = Path.home() / ".trio" / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    save_path = uploads_dir / filename
    save_path.write_bytes(data)
    result["saved_path"] = str(save_path)

    return web.json_response(result)


async def api_chat_with_file(request):
    """POST /api/chat/file -- send message with file context."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    message = data.get("message", "").strip()
    file_content = data.get("file_content", "")
    filename = data.get("filename", "")
    session_id = data.get("session_id", str(uuid.uuid4()))

    provider = request.app["provider"]
    system_prompt = request.app["system_prompt"]

    sessions = request.app["sessions"]
    if session_id not in sessions:
        sessions[session_id] = []

    history = sessions[session_id]

    # Build message with file context
    user_msg = message or f"I've uploaded a file: {filename}. Please analyze it."
    if file_content:
        user_msg = f"[Uploaded file: {filename}]\n\n```\n{file_content[:30000]}\n```\n\n{user_msg}"

    history.append({"role": "user", "content": user_msg})
    messages = [{"role": "system", "content": system_prompt}] + history[-20:]

    # Stream response
    resp = web.StreamResponse(
        status=200, reason="OK",
        headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache",
                 "Connection": "keep-alive"},
    )
    await resp.prepare(request)

    content = ""
    try:
        async for chunk in provider.stream_generate(messages=messages, max_tokens=2048):
            if chunk.text:
                content += chunk.text
                await resp.write(f"data: {json.dumps({'text': chunk.text})}\n\n".encode())
            if chunk.is_final:
                break
        await resp.write(f"data: {json.dumps({'done': True})}\n\n".encode())
    except Exception as e:
        content = f"Error: {e}"
        await resp.write(f"data: {json.dumps({'error': str(e)})}\n\n".encode())

    history.append({"role": "assistant", "content": content})
    return resp


# ── Status & Project ─────────────────────────────────────────────────────────

async def api_status(request):
    config = request.app["config"]
    return web.json_response({
        "status": "running",
        "provider": config.get("provider", "local"),
        "model": config.get("model", "trio-max"),
        "sessions": len(request.app["sessions"]),
        "version": "0.1.1",
    })


async def api_project(request):
    try:
        from trio.core.sandbox import get_project_info, list_project_files
        info = get_project_info()
        info["files"] = list_project_files(max_depth=3)
        return web.json_response(info)
    except Exception as e:
        return web.json_response({
            "error": str(e), "root": os.getcwd(),
            "name": Path(os.getcwd()).name,
            "language": "unknown", "files_count": 0,
            "has_git": False, "files": [],
        })


# ── Skills ───────────────────────────────────────────────────────────────────

async def api_skills(request):
    """GET /api/skills -- list skills from triohub index."""
    category = request.query.get("category", "")
    search = request.query.get("q", "").lower()
    limit = int(request.query.get("limit", "50"))
    offset = int(request.query.get("offset", "0"))

    index_path = Path(__file__).resolve().parent.parent.parent / "triohub" / "index.json"
    if not index_path.exists():
        return web.json_response({"skills": [], "total": 0, "categories": {}})

    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return web.json_response({"skills": [], "total": 0, "categories": {}})

    # Index has categories as list with nested skills
    categories_list = data.get("categories", [])
    cat_counts = {}
    all_skills = []

    for cat in categories_list:
        cat_name = cat.get("name", "general")
        cat_skills = cat.get("skills", [])
        cat_counts[cat_name] = len(cat_skills)
        for s in cat_skills:
            s["category"] = cat_name
            all_skills.append(s)

    # Filter
    skills = all_skills
    if category:
        skills = [s for s in skills if s.get("category") == category]
    if search:
        skills = [s for s in skills if search in s.get("name", "").lower()
                  or search in s.get("description", "").lower()
                  or any(search in t.lower() for t in s.get("tags", []))]

    total = len(skills)
    skills = skills[offset:offset + limit]

    return web.json_response({
        "skills": skills,
        "total": total,
        "categories": cat_counts,
    })


async def api_skill_install(request):
    """POST /api/skills/install -- install a skill by name."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    skill_name = data.get("name", "")
    if not skill_name:
        return web.json_response({"error": "Skill name required"}, status=400)

    # Find skill in index
    index_path = Path(__file__).resolve().parent.parent.parent / "triohub" / "index.json"
    if not index_path.exists():
        return web.json_response({"error": "TrioHub index not found"}, status=404)

    try:
        idx = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return web.json_response({"error": "Failed to read index"}, status=500)

    # Search in all categories
    skill = None
    for cat in idx.get("categories", []):
        for s in cat.get("skills", []):
            if s["name"] == skill_name:
                skill = s
                skill["category"] = cat.get("name", "general")
                break
        if skill:
            break

    if not skill:
        return web.json_response({"error": f"Skill '{skill_name}' not found"}, status=404)

    # Install: copy skill file to user's ~/.trio/skills/
    skills_dir = Path.home() / ".trio" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    src = Path(__file__).resolve().parent.parent / "skills" / "builtin" / skill.get("file", "")
    installed_path = skills_dir / skill.get("file", f"{skill_name}.md")

    if src.exists():
        installed_path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        # Create skill stub if source not bundled
        installed_path.write_text(
            f"---\nname: {skill_name}\ndescription: {skill.get('description', '')}\n"
            f"tags: {skill.get('tags', [])}\ncategory: {skill.get('category', 'general')}\n---\n\n"
            f"# {skill.get('description', skill_name)}\n\n"
            f"Installed from TrioHub.\n",
            encoding="utf-8",
        )

    # Track installed skills in config
    config = request.app["config"]
    installed = config.setdefault("installed_skills", [])
    if skill_name not in installed:
        installed.append(skill_name)
        _save_config(config)

    return web.json_response({
        "status": "installed",
        "name": skill_name,
        "path": str(installed_path),
        "category": skill.get("category", ""),
    })


async def api_skills_installed(request):
    """GET /api/skills/installed -- list installed skills."""
    config = request.app["config"]
    installed_names = config.get("installed_skills", [])

    skills_dir = Path.home() / ".trio" / "skills"
    installed = []
    if skills_dir.is_dir():
        for f in sorted(skills_dir.glob("*.md")):
            installed.append({
                "name": f.stem,
                "file": f.name,
                "path": str(f),
                "size": f.stat().st_size,
            })

    return web.json_response({
        "installed": installed,
        "count": len(installed),
    })


async def api_skill_uninstall(request):
    """POST /api/skills/uninstall -- remove an installed skill."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    skill_name = data.get("name", "")
    skills_dir = Path.home() / ".trio" / "skills"
    removed = False

    for ext in (".md", ".py", ".yaml"):
        path = skills_dir / f"{skill_name}{ext}"
        if path.exists():
            path.unlink()
            removed = True

    config = request.app["config"]
    installed = config.get("installed_skills", [])
    if skill_name in installed:
        installed.remove(skill_name)
        _save_config(config)

    return web.json_response({"status": "removed" if removed else "not_found", "name": skill_name})


# ── Tools ────────────────────────────────────────────────────────────────────

async def api_tools(request):
    """GET /api/tools -- list tools with enabled status."""
    config = request.app["config"]
    enabled = config.get("tools", {}).get("builtin", [])

    all_tools = [
        {"key": "shell", "name": "Shell", "desc": "Execute commands in sandbox directory"},
        {"key": "file_ops", "name": "File Operations", "desc": "Read, write, list files within project"},
        {"key": "browser", "name": "Browser", "desc": "Navigate, click, fill, screenshot via Playwright"},
        {"key": "web_search", "name": "Web Search", "desc": "Search the internet via DuckDuckGo"},
        {"key": "rag_search", "name": "RAG Search", "desc": "Semantic search over local documents"},
        {"key": "code_analysis", "name": "Code Analysis", "desc": "AST parsing, linting, dependency checking"},
        {"key": "screenshot", "name": "Screenshot", "desc": "Capture screen regions"},
        {"key": "email", "name": "Email", "desc": "Send and receive emails via SMTP/IMAP"},
        {"key": "calculator", "name": "Calculator", "desc": "Math and symbolic computation"},
        {"key": "delegate", "name": "Delegate", "desc": "Spawn sub-agents for complex tasks"},
        {"key": "mcp_client", "name": "MCP Client", "desc": "Connect to external MCP tool servers"},
        {"key": "memory", "name": "Memory", "desc": "Store and recall info across sessions"},
    ]

    for t in all_tools:
        t["enabled"] = t["key"] in enabled

    return web.json_response({"tools": all_tools})


async def api_tools_toggle(request):
    """POST /api/tools/toggle -- enable/disable a tool."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    key = data.get("key", "")
    enabled = data.get("enabled", True)

    config = request.app["config"]
    tools_config = config.setdefault("tools", {})
    builtin = tools_config.setdefault("builtin", [])

    if enabled and key not in builtin:
        builtin.append(key)
    elif not enabled and key in builtin:
        builtin.remove(key)

    _save_config(config)
    return web.json_response({"status": "ok", "key": key, "enabled": enabled})


# ── Channels ─────────────────────────────────────────────────────────────────

async def api_channels(request):
    """GET /api/channels -- list channels with config status."""
    config = request.app["config"]
    channels_cfg = config.get("channels", {})

    all_channels = [
        {"key": "cli", "name": "CLI", "desc": "Terminal interface", "tag": "built-in", "configurable": False},
        {"key": "web", "name": "Web UI", "desc": "Browser interface", "tag": "built-in", "configurable": False},
        {"key": "discord", "name": "Discord", "desc": "discord.py bot", "tag": "popular", "configurable": True, "fields": ["bot_token"]},
        {"key": "telegram", "name": "Telegram", "desc": "Telegram bot", "tag": "popular", "configurable": True, "fields": ["bot_token"]},
        {"key": "slack", "name": "Slack", "desc": "Slack Bolt app", "tag": "popular", "configurable": True, "fields": ["bot_token", "app_token"]},
        {"key": "whatsapp", "name": "WhatsApp", "desc": "Business API", "tag": "enterprise", "configurable": True, "fields": ["api_token", "phone_number_id"]},
        {"key": "teams", "name": "Teams", "desc": "Microsoft Teams", "tag": "enterprise", "configurable": True, "fields": ["app_id", "app_password"]},
        {"key": "signal", "name": "Signal", "desc": "Signal messenger", "tag": "secure", "configurable": True, "fields": ["phone_number"]},
        {"key": "matrix", "name": "Matrix", "desc": "Matrix/Element", "tag": "open", "configurable": True, "fields": ["homeserver", "access_token"]},
        {"key": "sms", "name": "SMS", "desc": "Twilio messaging", "tag": "mobile", "configurable": True, "fields": ["account_sid", "auth_token", "phone_number"]},
        {"key": "instagram", "name": "Instagram", "desc": "Instagram DM", "tag": "social", "configurable": True, "fields": ["access_token", "page_id"]},
        {"key": "messenger", "name": "Messenger", "desc": "Facebook Messenger", "tag": "social", "configurable": True, "fields": ["access_token", "verify_token"]},
        {"key": "line", "name": "LINE", "desc": "LINE platform", "tag": "asia", "configurable": True, "fields": ["channel_secret", "channel_access_token"]},
        {"key": "reddit", "name": "Reddit", "desc": "Reddit via PRAW", "tag": "social", "configurable": True, "fields": ["client_id", "client_secret", "username", "password"]},
        {"key": "email", "name": "Email", "desc": "IMAP / SMTP", "tag": "classic", "configurable": True, "fields": ["imap_host", "smtp_host", "username", "password"]},
        {"key": "google_chat", "name": "Google Chat", "desc": "Google Workspace", "tag": "enterprise", "configurable": True, "fields": ["service_account_key"]},
        {"key": "rest_api", "name": "REST API", "desc": "HTTP gateway", "tag": "developer", "configurable": True, "fields": ["port", "api_key"]},
    ]

    for ch in all_channels:
        ch_cfg = channels_cfg.get(ch["key"], {})
        ch["enabled"] = ch_cfg.get("enabled", ch["key"] in ("cli", "web"))
        ch["configured"] = bool(ch_cfg.get("bot_token") or ch_cfg.get("access_token")
                                or ch_cfg.get("api_token") or ch_cfg.get("account_sid")
                                or not ch.get("configurable", True))

    return web.json_response({"channels": all_channels})


async def api_channels_toggle(request):
    """POST /api/channels/toggle -- enable/disable a channel."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    key = data.get("key", "")
    enabled = data.get("enabled", True)

    config = request.app["config"]
    channels = config.setdefault("channels", {})
    ch = channels.setdefault(key, {})
    ch["enabled"] = enabled

    _save_config(config)
    return web.json_response({"status": "ok", "key": key, "enabled": enabled})


async def api_channels_config(request):
    """POST /api/channels/config -- save channel configuration."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    key = data.get("key", "")
    fields = data.get("fields", {})

    config = request.app["config"]
    channels = config.setdefault("channels", {})
    ch = channels.setdefault(key, {})
    ch.update(fields)
    ch["enabled"] = True

    _save_config(config)
    return web.json_response({"status": "ok", "key": key})


async def api_channels_verify(request):
    """POST /api/channels/verify -- verify channel credentials are valid."""
    import aiohttp as aio_http

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    key = data.get("key", "")
    fields = data.get("fields", {})

    try:
        async with aio_http.ClientSession() as session:
            if key == "telegram":
                token = fields.get("bot_token", "")
                if not token:
                    return web.json_response({"valid": False, "error": "Bot token required"})
                async with session.get(f"https://api.telegram.org/bot{token}/getMe",
                                       ssl=False) as resp:
                    d = await resp.json()
                    if d.get("ok"):
                        bot = d["result"]
                        return web.json_response({
                            "valid": True,
                            "bot_name": bot.get("first_name"),
                            "bot_username": bot.get("username"),
                            "message": f"Connected as @{bot.get('username')}",
                        })
                    return web.json_response({"valid": False, "error": d.get("description", "Invalid token")})

            elif key == "discord":
                token = fields.get("bot_token", "")
                if not token:
                    return web.json_response({"valid": False, "error": "Bot token required"})
                async with session.get("https://discord.com/api/v10/users/@me",
                                       headers={"Authorization": f"Bot {token}"},
                                       ssl=False) as resp:
                    if resp.status == 200:
                        d = await resp.json()
                        # Generate invite link
                        invite = f"https://discord.com/api/oauth2/authorize?client_id={d['id']}&permissions=274877975552&scope=bot"
                        return web.json_response({
                            "valid": True,
                            "bot_name": d.get("username"),
                            "bot_id": d.get("id"),
                            "invite_url": invite,
                            "message": f"Connected as {d.get('username')}#{d.get('discriminator', '0')}",
                        })
                    return web.json_response({"valid": False, "error": "Invalid bot token"})

            elif key == "slack":
                bot_token = fields.get("bot_token", "")
                if not bot_token:
                    return web.json_response({"valid": False, "error": "Bot token (xoxb-) required"})
                async with session.post("https://slack.com/api/auth.test",
                                        headers={"Authorization": f"Bearer {bot_token}"},
                                        ssl=False) as resp:
                    d = await resp.json()
                    if d.get("ok"):
                        return web.json_response({
                            "valid": True,
                            "team": d.get("team"),
                            "bot_name": d.get("user"),
                            "message": f"Connected to {d.get('team')} as {d.get('user')}",
                        })
                    return web.json_response({"valid": False, "error": d.get("error", "Auth failed")})

            elif key == "whatsapp":
                # WhatsApp Business API verification
                token = fields.get("access_token", "")
                phone_id = fields.get("phone_number_id", "")
                if not token or not phone_id:
                    return web.json_response({"valid": False, "error": "Access token and phone number ID required"})
                url = f"https://graph.facebook.com/v18.0/{phone_id}"
                async with session.get(url, headers={"Authorization": f"Bearer {token}"},
                                       ssl=False) as resp:
                    if resp.status == 200:
                        d = await resp.json()
                        return web.json_response({
                            "valid": True,
                            "phone": d.get("display_phone_number", phone_id),
                            "message": f"Connected: {d.get('display_phone_number', phone_id)}",
                        })
                    return web.json_response({"valid": False, "error": "Invalid credentials"})

            elif key == "reddit":
                client_id = fields.get("client_id", "")
                client_secret = fields.get("client_secret", "")
                username = fields.get("username", "")
                password = fields.get("password", "")
                if not all([client_id, client_secret, username, password]):
                    return web.json_response({"valid": False, "error": "All 4 fields required"})
                auth = aio_http.BasicAuth(client_id, client_secret)
                async with session.post("https://www.reddit.com/api/v1/access_token",
                                        auth=auth,
                                        data={"grant_type": "password", "username": username, "password": password},
                                        headers={"User-Agent": "trio.ai/0.1"},
                                        ssl=False) as resp:
                    d = await resp.json()
                    if "access_token" in d:
                        return web.json_response({"valid": True, "message": f"Connected as u/{username}"})
                    return web.json_response({"valid": False, "error": d.get("error", "Auth failed")})

            else:
                # Generic: just save config, no verification available
                return web.json_response({"valid": True, "message": "Configuration saved (no live verification for this channel)"})

    except Exception as e:
        return web.json_response({"valid": False, "error": str(e)})


# ── Models ───────────────────────────────────────────────────────────────────

async def api_models(request):
    """GET /api/models -- list available models."""
    from trio.providers.local import _list_gguf_models
    gguf = _list_gguf_models()

    config = request.app["config"]
    active = config.get("model", "trio-max")

    models = []
    for name in gguf:
        model_path = None
        for d in [Path.home() / ".trio" / "models",
                  Path(__file__).resolve().parent.parent.parent / "models"]:
            p = d / name
            if p.is_file():
                model_path = str(p)
                break
        size_mb = os.path.getsize(model_path) / (1024 * 1024) if model_path else 0
        models.append({
            "name": name,
            "size_mb": round(size_mb),
            "active": name.startswith(active.replace("-", "_")) or active in name,
            "path": model_path,
        })

    return web.json_response({"models": models, "active": active})


async def api_models_switch(request):
    """POST /api/models/switch -- switch active model."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    model = data.get("model", "")
    if not model:
        return web.json_response({"error": "Model name required"}, status=400)

    config = request.app["config"]
    config["model"] = model
    _save_config(config)

    # Reload provider with new model
    provider = request.app["provider"]
    if hasattr(provider, '_model'):
        provider._model = None  # Force reload on next request
        provider.default_model = model

    return web.json_response({"status": "ok", "model": model})


# ── Settings ─────────────────────────────────────────────────────────────────

async def api_settings(request):
    """GET /api/settings -- get current settings."""
    config = request.app["config"]
    return web.json_response({
        "sandbox": config.get("sandbox", True),
        "guardrails": config.get("guardrails", {}).get("enabled", True),
        "memory": config.get("memory", {}).get("enabled", True),
        "session_persistence": config.get("sessions", {}).get("persist", True),
        "deep_thinking": config.get("deep_thinking", False),
        "provider": config.get("provider", "local"),
        "model": config.get("model", "trio-max"),
    })


async def api_settings_update(request):
    """POST /api/settings -- update settings."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    config = request.app["config"]

    if "sandbox" in data:
        config["sandbox"] = data["sandbox"]
    if "guardrails" in data:
        config.setdefault("guardrails", {})["enabled"] = data["guardrails"]
    if "memory" in data:
        config.setdefault("memory", {})["enabled"] = data["memory"]
    if "session_persistence" in data:
        config.setdefault("sessions", {})["persist"] = data["session_persistence"]
    if "deep_thinking" in data:
        config["deep_thinking"] = data["deep_thinking"]
    if "provider" in data:
        config["provider"] = data["provider"]
    if "model" in data:
        config["model"] = data["model"]

    _save_config(config)
    return web.json_response({"status": "ok"})


# ── Sub-Agents ───────────────────────────────────────────────────────────────

async def api_agents(request):
    """GET /api/agents -- list sub-agents."""
    return web.json_response({"agents": [
        {"name": "researcher", "role": "Web search, browsing, RAG -- gathers and synthesizes information",
         "tools": ["web_search", "browser", "rag_search"], "max_iterations": 8},
        {"name": "coder", "role": "Shell commands, file operations -- writes, runs, and debugs code",
         "tools": ["shell", "file_ops"], "max_iterations": 10},
        {"name": "reviewer", "role": "Code review, bug detection, best practices -- read-only analysis",
         "tools": [], "max_iterations": 3},
        {"name": "planner", "role": "Task breakdown, architecture design, strategic planning",
         "tools": [], "max_iterations": 3},
        {"name": "summarizer", "role": "Condenses long documents, conversations, data into key points",
         "tools": [], "max_iterations": 2},
    ]})


# ── WhatsApp QR ──────────────────────────────────────────────────────────────

async def api_whatsapp_status(request):
    """GET /api/whatsapp/status -- get QR code or connection status."""
    from trio.channels.whatsapp_web import get_bridge_status, is_node_available
    port = request.app.get("wa_port", 28338)

    if not is_node_available():
        return web.json_response({
            "ready": False, "qr": None, "bridge_running": False,
            "error": "Node.js not installed. Install from https://nodejs.org",
        })

    status = await get_bridge_status(port)
    return web.json_response(status)


async def api_whatsapp_start(request):
    """POST /api/whatsapp/start -- start the WhatsApp bridge."""
    import subprocess as sp
    from trio.channels.whatsapp_web import _ensure_bridge, BRIDGE_DIR, BRIDGE_SCRIPT, SESSION_DIR, is_node_available

    if not is_node_available():
        return web.json_response({"error": "Node.js not installed"}, status=400)

    port = request.app.get("wa_port", 28338)

    # Check if already running
    from trio.channels.whatsapp_web import get_bridge_status
    status = await get_bridge_status(port)
    if status.get("bridge_running") or status.get("ready") or status.get("qr"):
        return web.json_response({"status": "already_running"})

    # Ensure bridge files exist
    has_modules = _ensure_bridge()

    if not has_modules:
        # Run npm install
        try:
            proc = await asyncio.create_subprocess_exec(
                "npm", "install", "--production",
                cwd=str(BRIDGE_DIR),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.wait(), timeout=120)
        except Exception as e:
            return web.json_response({"error": f"npm install failed: {e}"}, status=500)

    # Start bridge in background
    try:
        process = sp.Popen(
            ["node", str(BRIDGE_SCRIPT), str(SESSION_DIR), str(port)],
            cwd=str(BRIDGE_DIR),
            stdout=sp.DEVNULL, stderr=sp.DEVNULL,
            creationflags=sp.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )
        request.app["wa_process"] = process
        request.app["wa_port"] = port

        # Wait for bridge to start
        await asyncio.sleep(3)
        return web.json_response({"status": "started", "pid": process.pid, "port": port})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_whatsapp_logout(request):
    """POST /api/whatsapp/logout -- disconnect and clear session."""
    import aiohttp as aio_http
    port = request.app.get("wa_port", 28338)

    try:
        async with aio_http.ClientSession() as session:
            async with session.get(f"http://localhost:{port}/logout", timeout=aio_http.ClientTimeout(total=5)) as resp:
                await resp.json()
    except Exception:
        pass

    # Kill bridge process
    proc = request.app.get("wa_process")
    if proc:
        try:
            proc.terminate()
        except Exception:
            pass

    return web.json_response({"status": "logged_out"})


# ── App Factory ──────────────────────────────────────────────────────────────

def create_app(config: dict | None = None) -> web.Application:
    app = web.Application()
    cfg = config or load_config()
    app["config"] = cfg
    app["sessions"] = {}
    app["system_prompt"] = _load_workspace_prompt()
    app["provider"] = _create_provider(cfg)

    # Chat
    app.router.add_post("/api/chat", api_chat)
    app.router.add_post("/api/chat/stream", api_chat_stream)
    app.router.add_post("/api/chat/file", api_chat_with_file)
    app.router.add_post("/api/upload", api_upload)
    app.router.add_post("/api/sessions/clear", api_sessions_clear)

    # Status & Project
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/api/project", api_project)

    # Skills
    app.router.add_get("/api/skills", api_skills)
    app.router.add_get("/api/skills/installed", api_skills_installed)
    app.router.add_post("/api/skills/install", api_skill_install)
    app.router.add_post("/api/skills/uninstall", api_skill_uninstall)

    # Tools
    app.router.add_get("/api/tools", api_tools)
    app.router.add_post("/api/tools/toggle", api_tools_toggle)

    # Channels
    app.router.add_get("/api/channels", api_channels)
    app.router.add_post("/api/channels/toggle", api_channels_toggle)
    app.router.add_post("/api/channels/config", api_channels_config)
    app.router.add_post("/api/channels/verify", api_channels_verify)

    # Models
    app.router.add_get("/api/models", api_models)
    app.router.add_post("/api/models/switch", api_models_switch)

    # Settings
    app.router.add_get("/api/settings", api_settings)
    app.router.add_post("/api/settings", api_settings_update)

    # Sub-agents
    app.router.add_get("/api/agents", api_agents)

    # WhatsApp QR
    app.router.add_get("/api/whatsapp/status", api_whatsapp_status)
    app.router.add_post("/api/whatsapp/start", api_whatsapp_start)
    app.router.add_post("/api/whatsapp/logout", api_whatsapp_logout)

    # Static
    app.router.add_get("/", index)
    app.router.add_static("/static", STATIC_DIR, show_index=False)

    return app


def run_server(host: str = "0.0.0.0", port: int = 28337, config: dict | None = None):
    app = create_app(config)
    print(f"\n  trio.ai web UI")
    print(f"  ----------------------")
    print(f"  Local:   http://localhost:{port}")
    print(f"  Network: http://{host}:{port}")
    print(f"  Press Ctrl+C to stop\n")
    web.run_app(app, host=host, port=port, print=None)


if __name__ == "__main__":
    run_server()
