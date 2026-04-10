# trio.ai — Command Reference

This is the complete reference for every CLI command available in trio.ai. Run `trio help` from your terminal for an interactive version.

---

## Table of Contents

- [Setup & Diagnostics](#setup--diagnostics)
- [Chat & Agent](#chat--agent)
- [Models & Providers](#models--providers)
- [Skills](#skills)
- [Plugins](#plugins)
- [Channels & Daemon](#channels--daemon)
- [Training](#training)
- [Web UI](#web-ui)
- [Security & Pairing](#security--pairing)
- [Maintenance](#maintenance)
- [In-Chat Slash Commands](#in-chat-slash-commands)

---

## Setup & Diagnostics

### `trio onboard`
Run the interactive setup wizard. Auto-detects Ollama, downloads models, lets you browse skills, and configures channels.

```bash
trio onboard
```

### `trio help [command]`
Show all commands or detailed help for a specific command.

```bash
trio help                        # All commands grouped by category
trio help skill                  # Detailed help for "skill" command
trio help provider add           # Detailed help for a sub-command
```

### `trio doctor`
Diagnose system issues (missing dependencies, broken paths, provider connectivity).

```bash
trio doctor                      # Check system health
trio doctor --fix                # Auto-repair fixable issues
```

### `trio status`
Show a system overview: configured providers, enabled channels, installed skills, daemon health.

```bash
trio status
```

### `trio --version`
Print the installed version.

```bash
trio --version
```

---

## Chat & Agent

### `trio agent`
Start an interactive chat session in your terminal.

```bash
trio agent                       # Start interactive chat
trio agent -m "summarize this"   # Send a single message and exit
trio agent --no-markdown         # Plain text output (for piping)
trio agent --logs                # Show runtime logs alongside chat
```

**Inside the chat**, use these slash commands:
- `/help` — Show available slash commands
- `/provider` — Switch LLM provider
- `/model <name>` — Change model
- `/skill list` — List installed skills
- `/clear` — Clear chat history
- `/exit` — Exit the chat

---

## Models & Providers

### `trio provider list`
Show all configured providers and which one is active.

```bash
trio provider list
```

### `trio provider add`
Add a new LLM provider interactively.

```bash
trio provider add                # Interactive picker
```

Supports: OpenAI, Anthropic (Claude), Google (Gemini), Groq, DeepSeek, OpenRouter, Together AI, Ollama, GitHub Models, local trio-* models.

### `trio provider set`
Set the default provider and model.

```bash
trio provider set --provider ollama --model llama3.1:8b
trio provider set --model trio-max
trio provider set --provider openai --model gpt-4o
trio provider set --provider anthropic --model claude-opus-4-6
```

### `trio provider login`
OAuth login for providers that support it (e.g., GitHub Models).

```bash
trio provider login              # Interactive OAuth flow
```

### Built-in trio model tiers

| Command | What it does |
|---------|--------------|
| `trio provider set --model trio-nano` | Use the 1M-param model (CPU, 4GB RAM) |
| `trio provider set --model trio-small` | Use the 125M model (8GB RAM) |
| `trio provider set --model trio-medium` | Use the 350M model (GPU/Apple Silicon) |
| `trio provider set --model trio-high` | Use the 750M model (RTX 3060+) |
| `trio provider set --model trio-max` | Use the 3B model (RTX 4070+) |
| `trio provider set --model trio-pro` | Use the 30B MoE model (RTX 4090+) |

---

## Skills

### `trio skill list`
Show all installed skills.

```bash
trio skill list
trio skill list --category coding   # Filter by category
```

### `trio skill search`
Search the local skill index.

```bash
trio skill search "python debugger"
trio skill search "kubernetes"
```

### `trio skill install <name>`
Install a skill from the TrioHub community registry.

```bash
trio skill install python_debugger
trio skill install codex_review devops_toolkit  # Install multiple
```

### `trio skill remove <name>`
Remove an installed skill.

```bash
trio skill remove python_debugger
```

### `trio hub search "<query>"`
Search the full TrioHub registry (3,876 skills).

```bash
trio hub search "react"
trio hub search "data analysis"
```

### `trio hub trending`
Show the most popular skills in the community.

```bash
trio hub trending
trio hub trending --category coding
```

---

## Plugins

### `trio plugin list`
Show installed plugins.

```bash
trio plugin list
```

### `trio plugin install <path-or-url>`
Install a plugin from a local path or git URL.

```bash
trio plugin install ./my_plugin/
trio plugin install https://github.com/user/trio-plugin.git
```

### `trio plugin uninstall <name>`
Remove an installed plugin.

```bash
trio plugin uninstall my_plugin
```

### `trio plugin enable | disable <name>`
Toggle a plugin without uninstalling.

```bash
trio plugin enable my_plugin
trio plugin disable my_plugin
```

---

## Channels & Daemon

### `trio gateway`
Start all enabled channels in foreground (Ctrl+C to stop).

```bash
trio gateway
```

### `trio daemon install`
Install trio as a system service that auto-starts on boot.

```bash
trio daemon install              # systemd / launchd / Windows service
```

### `trio daemon` controls
```bash
trio daemon start                # Start the daemon
trio daemon stop                 # Stop the daemon
trio daemon restart              # Restart it
trio daemon status               # PID, uptime, channel health
trio daemon logs                 # Tail recent logs
trio daemon uninstall            # Remove the service
```

### `trio heartbeat`
Manage the heartbeat monitor (sends "I'm alive" pings).

```bash
trio heartbeat status
trio heartbeat log
trio heartbeat edit              # Edit ~/.trio/HEARTBEAT.md
```

---

## Training

### `trio train --setup`
Download pre-trained GGUF models and register them with Ollama.

```bash
trio train --setup
```

### `trio train`
Start training a model from scratch using your local data.

```bash
trio train                       # Resume from last checkpoint
trio train --reset               # Restart from scratch
```

Training auto-detects your hardware (CUDA/MPS/CPU) and picks the right config.

---

## Web UI

### `trio serve`
Start the browser-based chat UI.

```bash
trio serve                       # Default: http://localhost:28337
trio serve --port 8080           # Custom port
trio serve --host 0.0.0.0        # Listen on all interfaces (use with auth)
```

The web UI requires API key authentication for remote access. The key is auto-generated at `~/.trio/api_key` on first run.

---

## Security & Pairing

### `trio pairing list`
Show pairing status across channels.

```bash
trio pairing list
```

### `trio pairing pending`
Show pending DM pairing requests waiting for approval.

```bash
trio pairing pending
```

### `trio pairing approve <channel> <code>`
Approve a pairing request.

```bash
trio pairing approve discord ABC12345
trio pairing approve telegram XYZ98765
```

### `trio pairing revoke <channel> <user_id>`
Revoke a user's access to a channel.

```bash
trio pairing revoke discord 123456789
```

---

## Maintenance

### `trio update`
Update trio to the latest version.

```bash
trio update                      # Stable channel
trio update --channel beta       # Beta channel
trio update --channel nightly    # Nightly builds
```

---

## In-Chat Slash Commands

When you're inside `trio agent`, use these slash commands:

| Command | Description |
|---------|-------------|
| `/help` | Show all slash commands |
| `/provider` | Switch LLM provider with an interactive picker |
| `/model <name>` | Change model (e.g., `/model trio-max`) |
| `/skill list` | List installed skills |
| `/skill install <name>` | Install a skill from TrioHub |
| `/clear` | Clear chat history |
| `/save <name>` | Save current session |
| `/load <name>` | Load a saved session |
| `/exit` | Exit the chat |

---

## Environment Variables

trio.ai respects these environment variables (override `~/.trio/config.json`):

| Variable | Purpose |
|----------|---------|
| `TRIO_HOME` | Override `~/.trio` directory |
| `OPENAI_API_KEY` | OpenAI API key |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key |
| `GOOGLE_API_KEY` | Google Gemini API key |
| `GROQ_API_KEY` | Groq API key |
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `OLLAMA_HOST` | Ollama server URL (default: `http://localhost:11434`) |
| `FIRECRAWL_API_KEY` | Firecrawl API key (optional, for better web search) |

---

## Configuration File

trio.ai stores its configuration at `~/.trio/config.json`. Secrets (tokens, API keys, passwords) are automatically encrypted with AES-128 (Fernet).

```bash
trio doctor                      # Validate config
trio status                      # Show effective config
```

---

## Need More Help?

- **GitHub Issues**: https://github.com/iampopye/trio/issues
- **Discussions**: https://github.com/iampopye/trio/discussions
- **Security**: See [SECURITY.md](SECURITY.md)
- **Install Guide**: See [INSTALL.md](INSTALL.md)
- **Benchmarks**: See [BENCHMARKS.md](BENCHMARKS.md)
