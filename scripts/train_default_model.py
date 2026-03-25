"""Train the default trio-nano model on skills data — MAX POWER.

Uses all available CPU cores and RAM for fastest training.
Pre-trains on 11.5M chars of skills data + fine-tunes on 3,280 instruction pairs.
Saves trained checkpoint to ~/.trio/models/trio-nano.pt

Usage:
    python scripts/train_default_model.py
"""

import os
import sys
import time
import math
import json
from pathlib import Path
from contextlib import nullcontext

import torch

# Use all CPU cores
torch.set_num_threads(os.cpu_count() or 1)
torch.set_num_interop_threads(max(1, (os.cpu_count() or 1) // 2))

sys.path.insert(0, str(Path(__file__).parent.parent))

from trio_model.config import get_config
from trio_model.model.architecture import TrioModel
from trio_model.data.tokenizer import get_tokenizer
from trio_model.data.dataset import TextDataset, InstructionDataset
from torch.utils.data import DataLoader


def get_lr(step, max_iters, learning_rate, warmup_iters=200):
    """Cosine decay with linear warmup."""
    if step < warmup_iters:
        return learning_rate * step / warmup_iters
    if step > max_iters:
        return learning_rate * 0.1
    progress = (step - warmup_iters) / max(1, max_iters - warmup_iters)
    decay = 0.5 * (1.0 + math.cos(math.pi * progress))
    min_lr = learning_rate * 0.1
    return min_lr + decay * (learning_rate - min_lr)


def evaluate(model, val_loader, device, max_batches=30):
    """Run evaluation."""
    model.eval()
    losses = []
    with torch.no_grad():
        for i, (x, y) in enumerate(val_loader):
            if i >= max_batches:
                break
            x, y = x.to(device), y.to(device)
            _, loss = model(x, y)
            losses.append(loss.item())
    model.train()
    return sum(losses) / len(losses) if losses else float("inf")


def train():
    data_dir = Path(__file__).parent.parent / "trio_model" / "data"
    train_txt = data_dir / "train.txt"
    sft_jsonl = data_dir / "sft_data.jsonl"

    # Output to both repo (for bundling) and user dir
    repo_ckpt_dir = Path(__file__).parent.parent / "trio_model" / "checkpoints"
    repo_ckpt_dir.mkdir(parents=True, exist_ok=True)
    repo_output = repo_ckpt_dir / "trio-nano.pt"

    user_dir = Path.home() / ".trio" / "models"
    user_dir.mkdir(parents=True, exist_ok=True)
    user_output = user_dir / "trio-nano.pt"

    if not train_txt.exists():
        print("Training data not found. Run: python scripts/build_training_data.py")
        return

    # Config — push nano to its limits
    cfg = get_config("nano")
    tokenizer = get_tokenizer("nano")
    cfg.vocab_size = tokenizer.vocab_size
    device = torch.device(cfg.device)

    # Maximize batch size for available RAM
    cfg.batch_size = 16           # Larger batch = better gradients
    cfg.gradient_accumulation_steps = 2  # Effective batch = 32

    num_cores = os.cpu_count() or 1
    ram_gb = 0
    try:
        import psutil
        ram_gb = round(psutil.virtual_memory().total / (1024**3), 1)
    except ImportError:
        try:
            if sys.platform == "win32":
                import ctypes
                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                                ("ullTotalPhys", ctypes.c_ulonglong)] + [("_pad" + str(i), ctypes.c_ulonglong) for i in range(6)]
                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(stat)
                ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
                ram_gb = round(stat.ullTotalPhys / (1024**3), 1)
            elif sys.platform == "darwin":
                import subprocess
                result = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    ram_gb = round(int(result.stdout.strip()) / (1024**3), 1)
            else:
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            ram_gb = round(int(line.split()[1]) / (1024**2), 1)
                            break
        except Exception:
            ram_gb = 8

    print(f"\n{'='*60}")
    print(f"  TRIO.AI — Model Training (MAX POWER)")
    print(f"  CPU: {num_cores} cores | RAM: {ram_gb}GB")
    print(f"  PyTorch threads: {torch.get_num_threads()}")
    print(f"  Training data: {train_txt.stat().st_size / 1e6:.1f}MB")
    print(f"  SFT pairs: {sum(1 for _ in open(sft_jsonl, encoding='utf-8')) if sft_jsonl.exists() else 0}")
    print(f"  Batch size: {cfg.batch_size} x {cfg.gradient_accumulation_steps} = {cfg.batch_size * cfg.gradient_accumulation_steps}")
    print(f"{'='*60}\n")

    # ── Phase 1: Pre-training ──────────────────────────────────────
    print("[Phase 1/2] Pre-training on 11.5M chars of skills knowledge...")

    train_ds = TextDataset(str(train_txt), tokenizer, cfg.context_length, split="train")
    val_ds = TextDataset(str(train_txt), tokenizer, cfg.context_length, split="val")
    train_loader = DataLoader(train_ds, batch_size=cfg.batch_size, shuffle=True, num_workers=0, pin_memory=False)
    val_loader = DataLoader(val_ds, batch_size=cfg.batch_size, shuffle=False, num_workers=0)

    model = TrioModel(cfg).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=cfg.learning_rate,
        betas=(0.9, 0.95),
        weight_decay=0.1,
    )

    pretrain_steps = 5000  # Full training
    model.train()
    train_iter = iter(train_loader)
    best_loss = float("inf")
    start_time = time.time()

    for step in range(pretrain_steps):
        lr = get_lr(step, pretrain_steps, cfg.learning_rate, warmup_iters=300)
        for pg in optimizer.param_groups:
            pg["lr"] = lr

        optimizer.zero_grad(set_to_none=True)
        accum_loss = 0.0

        for _ in range(cfg.gradient_accumulation_steps):
            try:
                x, y = next(train_iter)
            except StopIteration:
                train_iter = iter(train_loader)
                x, y = next(train_iter)

            x, y = x.to(device), y.to(device)
            _, loss = model(x, y)
            loss = loss / cfg.gradient_accumulation_steps
            loss.backward()
            accum_loss += loss.item()

        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()

        if step % 50 == 0:
            elapsed = time.time() - start_time
            steps_per_sec = (step + 1) / elapsed if elapsed > 0 else 0
            eta_min = (pretrain_steps - step) / steps_per_sec / 60 if steps_per_sec > 0 else 0
            print(f"  Step {step:5d}/{pretrain_steps} | loss={accum_loss:.4f} | lr={lr:.2e} | {steps_per_sec:.1f} it/s | ETA: {eta_min:.0f}min")

        if step % 500 == 0 and step > 0:
            val_loss = evaluate(model, val_loader, device)
            print(f"  >>> Val loss: {val_loss:.4f} {'(new best!)' if val_loss < best_loss else ''}")
            if val_loss < best_loss:
                best_loss = val_loss

    total_pretrain_time = time.time() - start_time
    print(f"\n  Pre-training done in {total_pretrain_time/60:.1f} min | Best val loss: {best_loss:.4f}\n")

    # ── Phase 2: SFT on instruction pairs ──────────────────────────
    if sft_jsonl.exists():
        print("[Phase 2/2] Fine-tuning on 3,280 instruction pairs...")

        sft_ds = InstructionDataset(str(sft_jsonl), tokenizer, cfg.context_length)
        sft_loader = DataLoader(sft_ds, batch_size=cfg.batch_size, shuffle=True, num_workers=0)

        sft_lr = cfg.learning_rate * 0.1
        sft_optimizer = torch.optim.AdamW(model.parameters(), lr=sft_lr, weight_decay=0.01)
        sft_steps = 2000  # More SFT steps for better instruction following

        model.train()
        sft_iter = iter(sft_loader)
        sft_start = time.time()

        for step in range(sft_steps):
            lr = get_lr(step, sft_steps, sft_lr, warmup_iters=100)
            for pg in sft_optimizer.param_groups:
                pg["lr"] = lr

            sft_optimizer.zero_grad(set_to_none=True)
            accum_loss = 0.0

            for _ in range(cfg.gradient_accumulation_steps):
                try:
                    x, y = next(sft_iter)
                except StopIteration:
                    sft_iter = iter(sft_loader)
                    x, y = next(sft_iter)

                x, y = x.to(device), y.to(device)
                _, loss = model(x, y)
                loss = loss / cfg.gradient_accumulation_steps
                loss.backward()
                accum_loss += loss.item()

            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            sft_optimizer.step()

            if step % 50 == 0:
                elapsed = time.time() - sft_start
                steps_per_sec = (step + 1) / elapsed if elapsed > 0 else 0
                eta_min = (sft_steps - step) / steps_per_sec / 60 if steps_per_sec > 0 else 0
                print(f"  Step {step:5d}/{sft_steps} | loss={accum_loss:.4f} | lr={lr:.2e} | ETA: {eta_min:.0f}min")

        sft_time = time.time() - sft_start
        print(f"\n  SFT done in {sft_time/60:.1f} min\n")
    else:
        print("[Phase 2/2] Skipped — no SFT data\n")

    # ── Save checkpoint ────────────────────────────────────────────
    total_steps = pretrain_steps + (2000 if sft_jsonl.exists() else 0)
    model.eval()
    ckpt = {
        "step": total_steps,
        "val_loss": best_loss,
        "model": model.state_dict(),
        "config": cfg.__dict__,
    }

    # Save to repo (for bundling with package)
    torch.save(ckpt, str(repo_output))
    size_mb = repo_output.stat().st_size / (1024 * 1024)
    print(f"Saved to repo: {repo_output} ({size_mb:.1f}MB)")

    # Also save to user dir (for immediate use)
    torch.save(ckpt, str(user_output))
    print(f"Saved to user: {user_output}")

    total_time = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"  Training complete!")
    print(f"  Total time: {total_time/60:.1f} minutes")
    print(f"  Steps: {total_steps} (pretrain: {pretrain_steps} + SFT: {2000 if sft_jsonl.exists() else 0})")
    print(f"  Best val loss: {best_loss:.4f}")
    print(f"  Checkpoint: {size_mb:.1f}MB")
    print(f"{'='*60}")
    print(f"\nTest it: python -m trio agent -m 'Hello'")


if __name__ == "__main__":
    train()
