"""WhatsApp Web channel -- QR code pairing via whatsapp-web.js bridge.

Uses a small Node.js subprocess running whatsapp-web.js to handle
the WhatsApp Web multi-device protocol. The Python side manages
the lifecycle and message routing.

Bridge directory: ~/.trio/whatsapp-bridge/
Requires Node.js + npm (auto-installed dependencies).
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import atexit
import json
import logging
import os
import shutil
import signal
import subprocess  # nosec B404
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

BRIDGE_DIR = Path.home() / ".trio" / "whatsapp-bridge"
BRIDGE_SCRIPT = BRIDGE_DIR / "bridge.js"
SESSION_DIR = BRIDGE_DIR / "session"

# Track running bridge processes for cleanup
_bridge_processes: list = []

BRIDGE_JS = r"""
const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode');
const http = require('http');
const fs = require('fs');
const path = require('path');

const SESSION_DIR = process.argv[2] || path.join(__dirname, 'session');
const PORT = parseInt(process.argv[3] || '28338');

let currentQR = null;
let isReady = false;
let clientInfo = null;
let messageQueue = [];
let initError = null;

// Ensure session directory exists
if (!fs.existsSync(SESSION_DIR)) {
    fs.mkdirSync(SESSION_DIR, { recursive: true });
}

const client = new Client({
    authStrategy: new LocalAuth({ dataPath: SESSION_DIR }),
    puppeteer: {
        headless: true,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--no-first-run',
            '--disable-gpu'
        ]
    }
});

client.on('qr', async (qr) => {
    try {
        currentQR = await qrcode.toDataURL(qr, { width: 280, margin: 2 });
        isReady = false;
        initError = null;
        console.log(JSON.stringify({ event: 'qr', ts: Date.now() }));
    } catch (e) {
        console.error(JSON.stringify({ event: 'qr_error', error: e.message }));
    }
});

client.on('ready', () => {
    isReady = true;
    currentQR = null;
    initError = null;
    clientInfo = {
        name: client.info.pushname || 'Unknown',
        phone: client.info.wid.user,
        platform: client.info.platform
    };
    console.log(JSON.stringify({ event: 'ready', data: clientInfo }));
});

client.on('authenticated', () => {
    console.log(JSON.stringify({ event: 'authenticated' }));
});

client.on('auth_failure', (msg) => {
    initError = 'Authentication failed: ' + msg;
    console.log(JSON.stringify({ event: 'auth_failure', data: msg }));
});

client.on('message', async (msg) => {
    if (msg.fromMe) return;
    const data = {
        from: msg.from,
        body: msg.body,
        timestamp: msg.timestamp,
        type: msg.type,
        contact: msg.from.replace('@c.us', '')
    };
    messageQueue.push(data);
    // Keep queue bounded
    if (messageQueue.length > 500) messageQueue = messageQueue.slice(-250);
    console.log(JSON.stringify({ event: 'message', data }));
});

client.on('disconnected', (reason) => {
    isReady = false;
    clientInfo = null;
    console.log(JSON.stringify({ event: 'disconnected', data: reason }));
    // Re-initialize after disconnect
    setTimeout(() => {
        console.log(JSON.stringify({ event: 'reinitializing' }));
        client.initialize().catch(() => {});
    }, 5000);
});

// ── HTTP API ────────────────────────────────────────────────────────

const server = http.createServer(async (req, res) => {
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') { res.writeHead(200); res.end(); return; }

    const url = new URL(req.url, `http://localhost:${PORT}`);

    try {
        if (url.pathname === '/status') {
            res.end(JSON.stringify({
                ready: isReady,
                qr: currentQR,
                info: clientInfo,
                error: initError,
                bridge_running: true,
                uptime: process.uptime()
            }));
        }
        else if (url.pathname === '/qr') {
            // Return QR as base64 PNG (data URL)
            if (currentQR) {
                res.end(JSON.stringify({ qr: currentQR }));
            } else if (isReady) {
                res.end(JSON.stringify({ qr: null, message: 'Already connected' }));
            } else {
                res.end(JSON.stringify({ qr: null, message: 'Waiting for QR code...' }));
            }
        }
        else if (url.pathname === '/messages') {
            const msgs = [...messageQueue];
            messageQueue = [];
            res.end(JSON.stringify({ messages: msgs }));
        }
        else if (url.pathname === '/send' && req.method === 'POST') {
            let body = '';
            req.on('data', c => body += c);
            req.on('end', async () => {
                try {
                    const { to, message } = JSON.parse(body);
                    if (!to || !message) {
                        res.writeHead(400);
                        res.end(JSON.stringify({ error: 'Missing "to" or "message" field' }));
                        return;
                    }
                    if (!isReady) {
                        res.writeHead(503);
                        res.end(JSON.stringify({ error: 'WhatsApp not connected' }));
                        return;
                    }
                    const chatId = to.includes('@') ? to : to + '@c.us';
                    await client.sendMessage(chatId, message);
                    res.end(JSON.stringify({ sent: true }));
                } catch(e) {
                    res.writeHead(500);
                    res.end(JSON.stringify({ error: e.message }));
                }
            });
        }
        else if (url.pathname === '/logout') {
            try { await client.logout(); } catch(e) {}
            isReady = false;
            currentQR = null;
            clientInfo = null;
            initError = null;
            res.end(JSON.stringify({ status: 'logged_out' }));
        }
        else if (url.pathname === '/health') {
            res.end(JSON.stringify({ ok: true, pid: process.pid, uptime: process.uptime() }));
        }
        else {
            res.writeHead(404);
            res.end(JSON.stringify({ error: 'not found' }));
        }
    } catch (e) {
        res.writeHead(500);
        res.end(JSON.stringify({ error: e.message }));
    }
});

server.listen(PORT, '127.0.0.1', () => {
    console.log(JSON.stringify({ event: 'bridge_started', port: PORT, pid: process.pid }));
});

// Graceful shutdown
function shutdown() {
    console.log(JSON.stringify({ event: 'shutting_down' }));
    try { client.destroy(); } catch(e) {}
    server.close();
    process.exit(0);
}

process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
process.on('uncaughtException', (err) => {
    console.error(JSON.stringify({ event: 'uncaught_exception', error: err.message }));
});

client.initialize().catch((err) => {
    initError = err.message;
    console.error(JSON.stringify({ event: 'init_error', error: err.message }));
});
""".strip()

PACKAGE_JSON = {
    "name": "trio-whatsapp-bridge",
    "version": "1.0.0",
    "private": True,
    "description": "WhatsApp Web bridge for trio.ai",
    "dependencies": {
        "whatsapp-web.js": "^1.26.0",
        "qrcode": "^1.5.4",
    },
}


# ── Bridge lifecycle helpers ─────────────────────────────────────────


def _ensure_bridge() -> bool:
    """Create bridge JS file and package.json if they don't exist.

    Returns True if bridge files are ready (node_modules present).
    Returns False if npm install is still needed.
    """
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    # Always write the latest bridge script (allows upgrades)
    BRIDGE_SCRIPT.write_text(BRIDGE_JS, encoding="utf-8")

    # Write package.json (always overwrite to keep deps current)
    pkg_path = BRIDGE_DIR / "package.json"
    pkg_path.write_text(json.dumps(PACKAGE_JSON, indent=2), encoding="utf-8")

    # Check if node_modules exists and has the required packages
    node_modules = BRIDGE_DIR / "node_modules"
    wwjs = node_modules / "whatsapp-web.js"
    qrcode = node_modules / "qrcode"

    if node_modules.exists() and wwjs.exists() and qrcode.exists():
        return True

    return False


async def _ensure_node_modules(timeout: int = 180) -> tuple[bool, str]:
    """Run npm install if node_modules is missing.

    Returns (success: bool, message: str).
    """
    node_modules = BRIDGE_DIR / "node_modules"
    wwjs = node_modules / "whatsapp-web.js"
    qrcode_mod = node_modules / "qrcode"

    if node_modules.exists() and wwjs.exists() and qrcode_mod.exists():
        return True, "Dependencies already installed"

    # Make sure package.json exists
    pkg_path = BRIDGE_DIR / "package.json"
    if not pkg_path.exists():
        _ensure_bridge()

    if not is_npm_available():
        return False, "npm is not available on PATH. Install Node.js from https://nodejs.org"

    logger.info("Installing WhatsApp bridge dependencies via npm...")

    try:
        proc = await asyncio.create_subprocess_exec(
            "npm", "install", "--production", "--no-audit", "--no-fund",
            cwd=str(BRIDGE_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        if proc.returncode != 0:
            err_text = stderr.decode(errors="replace").strip()
            logger.error("npm install failed (rc=%d): %s", proc.returncode, err_text)
            return False, f"npm install failed: {err_text[:500]}"

        logger.info("npm install completed successfully")
        return True, "Dependencies installed"

    except asyncio.TimeoutError:
        logger.error("npm install timed out after %ds", timeout)
        return False, f"npm install timed out after {timeout}s"
    except FileNotFoundError:
        return False, "npm not found. Install Node.js from https://nodejs.org"
    except Exception as e:
        logger.error("npm install error: %s", e)
        return False, f"npm install error: {e}"


def is_node_available() -> bool:
    """Check if Node.js is installed and accessible on PATH."""
    try:
        r = subprocess.run(  # nosec B603 B607
            ["node", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            ver = r.stdout.strip()
            logger.debug("Node.js found: %s", ver)
            return True
        return False
    except Exception:
        return False


def is_npm_available() -> bool:
    """Check if npm is installed and accessible on PATH."""
    try:
        r = subprocess.run(  # nosec B603 B607
            ["npm", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def get_node_version() -> str | None:
    """Return the Node.js version string, or None if not installed."""
    try:
        r = subprocess.run(  # nosec B603 B607
            ["node", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


async def get_bridge_status(port: int = 28338) -> dict:
    """Get WhatsApp bridge status (QR code, connection state).

    Returns dict with keys: ready, qr, info, bridge_running, error
    """
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://127.0.0.1:{port}/status",
                timeout=aiohttp.ClientTimeout(total=3),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    data["bridge_running"] = True
                    return data
                return {
                    "ready": False, "qr": None, "info": None,
                    "bridge_running": True, "error": f"Bridge returned HTTP {resp.status}",
                }
    except Exception:
        return {
            "ready": False, "qr": None, "info": None,
            "bridge_running": False, "error": None,
        }


async def start_bridge(port: int = 28338) -> tuple[object | None, str]:
    """Start the WhatsApp bridge subprocess.

    Returns (process, message). process is None on failure.
    """
    if not is_node_available():
        return None, (
            "Node.js is not installed. "
            "Install Node.js from https://nodejs.org to enable WhatsApp QR scan."
        )

    # Check if already running
    status = await get_bridge_status(port)
    if status.get("bridge_running"):
        return None, "Bridge is already running"

    # Ensure bridge files exist
    _ensure_bridge()

    # Ensure dependencies
    ok, msg = await _ensure_node_modules()
    if not ok:
        return None, msg

    # Start the Node.js bridge process
    try:
        creation_flags = 0
        if os.name == "nt":
            creation_flags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

        process = subprocess.Popen(  # nosec B603 B607
            ["node", str(BRIDGE_SCRIPT), str(SESSION_DIR), str(port)],
            cwd=str(BRIDGE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
        )

        # Register for cleanup
        _bridge_processes.append(process)

        # Wait briefly for the bridge to start
        for _ in range(10):
            await asyncio.sleep(0.5)
            status = await get_bridge_status(port)
            if status.get("bridge_running"):
                logger.info("WhatsApp bridge started on port %d (pid=%d)", port, process.pid)
                return process, f"Bridge started on port {port}"

            # Check if process died
            if process.poll() is not None:
                stderr_out = ""
                try:
                    stderr_out = process.stderr.read().decode(errors="replace")[:500]
                except Exception:
                    pass
                return None, f"Bridge process exited immediately: {stderr_out}"

        # Process running but not responding yet - give it benefit of the doubt
        logger.warning("Bridge process running but /status not responding after 5s")
        return process, f"Bridge started on port {port} (still initializing)"

    except FileNotFoundError:
        return None, "Node.js not found on PATH. Install from https://nodejs.org"
    except Exception as e:
        logger.error("Failed to start bridge: %s", e)
        return None, f"Failed to start bridge: {e}"


async def stop_bridge(port: int = 28338, process=None) -> str:
    """Stop the WhatsApp bridge."""
    # Try graceful logout via HTTP first
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://127.0.0.1:{port}/logout",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                await resp.json()
    except Exception:
        pass  # nosec B110 -- best-effort

    # Terminate the process
    if process:
        try:
            process.terminate()
            # Give it a moment to shut down
            await asyncio.sleep(1)
            if process.poll() is None:
                process.kill()
        except Exception:
            pass  # nosec B110 -- best-effort

    return "Bridge stopped"


def cleanup_all_bridges():
    """Kill all tracked bridge processes. Called at interpreter exit."""
    for proc in _bridge_processes:
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass  # nosec B110


# Register cleanup at exit
atexit.register(cleanup_all_bridges)
