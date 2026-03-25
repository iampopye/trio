# trio.ai

> Train your own AI. Deploy it everywhere.

**trio.ai** is a complete open-source AI platform that combines a trainable language model with a multi-platform agent framework. Train your own LLM from scratch, align it with Constitutional AI, and deploy it as an intelligent agent across CLI, Discord, Telegram, and Signal — all in one project.

---

## What Makes trio.ai Different

| Other tools | trio.ai |
|---|---|
| LangChain/CrewAI need external LLMs | **Train your own model** from scratch |
| Ollama just runs models | **Full agent** with tools, memory, channels |
| Open Interpreter needs API keys | Works **100% local** or with 13+ cloud providers |

---

## Features

### LLM Engine (`trio_model/`)
- **Decoder-only Transformer** built from scratch with PyTorch
- **RoPE** positional encoding, **RMSNorm**, **SwiGLU** activation
- **Grouped Query Attention (GQA)** for efficient inference
- **trio-max**: Auto-optimizes for your hardware (CPU, GPU, or cloud)
- **Constitutional AI** alignment (Anthropic-inspired self-critique)
- **FastAPI** inference server + CLI chat

### Agent Framework (`trio/`)
- **Multi-platform**: CLI, Discord, Telegram, Signal
- **13+ LLM providers**: Ollama, OpenAI, Claude, Gemini, DeepSeek, Groq, and more
- **Built-in Trio provider**: Use your own trained model as the agent backend
- **Tool system**: Web search, math solver, shell, file ops, RAG, MCP
- **Persistent memory**: Long-term facts, interaction history, daily notes
- **5-layer guardrails**: Input/output filtering, jailbreak detection, rate limiting
- **1,600+ built-in skills**: Coding, marketing, SEO, DevOps, data analysis, C-level advisory, security, testing, cloud, finance, and more
- **Extensible skill system**: Add your own skills as simple markdown files
- **Cron scheduler**: Recurring tasks

---

## Quick Start

```bash
pip install trio-ai
trio onboard          # One-time setup (select default)
trio agent            # Start chatting — trio-max auto-deploys
```

No API keys. No model downloads. No training. Just install and go.

### For Developers: Train Your Own Model

```bash
git clone https://github.com/iampopye/trio.git
cd trio
pip install -e ".[model,serve]"

# Train on your own data
python scripts/build_training_data.py
python scripts/train_default_model.py

# Or use the API server
python -m trio_model.inference.server --mode api
```

---

## Project Structure

```
trio.ai/
├── trio/                        # Agent Framework
│   ├── core/                    #   AgentLoop, MessageBus, Config, Memory, RAG
│   ├── providers/               #   Ollama, OpenAI, Claude, Gemini, Trio Local
│   ├── channels/                #   CLI, Discord, Telegram, Signal
│   ├── tools/                   #   Web search, math, shell, file ops, MCP
│   ├── skills/                  #   Markdown-based dynamic skills
│   ├── shared/                  #   Guardrails, context analyzer
│   └── cli/                     #   Onboard, agent, gateway, provider mgmt
│
├── trio_model/                  # LLM Engine
│   ├── model/                   #   TrioModel, RoPE, GQA, RMSNorm, SwiGLU
│   ├── data/                    #   Tokenizer (char + BPE), datasets
│   ├── training/                #   Pre-train, SFT, Constitutional AI
│   ├── inference/               #   FastAPI server + CLI chat
│   └── configs/                 #   nano.yaml, small.yaml, medium.yaml
│
└── workspace/                   # Agent personality & context
```

---

## Platform Support

| Platform | Status | GPU Acceleration |
|---|---|---|
| **Windows** 10/11 | Full support | NVIDIA CUDA |
| **macOS** (Intel) | Full support | — |
| **macOS** (Apple Silicon M1-M4) | Full support | MPS (Metal) |
| **Ubuntu / Debian** | Full support | NVIDIA CUDA, AMD ROCm |
| **Fedora / CentOS / RHEL** | Full support | NVIDIA CUDA, AMD ROCm |
| **Arch Linux** | Full support | NVIDIA CUDA, AMD ROCm |
| **WSL2** | Full support | NVIDIA CUDA (passthrough) |

## Hardware Targets

| Config | Params | Hardware | Training Time |
|---|---|---|---|
| **trio-max** | Auto | **Any system** — auto-optimizes | **Pre-trained** |
| Internal: nano | ~1M | CPU (4GB+ RAM) | Hours |
| Internal: small | ~125M | GPU (T4 16GB+ / Apple M1+) | Days |
| Internal: medium | ~1B | GPU (A100 40GB+ / M2 Ultra+) | Weeks |

---

## Training Pipeline

```
1. Pre-training      → Learn language from raw text
2. SFT               → Learn to follow instructions
3. Constitutional AI  → Self-critique against principles (helpful, honest, harmless)
4. Deploy as Agent    → Multi-platform with tools, memory, and guardrails
```

---

## CLI Commands

```bash
trio onboard              # Setup wizard (providers, channels, features)
trio agent                # Interactive chat
trio agent -m "message"   # Single message mode
trio gateway              # Start all enabled channels (Discord, Telegram, etc.)
trio provider list        # List configured LLM providers
trio provider add         # Add a new provider
trio status               # Show system status
```

---

## Architecture

```
User → Channel → MessageBus → AgentLoop
     → Build Context (memory + skills + tools)
     → Call LLM Provider (Trio local / Ollama / Cloud API)
     → Execute Tools (if needed)
     → Guardrails Filter
     → MessageBus → Channel → User
```

---

## Roadmap

- [x] Transformer architecture (RoPE, SwiGLU, RMSNorm, GQA)
- [x] Multi-platform agent framework
- [x] 13+ LLM provider integrations
- [x] 1,600+ built-in skills (largest open-source skill library)
- [x] Tool system with MCP support
- [x] Constitutional AI alignment
- [x] Persistent memory system
- [x] 5-layer safety guardrails
- [ ] RLHF (reward model + PPO)
- [ ] Model quantization (4-bit / 8-bit)
- [ ] Web UI dashboard
- [ ] HuggingFace Hub model upload
- [ ] Voice channel support

---

## License

MIT — Karan Garg

---

*Built from scratch. Train it. Deploy it. Own it.*
