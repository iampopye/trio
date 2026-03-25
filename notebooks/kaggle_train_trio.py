"""
TRIO.AI — Train trio-max on Kaggle Free T4 GPU
================================================

Upload this as a Kaggle notebook. Enable GPU (T4) in settings.
Automatically detects GPU VRAM and trains the largest model possible.

Expected results:
- T4 16GB → ~350-500M params → genuinely smart model
- Training time: 20-30 hours (within Kaggle's free 30hr/week quota)
- Output: trained checkpoint ready to deploy

Instructions:
1. Create new Kaggle notebook
2. Enable GPU: Settings → Accelerator → GPU T4 x2 (or T4)
3. Paste this entire file
4. Run all cells
5. Download the checkpoint from /kaggle/working/trio-max.pt
"""

# ── Cell 1: Setup ─────────────────────────────────────────────────────────────

import subprocess, sys, os

# Install dependencies
subprocess.run([sys.executable, "-m", "pip", "install", "-q",
    "torch", "tiktoken", "pyyaml", "numpy", "datasets", "huggingface_hub"])

# Clone trio repo
if not os.path.exists("/kaggle/working/trio"):
    subprocess.run(["git", "clone", "https://github.com/iampopye/trio.git", "/kaggle/working/trio"])

sys.path.insert(0, "/kaggle/working/trio")

import torch
import time
import math
import json
from pathlib import Path
from datasets import load_dataset
from torch.utils.data import DataLoader

print(f"PyTorch: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")
    print(f"VRAM: {torch.cuda.get_device_properties(0).total_mem / 1024**3:.1f}GB")

# ── Cell 2: Auto-detect best model size for this GPU ──────────────────────────

from trio_model.config import TrioConfig

def auto_config_for_gpu():
    """Create the largest config that fits in available VRAM."""
    if not torch.cuda.is_available():
        print("No GPU! Using nano config (CPU)")
        from trio_model.config import NanoConfig
        return NanoConfig()

    vram_gb = torch.cuda.get_device_properties(0).total_mem / 1024**3

    if vram_gb >= 30:
        # A100/H100 — go big
        print(f"GPU VRAM: {vram_gb:.0f}GB → Training ~1B param model")
        return TrioConfig(
            model_name="trio-max",
            vocab_size=50257,
            context_length=2048,
            d_model=2048,
            num_heads=16,
            num_layers=24,
            ff_dim=8192,
            num_kv_heads=8,
            batch_size=4,
            gradient_accumulation_steps=8,
            learning_rate=3e-5,
            max_iters=100000,
            warmup_iters=2000,
            device="cuda",
            dtype="bfloat16",
        )
    elif vram_gb >= 14:
        # T4 16GB — maximize with optimizations
        print(f"GPU VRAM: {vram_gb:.0f}GB → Training ~350M param model (FP16 + grad checkpoint)")
        return TrioConfig(
            model_name="trio-max",
            vocab_size=50257,
            context_length=1024,
            d_model=1024,
            num_heads=16,
            num_layers=20,
            ff_dim=4096,
            num_kv_heads=4,       # GQA for efficiency
            batch_size=4,
            gradient_accumulation_steps=8,  # effective batch = 32
            learning_rate=6e-5,
            max_iters=30000,
            warmup_iters=1000,
            device="cuda",
            dtype="float16",
        )
    else:
        # Smaller GPU
        print(f"GPU VRAM: {vram_gb:.0f}GB → Training ~125M param model")
        return TrioConfig(
            model_name="trio-max",
            vocab_size=50257,
            context_length=1024,
            d_model=768,
            num_heads=12,
            num_layers=12,
            ff_dim=3072,
            batch_size=8,
            gradient_accumulation_steps=4,
            learning_rate=1e-4,
            max_iters=50000,
            warmup_iters=2000,
            device="cuda",
            dtype="float16",
        )


cfg = auto_config_for_gpu()
params = cfg.num_parameters()
print(f"\nModel: {cfg.model_name}")
print(f"Parameters: {params/1e6:.0f}M")
print(f"Context: {cfg.context_length} tokens")
print(f"d_model: {cfg.d_model}, layers: {cfg.num_layers}, heads: {cfg.num_heads}")
print(f"Device: {cfg.device}, dtype: {cfg.dtype}")

# ── Cell 3: Download training data ───────────────────────────────────────────

DATA_DIR = Path("/kaggle/working/data")
DATA_DIR.mkdir(exist_ok=True)

print("\n[1/3] Downloading TinyStories...")
tinystories = load_dataset("roneneldan/TinyStories", split="train")
print(f"  Loaded {len(tinystories):,} stories")

# Write pretrain data
pretrain_path = DATA_DIR / "pretrain.txt"
if not pretrain_path.exists():
    with open(pretrain_path, "w", encoding="utf-8") as f:
        for i, row in enumerate(tinystories):
            if i >= 1_000_000:  # 1M stories for GPU training
                break
            text = row.get("text", "").strip()
            if text:
                f.write(text + "\n\n")
            if (i+1) % 200_000 == 0:
                print(f"  Wrote {i+1:,} stories...")
    print(f"  Pretrain: {pretrain_path.stat().st_size/1e6:.0f}MB")

# Also add trio skills if cloned
skills_txt = Path("/kaggle/working/trio/trio_model/data/train.txt")
if skills_txt.exists():
    with open(pretrain_path, "a", encoding="utf-8") as f:
        f.write(open(skills_txt, encoding="utf-8").read())
    print(f"  Added trio skills data")

print("\n[2/3] Downloading Alpaca-GPT4...")
alpaca = load_dataset("vicgalle/alpaca-gpt4", split="train")
print(f"  Loaded {len(alpaca):,} instruction pairs")

print("\n[3/3] Downloading Dolly-15K...")
dolly = load_dataset("databricks/databricks-dolly-15k", split="train")
print(f"  Loaded {len(dolly):,} instruction pairs")

# Merge SFT data
sft_path = DATA_DIR / "sft.jsonl"
if not sft_path.exists():
    count = 0
    with open(sft_path, "w", encoding="utf-8") as f:
        for row in alpaca:
            inst = row.get("instruction", "").strip()
            inp = row.get("input", "").strip()
            out = row.get("output", "").strip()
            if inst and out:
                prompt = f"{inst}\n\nInput: {inp}" if inp else inst
                f.write(json.dumps({"instruction": prompt, "response": out}) + "\n")
                count += 1
        for row in dolly:
            inst = row.get("instruction", "").strip()
            ctx = row.get("context", "").strip()
            resp = row.get("response", "").strip()
            if inst and resp:
                prompt = f"{inst}\n\nContext: {ctx}" if ctx else inst
                f.write(json.dumps({"instruction": prompt, "response": resp}) + "\n")
                count += 1
        # Add trio skills SFT
        skills_sft = Path("/kaggle/working/trio/trio_model/data/sft_data.jsonl")
        if skills_sft.exists():
            for line in open(skills_sft, encoding="utf-8"):
                f.write(line)
                count += 1
    print(f"  Total SFT pairs: {count:,}")

print("\nData ready!")

# ── Cell 4: Initialize tokenizer and datasets ────────────────────────────────

import tiktoken

# Use BPE tokenizer (GPT-2 compatible) for larger models
tokenizer = tiktoken.get_encoding("gpt2")
cfg.vocab_size = tokenizer.n_vocab
print(f"Tokenizer: BPE (GPT-2), vocab size: {cfg.vocab_size}")


class TextDatasetBPE(torch.utils.data.Dataset):
    """Pre-training dataset with BPE tokenizer."""
    def __init__(self, path, tokenizer, seq_len, max_tokens=None):
        text = open(path, encoding="utf-8").read()
        self.tokens = tokenizer.encode(text)
        if max_tokens:
            self.tokens = self.tokens[:max_tokens]
        self.seq_len = seq_len
        print(f"[Dataset] {len(self.tokens):,} tokens, {len(self)} sequences of length {seq_len}")

    def __len__(self):
        return max(1, (len(self.tokens) - 1) // self.seq_len)

    def __getitem__(self, idx):
        start = idx * self.seq_len
        end = start + self.seq_len + 1
        chunk = self.tokens[start:end]
        if len(chunk) < self.seq_len + 1:
            chunk = chunk + [0] * (self.seq_len + 1 - len(chunk))
        x = torch.tensor(chunk[:-1], dtype=torch.long)
        y = torch.tensor(chunk[1:], dtype=torch.long)
        return x, y


class SFTDatasetBPE(torch.utils.data.Dataset):
    """Instruction-following dataset with BPE tokenizer."""
    def __init__(self, path, tokenizer, seq_len):
        self.samples = []
        self.seq_len = seq_len
        for line in open(path, encoding="utf-8"):
            try:
                d = json.loads(line)
                inst = d.get("instruction", "")
                resp = d.get("response", "")
                if inst and resp:
                    text = f"### Instruction:\n{inst}\n\n### Response:\n{resp}"
                    tokens = tokenizer.encode(text)[:seq_len]
                    if len(tokens) > 20:
                        self.samples.append(tokens)
            except:
                continue
        print(f"[SFT Dataset] {len(self.samples):,} samples")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        tokens = self.samples[idx]
        if len(tokens) < self.seq_len:
            tokens = tokens + [0] * (self.seq_len - len(tokens))
        tokens = tokens[:self.seq_len]
        x = torch.tensor(tokens[:-1], dtype=torch.long)
        y = torch.tensor(tokens[1:], dtype=torch.long)
        return x, y


# ── Cell 5: Build model with optimizations ───────────────────────────────────

from trio_model.model.architecture import TrioModel

model = TrioModel(cfg)
param_count = sum(p.numel() for p in model.parameters())
print(f"\nModel created: {param_count/1e6:.1f}M parameters")

# Move to GPU with mixed precision
device = torch.device(cfg.device)
model = model.to(device)

# Enable gradient checkpointing for memory savings
if hasattr(model, 'gradient_checkpointing_enable'):
    model.gradient_checkpointing_enable()
    print("Gradient checkpointing: enabled")
else:
    # Manual gradient checkpointing for our architecture
    for block in model.blocks if hasattr(model, 'blocks') else []:
        if hasattr(block, 'use_checkpoint'):
            block.use_checkpoint = True
    print("Gradient checkpointing: manual")

# Mixed precision setup
use_amp = cfg.dtype in ("float16", "bfloat16")
dtype = torch.float16 if cfg.dtype == "float16" else torch.bfloat16 if cfg.dtype == "bfloat16" else torch.float32
scaler = torch.amp.GradScaler("cuda", enabled=(cfg.dtype == "float16"))
print(f"Mixed precision: {cfg.dtype} (AMP {'enabled' if use_amp else 'disabled'})")

# Memory stats
if torch.cuda.is_available():
    torch.cuda.reset_peak_memory_stats()
    print(f"GPU memory allocated: {torch.cuda.memory_allocated()/1024**3:.2f}GB")

# ── Cell 6: Pre-training ─────────────────────────────────────────────────────

print("\n" + "="*70)
print("  PHASE 1: PRE-TRAINING")
print("="*70)

# Load data
train_ds = TextDatasetBPE(str(pretrain_path), tokenizer, cfg.context_length, max_tokens=50_000_000)
train_loader = DataLoader(train_ds, batch_size=cfg.batch_size, shuffle=True, num_workers=2, pin_memory=True)

optimizer = torch.optim.AdamW(
    model.parameters(), lr=cfg.learning_rate,
    betas=(0.9, 0.95), weight_decay=0.1,
)

def get_lr(step, max_steps, max_lr, warmup):
    if step < warmup:
        return max_lr * step / warmup
    progress = (step - warmup) / max(1, max_steps - warmup)
    return max_lr * 0.1 + 0.5 * (max_lr - max_lr * 0.1) * (1 + math.cos(math.pi * progress))

pretrain_steps = cfg.max_iters
model.train()
train_iter = iter(train_loader)
start_time = time.time()
best_loss = float("inf")

SAVE_PATH = Path("/kaggle/working/trio-max.pt")

for step in range(pretrain_steps):
    lr = get_lr(step, pretrain_steps, cfg.learning_rate, cfg.warmup_iters)
    for pg in optimizer.param_groups:
        pg["lr"] = lr

    optimizer.zero_grad(set_to_none=True)
    accum_loss = 0.0

    for micro_step in range(cfg.gradient_accumulation_steps):
        try:
            x, y = next(train_iter)
        except StopIteration:
            train_iter = iter(train_loader)
            x, y = next(train_iter)

        x, y = x.to(device), y.to(device)

        with torch.amp.autocast("cuda", dtype=dtype, enabled=use_amp):
            _, loss = model(x, y)
            loss = loss / cfg.gradient_accumulation_steps

        scaler.scale(loss).backward()
        accum_loss += loss.item()

    scaler.unscale_(optimizer)
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    scaler.step(optimizer)
    scaler.update()

    if step % 100 == 0:
        elapsed = time.time() - start_time
        sps = (step + 1) / elapsed if elapsed > 0 else 0
        eta_hr = (pretrain_steps - step) / sps / 3600 if sps > 0 else 0
        mem = torch.cuda.max_memory_allocated() / 1024**3 if torch.cuda.is_available() else 0
        print(f"  Step {step:6d}/{pretrain_steps} | loss={accum_loss:.4f} | lr={lr:.2e} | "
              f"{sps:.1f} it/s | ETA: {eta_hr:.1f}hr | GPU: {mem:.1f}GB")

    # Save checkpoint every 2000 steps
    if step % 2000 == 0 and step > 0:
        ckpt = {"step": step, "phase": "pretrain", "val_loss": accum_loss,
                "model": model.state_dict(), "optimizer": optimizer.state_dict(),
                "config": cfg.__dict__}
        torch.save(ckpt, str(SAVE_PATH))
        print(f"  [Checkpoint saved at step {step}]")

        if accum_loss < best_loss:
            best_loss = accum_loss

pretrain_time = time.time() - start_time
print(f"\nPre-training done in {pretrain_time/3600:.1f} hours | Best loss: {best_loss:.4f}")

# ── Cell 7: SFT Fine-tuning ──────────────────────────────────────────────────

print("\n" + "="*70)
print("  PHASE 2: INSTRUCTION FINE-TUNING (SFT)")
print("="*70)

sft_ds = SFTDatasetBPE(str(sft_path), tokenizer, cfg.context_length)
sft_loader = DataLoader(sft_ds, batch_size=cfg.batch_size, shuffle=True, num_workers=2, pin_memory=True)

sft_lr = cfg.learning_rate * 0.1
sft_optimizer = torch.optim.AdamW(model.parameters(), lr=sft_lr, weight_decay=0.01)
sft_steps = min(5000, len(sft_ds) * 3 // cfg.batch_size)  # ~3 epochs

model.train()
sft_iter = iter(sft_loader)
sft_start = time.time()

for step in range(sft_steps):
    lr = get_lr(step, sft_steps, sft_lr, warmup=200)
    for pg in sft_optimizer.param_groups:
        pg["lr"] = lr

    sft_optimizer.zero_grad(set_to_none=True)
    accum_loss = 0.0

    for micro_step in range(cfg.gradient_accumulation_steps):
        try:
            x, y = next(sft_iter)
        except StopIteration:
            sft_iter = iter(sft_loader)
            x, y = next(sft_iter)

        x, y = x.to(device), y.to(device)

        with torch.amp.autocast("cuda", dtype=dtype, enabled=use_amp):
            _, loss = model(x, y)
            loss = loss / cfg.gradient_accumulation_steps

        scaler.scale(loss).backward()
        accum_loss += loss.item()

    scaler.unscale_(sft_optimizer)
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    scaler.step(sft_optimizer)
    scaler.update()

    if step % 100 == 0:
        elapsed = time.time() - sft_start
        sps = (step + 1) / elapsed if elapsed > 0 else 0
        eta_min = (sft_steps - step) / sps / 60 if sps > 0 else 0
        print(f"  Step {step:5d}/{sft_steps} | loss={accum_loss:.4f} | lr={lr:.2e} | ETA: {eta_min:.0f}min")

    if step % 1000 == 0 and step > 0:
        ckpt = {"step": pretrain_steps + step, "phase": "sft", "val_loss": accum_loss,
                "model": model.state_dict(), "config": cfg.__dict__}
        torch.save(ckpt, str(SAVE_PATH))
        print(f"  [Checkpoint saved]")

sft_time = time.time() - sft_start
print(f"\nSFT done in {sft_time/3600:.1f} hours")

# ── Cell 8: Save final checkpoint ────────────────────────────────────────────

print("\n" + "="*70)
print("  SAVING FINAL MODEL")
print("="*70)

total_steps = pretrain_steps + sft_steps
model.eval()

ckpt = {
    "step": total_steps,
    "val_loss": best_loss,
    "model": model.state_dict(),
    "config": cfg.__dict__,
}

torch.save(ckpt, str(SAVE_PATH))
size_mb = SAVE_PATH.stat().st_size / 1024**2

total_time = time.time() - start_time
print(f"Model saved: {SAVE_PATH} ({size_mb:.0f}MB)")
print(f"Total training time: {total_time/3600:.1f} hours")
print(f"Parameters: {param_count/1e6:.0f}M")
print(f"Steps: {total_steps} (pretrain: {pretrain_steps} + SFT: {sft_steps})")
print(f"Best loss: {best_loss:.4f}")

print(f"\n{'='*70}")
print(f"  DONE! Download trio-max.pt from /kaggle/working/")
print(f"  Then deploy it:")
print(f"")
print(f"  Windows:  copy trio-max.pt %USERPROFILE%\\.trio\\models\\trio-nano.pt")
print(f"  Mac/Linux: cp trio-max.pt ~/.trio/models/trio-nano.pt")
print(f"")
print(f"  Also copy to your repo: trio_model/checkpoints/trio-nano.pt")
print(f"  Then run: trio agent -m 'Hello'")
print(f"{'='*70}")

# ── Cell 9: Quick test ───────────────────────────────────────────────────────

print("\n[Quick test] Generating text...")
model.eval()
prompt = "### Instruction:\nExplain what Docker is.\n\n### Response:\n"
tokens = tokenizer.encode(prompt)
x = torch.tensor([tokens]).to(device)

with torch.no_grad(), torch.amp.autocast("cuda", dtype=dtype, enabled=use_amp):
    for _ in range(200):
        logits, _ = model(x[:, -cfg.context_length:])
        next_token = torch.multinomial(
            torch.softmax(logits[:, -1, :] / 0.7, dim=-1), num_samples=1
        )
        x = torch.cat([x, next_token], dim=1)

output = tokenizer.decode(x[0].tolist())
print(output[:1000])

# ── Cell 10: Upload to HuggingFace Hub ──────────────────────────────────────

# This makes the model auto-downloadable by anyone who installs trio.ai
# Users just run: pip install trio-ai && trio agent
# The model downloads automatically on first use.
#
# INSTRUCTIONS:
# 1. Get a HuggingFace token from https://huggingface.co/settings/tokens
# 2. Create a "Write" token
# 3. Uncomment the lines below and paste your token
# 4. Run this cell

# from huggingface_hub import HfApi, create_repo
#
# HF_TOKEN = "hf_YOUR_TOKEN_HERE"  # <-- paste your HuggingFace token
# REPO_ID = "iampopye/trio-max"
#
# # Create repo if it doesn't exist
# create_repo(REPO_ID, token=HF_TOKEN, exist_ok=True, repo_type="model")
#
# # Upload the checkpoint
# api = HfApi()
# api.upload_file(
#     path_or_fileobj=str(SAVE_PATH),
#     path_in_repo="trio-nano.pt",
#     repo_id=REPO_ID,
#     token=HF_TOKEN,
# )
#
# # Upload a model card
# model_card = f"""---
# license: mit
# tags:
#   - trio-ai
#   - transformer
#   - from-scratch
# ---
#
# # Trio-Max — Custom AI Model by Karan Garg
#
# A {param_count/1e6:.0f}M parameter transformer trained from scratch.
#
# - **Architecture**: Custom transformer with RoPE, SwiGLU, GQA
# - **Training data**: TinyStories + Alpaca-GPT4 + Dolly-15K
# - **Training**: {total_time/3600:.1f} hours on Kaggle T4 GPU
# - **Pre-training**: {pretrain_steps} steps
# - **SFT**: {sft_steps} steps on 67K+ instruction pairs
#
# ## Usage
#
# ```bash
# pip install trio-ai[model]
# trio agent -m "Hello"
# ```
#
# The model downloads automatically on first use.
#
# ## Created by
# Karan Garg — [github.com/iampopye/trio](https://github.com/iampopye/trio)
# """
#
# api.upload_file(
#     path_or_fileobj=model_card.encode(),
#     path_in_repo="README.md",
#     repo_id=REPO_ID,
#     token=HF_TOKEN,
# )
#
# print(f"\nModel uploaded to: https://huggingface.co/{REPO_ID}")
# print(f"Anyone who installs trio-ai will auto-download this model!")
