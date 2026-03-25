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
- **3 presets**: nano (~1M, CPU), small (~125M, T4 GPU), medium (~1B, A100)
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

### Option A: Agent Framework (use with Ollama or cloud LLMs)

```bash
pip install trio-ai
trio onboard          # Interactive setup wizard
trio agent            # Start chatting
```

### Option B: Train Your Own Model + Deploy

```bash
# Clone and install with model dependencies
git clone https://github.com/iampopye/trio.git
cd trio
pip install -e ".[model,serve]"

# Train nano model on CPU (takes hours, not days)
python -m trio_model.training.pretrain --preset nano

# Fine-tune on instructions
python -m trio_model.training.sft --preset nano

# Chat with your trained model
python -m trio_model.inference.server --preset nano --mode cli

# Or deploy as a multi-platform agent
trio onboard          # Select "trio" as provider
trio agent            # Chat using your own model
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

## Hardware Targets

| Config | Params | Hardware | Training Time |
|---|---|---|---|
| `nano` | ~1M | Any CPU / Mac Mini | Hours |
| `small` | ~125M | Kaggle T4 (free) / Colab | Days |
| `medium` | ~1B | RunPod A100 (40GB+) | Weeks |

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
