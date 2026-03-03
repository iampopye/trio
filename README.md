# 🤖 Trio AI

> A Claude-inspired language model built from scratch using PyTorch.

Trio is a decoder-only transformer language model with a Constitutional AI training pipeline. It is designed to be **helpful, honest, and harmless** — inspired by Anthropic's Claude. The architecture runs from a tiny 1M-parameter nano model (suitable for a Mac Mini with 4GB RAM) all the way up to a 1B-parameter medium model for cloud GPU training.

---

## Architecture Highlights

| Feature | Implementation |
|---|---|
| Architecture | Decoder-only Transformer |
| Positional Encoding | Rotary (RoPE) |
| Normalization | RMSNorm |
| Activation | SwiGLU |
| Attention | Multi-Head + optional Group Query Attention (GQA) |
| Alignment | Constitutional AI (CAI) self-critique loop |

---

## Project Structure

```
trio/
├── config.py                # Nano / Small / Medium presets
├── test_setup.py            # Quick validation script (run this first!)
├── requirements.txt
│
├── model/
│   ├── architecture.py      # TrioModel (full transformer)
│   └── attention.py         # MHA + RoPE + GQA
│
├── data/
│   ├── tokenizer.py         # CharTokenizer (nano) + tiktoken BPE (small/medium)
│   └── dataset.py           # Pretrain + SFT datasets
│
├── training/
│   ├── pretrain.py          # Pre-training loop
│   ├── sft.py               # Supervised fine-tuning
│   ├── cai.py               # Constitutional AI self-critique
│   └── constitution.md      # Trio's values & principles
│
├── inference/
│   └── server.py            # FastAPI REST server + CLI chat
│
└── configs/
    ├── nano.yaml            # Mac Mini / CPU (~1M params)
    ├── small.yaml           # Kaggle T4 (~125M params)
    └── medium.yaml          # RunPod A100 (~1B params)
```

---

## Quick Start

### 1. Install dependencies
```bash
python -m venv trio_env
source trio_env/bin/activate       # Mac/Linux
# trio_env\Scripts\activate        # Windows

pip install -r requirements.txt
```

### 2. Verify setup
```bash
python test_setup.py
```

### 3. Train Trio (nano — runs on CPU / Mac Mini)
```bash
python training/pretrain.py --preset nano
```

### 4. Fine-tune on instructions (SFT)
```bash
python training/sft.py --preset nano
```

### 5. Chat with Trio
```bash
# Interactive CLI
python inference/server.py --preset nano --mode cli

# REST API
python inference/server.py --preset nano --mode api
# Then open: http://localhost:8080/docs
```

---

## Training Pipeline (Claude-Inspired)

```
1. Pre-training     →  Learn language from raw text
2. SFT              →  Learn to follow instructions
3. Constitutional AI → Self-critique against principles
4. (Optional) RLHF  → Human preference fine-tuning
```

---

## Hardware Targets

| Config | Params | Hardware | Est. Train Time |
|---|---|---|---|
| `nano` | ~1M | Mac Mini / any CPU | Hours |
| `small` | ~125M | Kaggle T4 (free) | Days |
| `medium` | ~1B | RunPod A100 | Weeks |

---

## Roadmap

- [x] Transformer architecture (RoPE, SwiGLU, RMSNorm)
- [x] Tokenizer (char-level + BPE)
- [x] Pre-training loop
- [x] SFT instruction tuning
- [x] Constitutional AI self-critique
- [x] FastAPI inference server
- [ ] RLHF (reward model + PPO)
- [ ] Quantization (4-bit / 8-bit for Mac Mini inference)
- [ ] HuggingFace Hub upload
- [ ] Web UI (Gradio / Streamlit)

---

## License

MIT — build freely, give credit.

---

*Built with ❤️ from scratch. Trio v0.1.0*
