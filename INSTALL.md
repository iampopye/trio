# trio.ai — Installation Guide

trio.ai runs on Windows, macOS, Linux, and WSL2. This guide has step-by-step instructions for every platform, with a non-technical path for first-time users.

---

## Table of Contents

- [Quick Install (All Platforms)](#quick-install-all-platforms)
- [Non-Technical Setup](#non-technical-setup)
- [Windows](#windows)
- [macOS](#macos)
- [Linux (Ubuntu / Debian / Fedora / Arch)](#linux)
- [WSL2](#wsl2)
- [From Source](#from-source)
- [Optional Dependencies](#optional-dependencies)
- [Troubleshooting](#troubleshooting)

---

## Quick Install (All Platforms)

If you have Python 3.10+ installed:

```bash
pip install trio-ai
trio onboard
```

That's it. Skip to [First Run](#first-run) below.

---

## Non-Technical Setup

Never used Python before? Follow this path.

### Step 1 — Install Python

Pick your operating system:

- **Windows**: Download Python from [python.org/downloads](https://www.python.org/downloads/) and run the installer. **Important**: tick "Add Python to PATH" on the first screen.
- **macOS**: Open Terminal and paste:
  ```bash
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  brew install python@3.12
  ```
- **Linux**: Most distros already have Python. Verify with `python3 --version`.

### Step 2 — Install trio.ai

Open a terminal (Command Prompt on Windows, Terminal on Mac, your favourite shell on Linux) and run:

```bash
pip install trio-ai
```

You should see "Successfully installed trio-ai".

### Step 3 — Run the setup wizard

```bash
trio onboard
```

trio will guide you through:
1. Picking an LLM provider (Ollama for free local, or any cloud provider)
2. Downloading a model
3. Choosing chat channels
4. Installing your first skills

### Step 4 — Start chatting

```bash
trio agent
```

Or open the web UI:

```bash
trio serve
# Then visit http://localhost:28337
```

**Stuck?** Run `trio doctor --fix` to auto-repair common issues.

---

## Windows

### Prerequisites
- Python 3.10 or newer ([python.org/downloads](https://www.python.org/downloads/))
- Visual Studio Build Tools (only if installing optional ML deps)

### Standard install

```powershell
pip install trio-ai
trio onboard
```

### With local model training

```powershell
pip install trio-ai[model]
```

This installs PyTorch, tiktoken, and other ML dependencies. Recommended for users with NVIDIA GPUs.

### With all features (channels, ML, web)

```powershell
pip install trio-ai[all]
```

### Windows-specific notes

- **PATH issues**: trio.ai auto-adds the Python Scripts folder to your PATH on first run. If `trio` isn't found, restart your terminal.
- **NVIDIA GPU**: Install CUDA Toolkit 12.x from [nvidia.com](https://developer.nvidia.com/cuda-downloads) for GPU acceleration.
- **WhatsApp channel**: Requires Node.js. Install from [nodejs.org](https://nodejs.org).

---

## macOS

### Prerequisites
- macOS 12 (Monterey) or newer
- Homebrew ([brew.sh](https://brew.sh))

### Install Python via Homebrew

```bash
brew install python@3.12
```

### Standard install

```bash
pip install trio-ai
trio onboard
```

### Apple Silicon (M1/M2/M3/M4)

trio.ai uses Metal Performance Shaders (MPS) for GPU acceleration on Apple Silicon. No extra setup needed.

```bash
pip install trio-ai[model]
trio train --setup    # Downloads MPS-optimized models
```

### Intel Macs

Standard install works. ML dependencies will use CPU mode unless an eGPU is connected.

---

## Linux

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv
pip install trio-ai
trio onboard
```

### Fedora / RHEL / CentOS

```bash
sudo dnf install -y python3 python3-pip
pip install trio-ai
trio onboard
```

### Arch / Manjaro

```bash
sudo pacman -S python python-pip
pip install trio-ai
trio onboard
```

### NVIDIA GPU support

```bash
# Install CUDA toolkit
sudo apt install nvidia-cuda-toolkit  # Ubuntu/Debian

# Install trio.ai with ML extras
pip install trio-ai[model]

# Verify GPU is detected
trio doctor
```

### AMD GPU support (ROCm)

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm6.0
pip install trio-ai[model]
```

---

## WSL2

WSL2 (Windows Subsystem for Linux) gives you a real Linux environment on Windows.

### Step 1 — Install WSL2

```powershell
wsl --install
```

Restart your machine when prompted.

### Step 2 — Install trio.ai inside WSL

Open the WSL terminal and run:

```bash
sudo apt update
sudo apt install -y python3 python3-pip
pip install trio-ai
trio onboard
```

### NVIDIA GPU passthrough

If you have an NVIDIA GPU, WSL2 can use it directly:

```bash
nvidia-smi    # Should show your GPU
pip install trio-ai[model]
trio doctor
```

---

## From Source

For developers who want to modify trio.ai:

```bash
git clone https://github.com/iampopye/trio.git
cd trio
python install.py
trio onboard
```

The `install.py` script:
1. Creates a virtual environment in `.venv/`
2. Installs trio.ai in editable mode (`pip install -e .`)
3. Adds the `trio` command to your PATH
4. Runs `trio doctor` to verify everything works

### Development install with all extras

```bash
git clone https://github.com/iampopye/trio.git
cd trio
python -m venv .venv
source .venv/bin/activate         # Linux/Mac
.venv\Scripts\activate            # Windows
pip install -e ".[all,dev]"
```

---

## Optional Dependencies

trio.ai uses optional dependency groups so you only install what you need.

```bash
pip install trio-ai                 # Minimal install (CLI + core)
pip install trio-ai[model]          # + Local model training (PyTorch)
pip install trio-ai[serve]          # + Web UI server (FastAPI)
pip install trio-ai[discord]        # + Discord channel
pip install trio-ai[telegram]       # + Telegram channel
pip install trio-ai[slack]          # + Slack channel
pip install trio-ai[teams]          # + Microsoft Teams channel
pip install trio-ai[whatsapp]       # + WhatsApp Business API
pip install trio-ai[search]         # + DuckDuckGo web search
pip install trio-ai[web]            # + Web scraping (BeautifulSoup, PyPDF2, Playwright)
pip install trio-ai[math]           # + Symbolic math (SymPy)
pip install trio-ai[screenshot]     # + Screen capture (mss, Pillow)
pip install trio-ai[all]            # Everything above
pip install trio-ai[dev]            # + Testing (pytest)
```

You can mix and match:

```bash
pip install trio-ai[discord,telegram,slack,model]
```

---

## First Run

After installation, run:

```bash
trio onboard
```

The wizard will:

1. **Detect your system** — checks Python version, GPU availability, RAM
2. **Pick a provider** — Ollama (free local), OpenAI, Claude, Gemini, etc.
3. **Download a model** — recommends the right tier for your hardware
4. **Configure channels** — optional, you can add them later
5. **Install starter skills** — picks 10-20 popular skills to get you started

Then start chatting:

```bash
trio agent                 # Terminal chat
trio serve                 # Browser UI
trio gateway               # All chat channels
```

---

## Troubleshooting

### `trio: command not found`

The Python Scripts/bin folder isn't on your PATH. Fixes:

**Windows**: Restart your terminal. trio.ai auto-adds the Scripts folder on first run.

**macOS/Linux**: Add to your shell profile:
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### `ModuleNotFoundError: No module named 'trio'`

You may have a conflicting `trio` async library installed. Remove it:

```bash
pip uninstall trio
pip install trio-ai
```

trio.ai uses the package name `triobot` on PyPI to avoid this conflict, but the import name is still `trio`.

### `Could not find Ollama`

Install Ollama from [ollama.com](https://ollama.com), then:

```bash
ollama pull llama3.2:1b
trio doctor
```

### Permission errors on Linux/macOS

Don't use `sudo pip install`. Use `pip install --user` or a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install trio-ai
```

### CUDA out of memory

Switch to a smaller model tier:

```bash
trio provider set --model trio-nano    # CPU-friendly, ~600 MB
trio provider set --model trio-small   # 1.2 GB
```

Or enable CPU offloading via Ollama:

```bash
ollama pull llama3.2:1b
trio provider set --provider ollama --model llama3.2:1b
```

### Auto-repair

```bash
trio doctor --fix
```

This auto-fixes most common issues.

---

## Verifying Your Install

```bash
trio --version              # Should show version 0.2.1 or newer
trio doctor                 # Should show all green checks
trio status                 # System overview
trio agent -m "hello"       # Quick functional test
```

If all four commands succeed, you're good to go.

---

## Updating trio.ai

```bash
trio update                  # Stable channel
trio update --channel beta   # Beta channel
```

Or use pip directly:

```bash
pip install --upgrade trio-ai
```

---

## Uninstalling

```bash
pip uninstall trio-ai
```

To also remove your data:

```bash
# Linux/Mac
rm -rf ~/.trio

# Windows PowerShell
Remove-Item -Recurse -Force $HOME\.trio
```

---

## Need Help?

- **GitHub Issues**: https://github.com/iampopye/trio/issues
- **Discussions**: https://github.com/iampopye/trio/discussions
- **Run** `trio help` for the complete command reference
