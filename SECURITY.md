# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in trio.ai, please report it responsibly.

**Do NOT open a public issue.**

Instead, email: **karangarg.dev@gmail.com**

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

You will receive a response within 48 hours. We take security seriously and will work with you to address the issue before any public disclosure.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | Yes       |
| 0.1.x   | Security fixes only |

## Scope

This policy covers:
- The trio agent framework (`trio/`)
- The trio model engine (`trio_model/`)
- The CLI tool and all built-in tools
- The web UI and API server (`trio serve`)
- The inference server
- Channel integrations (Discord, Telegram, Slack, etc.)
- Plugin and skill loading systems

## Security Architecture

trio.ai implements a multi-layer security model:

### 1. Web API Authentication
- API key authentication required for remote access (auto-generated at `~/.trio/api_key`)
- Local requests (127.0.0.1) bypass auth by default for developer convenience
- Per-IP rate limiting (60 requests/minute)
- Security headers: X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, CSP
- CORS restricted to configured origins (localhost by default)

### 2. Secrets Encryption
- All tokens, API keys, and passwords in `~/.trio/config.json` are encrypted at rest
- Machine-local encryption key stored in `~/.trio/.secret_key` (chmod 600)
- Encrypted values use `ENC:` prefix and are auto-decrypted on load

### 3. Shell Command Sandboxing
- Allowlist-based execution — only known-safe commands are permitted
- Dangerous pattern blocklist as a second defense layer
- Pipeline validation — every command in pipes/chains is checked
- Optional workspace restriction limits execution directory
- Timeout enforcement (max 120 seconds)

### 4. Plugin Integrity Verification
- SHA-256 checksum verification for plugins
- Tampered plugins are rejected — tools will not load if checksum fails
- Plugin manifests include author and version metadata

### 5. Input/Output Guardrails (5 layers)
- **Input filtering**: Prompt injection and jailbreak detection
- **Output filtering**: Prevents leakage of internal architecture, API keys, infrastructure
- **Content safety**: Blocks harmful content categories
- **Rate limiting**: Per-user probe attack detection (3 attempts → 30-min block)
- **Operational limits**: Input length caps, output truncation

### 6. File Upload Security
- File extension allowlist (documents, code, images only)
- 50 MB size limit
- Path traversal prevention (filename sanitization)
- Content-hash prefixed filenames to prevent collisions

### 7. DM Pairing Security
- Cryptographic pairing codes for channel authentication
- Per-channel user allowlists
- 1-hour TTL on pairing requests

## Responsible Disclosure

We kindly ask that you:
- Give us reasonable time to fix the issue before public disclosure
- Do not exploit the vulnerability beyond what is necessary to demonstrate it
- Do not access or modify other users' data

## Known Limitations

- Config encryption uses XOR-based obfuscation with a local key — it prevents casual reading but is not equivalent to a hardware security module. For production deployments with high-security requirements, use environment variables or a dedicated secrets manager.
- Shell tool allowlist may need expansion for specific workflows — users can extend it in their deployment.
- Web API auth is bearer-token based; for internet-facing deployments, use a reverse proxy with TLS.
