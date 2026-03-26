# trio.ai

> Your AI, everywhere.

**trio.ai** is an open-source AI agent framework. Train your own LLM, connect any provider (Ollama, OpenAI, Claude, Gemini), and deploy across CLI, Discord, Telegram, Slack, WhatsApp, Teams, and 16 more channels.

---

## Install

```bash
pip install trio-ai
trio onboard
```

That's it. Two commands. `trio onboard` auto-detects Ollama, lets you browse 1,900+ skills, and sets everything up.

Then start chatting:

```bash
trio agent
```

### From source

```bash
git clone https://github.com/iampopye/trio.git
cd trio
python install.py
trio onboard
```

> **Need Ollama?** Install from [ollama.com](https://ollama.com), then: `ollama pull llama3.2:1b`

---

## What It Does

```
You type --> trio agent --> AI responds (streaming, with tools, memory, guardrails)
```

trio connects to any LLM and adds:
- **12 built-in tools**: web search, browser, email, calendar, notes, shell, file ops, math, screenshot, RAG, URL reader, sub-agent delegation
- **1,900+ skills**: coding, marketing, DevOps, security, finance, data science, creative writing, sysadmin, web dev
- **Sub-agent system**: delegate tasks to specialized agents (researcher, coder, reviewer, planner, summarizer)
- **Persistent memory**: remembers facts across conversations
- **5-layer guardrails**: input/output filtering, jailbreak detection
- **17 chat channels**: CLI, Discord, Telegram, Signal, Slack, WhatsApp, Teams, Google Chat, iMessage, Matrix, SMS, Instagram, Messenger, LINE, Reddit, Email
- **TrioHub**: community skill/plugin registry with 1,900+ skills across 13 categories
- **Plugin system**: extend with your own tools and skills
- **Production daemon**: runs as a system service with auto-restart and health monitoring
- **Train your own model**: the only open-source agent framework with built-in LLM training

---

## Commands

```bash
trio onboard                # Interactive setup wizard (6 steps)
trio agent                  # Interactive chat
trio agent -m "hello"       # Single message
trio status                 # System overview
trio doctor                 # Diagnose issues
trio doctor --fix           # Auto-repair

trio gateway                # Start all chat channels
trio daemon start           # Run as background service
trio daemon install         # Auto-start on boot (systemd/launchd/Windows)
trio daemon status          # Health, uptime, channels

trio provider add           # Add LLM provider
trio pairing list           # Manage DM access
trio plugin list            # Manage plugins
trio skill list             # Browse installed skills
trio hub search "coding"    # Search TrioHub registry
trio skill install <name>   # Install from TrioHub

trio update                 # Self-update
trio train                  # Train your own model
```

---

## Providers

Works with **13+ LLM providers** out of the box:

| Provider | Setup |
|---|---|
| **Ollama** (local) | `ollama pull llama3.2:1b` -- auto-detected |
| **OpenAI** | API key |
| **Anthropic** (Claude) | API key |
| **Google** (Gemini) | API key |
| **Groq** | API key |
| **DeepSeek** | API key |
| **OpenRouter** | API key |
| **trio-max** (built-in) | Train your own -- no API needed |

---

## Chat Channels

Deploy your AI on any platform:

| Channel | Type |
|---|---|
| **CLI** | Built-in terminal chat |
| **Discord** | Bot with live message editing |
| **Telegram** | Bot with markdown support |
| **Signal** | Private messenger |
| **Slack** | Workspace bot (Socket Mode) |
| **WhatsApp** | Business API webhook |
| **Teams** | Bot Framework |
| **Google Chat** | Service account webhook |
| **iMessage** | macOS only (AppleScript) |
| **Matrix** | Element/Matrix rooms (matrix-nio) |
| **SMS** | Twilio API |
| **Instagram** | DM via Meta Graph API |
| **Messenger** | Facebook Messenger webhook |
| **LINE** | LINE Bot SDK |
| **Reddit** | Bot via PRAW |
| **Email** | IMAP receive / SMTP send |

Enable channels: `trio onboard` or edit `~/.trio/config.json`

---

## Sub-Agents

trio can delegate tasks to specialized sub-agents:

| Agent | Role | Tools |
|---|---|---|
| **researcher** | Web search, gather information | web_search, browser, RAG |
| **coder** | Write and debug code | shell, file_ops |
| **reviewer** | Review content for quality | none (LLM-only) |
| **planner** | Break tasks into steps | none (LLM-only) |
| **summarizer** | Condense long content | none (LLM-only) |

The main agent automatically delegates when a task benefits from specialization.

---

## TrioHub -- Community Registry

Browse and install skills from the community:

```bash
trio hub search "python"     # Search skills
trio hub trending            # Popular skills
trio skill install <name>    # Install a skill
trio skill list              # Your installed skills
```

**13 categories**: Coding (418), Web Dev (159), Marketing (163), Security (80), Finance (47), Data Science (102), Creative (79), SysAdmin (204), Education (25), Productivity (167), Legal (29), Health (21), General (415)

---

## Architecture

```
User --> Channel --> MessageBus --> AgentLoop
                                      |
                                      +--> Build Context (memory + skills + tools)
                                      +--> Call LLM (Ollama / OpenAI / Claude / local)
                                      +--> Execute Tools (if needed)
                                      +--> Delegate to Sub-Agents (if needed)
                                      +--> Guardrails Filter
                                      |
                                   Response --> MessageBus --> Channel --> User
```

---

## Project Structure

```
trio/
  trio/                     # Agent framework
    core/                   #   AgentLoop, MessageBus, Config, Memory, Sessions, SubAgents
    providers/              #   Ollama, OpenAI, Claude, Gemini, 10+ more
    channels/               #   17 channels (CLI, Discord, Telegram, Slack, WhatsApp, etc.)
    tools/                  #   12 tools (web, browser, email, calendar, notes, shell, etc.)
    skills/                 #   1,900+ markdown-based skills
    plugins/                #   Plugin system (loader, manager, manifest)
    hub/                    #   TrioHub community registry client
    cron/                   #   Daemon, heartbeat, scheduler
    shared/                 #   Guardrails, pairing security, context analyzer
    cli/                    #   13 CLI commands

  trio_model/               # LLM engine (train your own)
    model/                  #   Transformer (RoPE, GQA, RMSNorm, SwiGLU)
    training/               #   Pre-train, SFT, Constitutional AI
    inference/              #   FastAPI server + CLI

  triohub/                  # Community skill/plugin registry
    index.json              #   1,909 skills across 13 categories
```

---

## Train Your Own Model

```bash
pip install trio-ai[model]
trio train                  # Start training (pause/resume with Ctrl+C)
```

Or on Kaggle/Colab with GPU:
```bash
# Upload notebooks/kaggle_train_trio.ipynb
# Uses T4 GPU with Flash Attention + gradient checkpointing
```

| Config | Params | Hardware |
|---|---|---|
| **trio-max** | Auto | Any system -- auto-optimizes |
| nano | ~1M | CPU (4GB+ RAM) |
| small | ~125M | T4 GPU (16GB) |
| medium | ~350M+ | A100 / M2+ |

---

## Platform Support

| Platform | Status |
|---|---|
| Windows 10/11 | Full support (NVIDIA CUDA) |
| macOS Intel | Full support |
| macOS Apple Silicon | Full support (MPS Metal) |
| Ubuntu / Debian | Full support (CUDA, ROCm) |
| Fedora / Arch | Full support |
| WSL2 | Full support (CUDA passthrough) |

---

## License

MIT -- Karan Garg

---

*Built from scratch. Train it. Deploy it. Own it.*
