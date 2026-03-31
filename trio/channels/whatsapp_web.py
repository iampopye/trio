"""WhatsApp Web channel -- QR code pairing via whatsapp-web.js bridge.

Uses a small Node.js subprocess running whatsapp-web.js to handle
the WhatsApp Web multi-device protocol. The Python side manages
the lifecycle and message routing.

Requires: npm install whatsapp-web.js qrcode-terminal
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import json
import logging
import os
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

BRIDGE_DIR = Path.home() / ".trio" / "whatsapp-bridge"
BRIDGE_SCRIPT = BRIDGE_DIR / "bridge.js"
SESSION_DIR = BRIDGE_DIR / "session"

BRIDGE_JS = r"""
const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode');
const http = require('http');
const fs = require('fs');

const SESSION_DIR = process.argv[2] || './session';
const PORT = parseInt(process.argv[3] || '28338');

let currentQR = null;
let isReady = false;
let clientInfo = null;
let messageCallback = null;
let messageQueue = [];

const client = new Client({
    authStrategy: new LocalAuth({ dataPath: SESSION_DIR }),
    puppeteer: { headless: true, args: ['--no-sandbox', '--disable-setuid-sandbox'] }
});

client.on('qr', async (qr) => {
    currentQR = qr;
    isReady = false;
    const qrDataUrl = await qrcode.toDataURL(qr, { width: 280, margin: 2 });
    currentQR = qrDataUrl;
    console.log(JSON.stringify({ event: 'qr', data: qrDataUrl }));
});

client.on('ready', () => {
    isReady = true;
    currentQR = null;
    clientInfo = {
        name: client.info.pushname,
        phone: client.info.wid.user,
        platform: client.info.platform
    };
    console.log(JSON.stringify({ event: 'ready', data: clientInfo }));
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
    console.log(JSON.stringify({ event: 'message', data }));
});

client.on('disconnected', (reason) => {
    isReady = false;
    console.log(JSON.stringify({ event: 'disconnected', data: reason }));
});

// HTTP API for Python bridge
const server = http.createServer(async (req, res) => {
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') { res.writeHead(200); res.end(); return; }

    const url = new URL(req.url, `http://localhost:${PORT}`);

    if (url.pathname === '/status') {
        res.end(JSON.stringify({ ready: isReady, qr: currentQR, info: clientInfo }));
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
        res.end(JSON.stringify({ status: 'logged_out' }));
    }
    else {
        res.writeHead(404);
        res.end(JSON.stringify({ error: 'not found' }));
    }
});

server.listen(PORT, () => {
    console.log(JSON.stringify({ event: 'bridge_started', port: PORT }));
});

client.initialize();
""".strip()


def _ensure_bridge():
    """Install whatsapp-web.js bridge if not present."""
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    # Write bridge script
    BRIDGE_SCRIPT.write_text(BRIDGE_JS, encoding="utf-8")

    # Check if node_modules exists
    node_modules = BRIDGE_DIR / "node_modules"
    if not node_modules.exists():
        pkg = BRIDGE_DIR / "package.json"
        pkg.write_text(json.dumps({
            "name": "trio-whatsapp-bridge",
            "private": True,
            "dependencies": {
                "whatsapp-web.js": "^1.26.0",
                "qrcode": "^1.5.4"
            }
        }), encoding="utf-8")
        return False  # Need npm install
    return True


def is_node_available():
    """Check if Node.js is installed."""
    try:
        r = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5)  # nosec B603 B607
        return r.returncode == 0
    except Exception:
        return False


async def get_bridge_status(port=28338):
    """Get WhatsApp bridge status (QR code, connection state)."""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://localhost:{port}/status", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                return await resp.json()
    except Exception:
        return {"ready": False, "qr": None, "info": None, "bridge_running": False}
