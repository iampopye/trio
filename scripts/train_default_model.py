"""Train the default trio-nano model on skills data.

Run this once to create a pre-trained model that ships with trio.ai.
The model will be saved to ~/.trio/models/trio-nano.pt

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

# Add project root to path
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


def train():
    data_dir = Path(__file__).parent.parent / "trio_model" / "data"
    train_txt = data_dir / "train.txt"
    sft_jsonl = data_dir / "sft_data.jsonl"
    output_dir = Path.home() / ".trio" / "models"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "trio-nano.pt"

    if not train_txt.exists():
        print("Training data not found. Run: python scripts/build_training_data.py")
        return

    # Config
    cfg = get_config("nano")
    tokenizer = get_tokenizer("nano")
    cfg.vocab_size = tokenizer.vocab_size
    device = torch.device(cfg.device)

    print(f"\n{'='*60}")
    print(f"  Training trio-nano on {train_txt.stat().st_size / 1e6:.1f}MB of skills data")
    print(f"  Output: {output_path}")
    print(f"{'='*60}\n")

    # ── Phase 1: Pre-training ──────────────────────────────────────
    print("[Phase 1/2] Pre-training on skills corpus...")

    train_ds = TextDataset(str(train_txt), tokenizer, cfg.context_length, split="train")
    val_ds = TextDataset(str(train_txt), tokenizer, cfg.context_length, split="val")
    train_loader = DataLoader(train_ds, batch_size=cfg.batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=cfg.batch_size, shuffle=False, num_workers=0)

    model = TrioModel(cfg).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg.learning_rate, weight_decay=0.1)

    pretrain_steps = 3000
    model.train()
    train_iter = iter(train_loader)
    best_loss = float("inf")
    t0 = time.time()

    for step in range(pretrain_steps):
        lr = get_lr(step, pretrain_steps, cfg.learning_rate)
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

        if step % 100 == 0:
            elapsed = time.time() - t0
            steps_per_sec = (step + 1) / elapsed if elapsed > 0 else 0
            eta = (pretrain_steps - step) / steps_per_sec if steps_per_sec > 0 else 0
            print(f"  [Pretrain] Step {step:4d}/{pretrain_steps} | loss={accum_loss:.4f} | lr={lr:.2e} | {steps_per_sec:.1f} steps/s | ETA: {eta/60:.0f}min")
            t0_eval = time.time()

        if step % 500 == 0 and step > 0:
            model.eval()
            val_losses = []
            with torch.no_grad():
                for i, (vx, vy) in enumerate(val_loader):
                    if i >= 20:
                        break
                    vx, vy = vx.to(device), vy.to(device)
                    _, vloss = model(vx, vy)
                    val_losses.append(vloss.item())
            val_loss = sum(val_losses) / len(val_losses) if val_losses else float("inf")
            print(f"  [Pretrain] Val loss: {val_loss:.4f}")
            if val_loss < best_loss:
                best_loss = val_loss
            model.train()

    print(f"  [Pretrain] Done! Best val loss: {best_loss:.4f}\n")

    # ── Phase 2: SFT ──────────────────────────────────────────────
    if sft_jsonl.exists():
        print("[Phase 2/2] Fine-tuning on instruction pairs...")

        sft_ds = InstructionDataset(str(sft_jsonl), tokenizer, cfg.context_length)
        sft_loader = DataLoader(sft_ds, batch_size=cfg.batch_size, shuffle=True, num_workers=0)

        # Lower LR for fine-tuning
        sft_lr = cfg.learning_rate * 0.1
        sft_optimizer = torch.optim.AdamW(model.parameters(), lr=sft_lr, weight_decay=0.01)
        sft_steps = 1000

        model.train()
        sft_iter = iter(sft_loader)

        for step in range(sft_steps):
            lr = get_lr(step, sft_steps, sft_lr, warmup_iters=50)
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

            if step % 100 == 0:
                print(f"  [SFT] Step {step:4d}/{sft_steps} | loss={accum_loss:.4f} | lr={lr:.2e}")

        print(f"  [SFT] Done!\n")
    else:
        print("[Phase 2/2] Skipped (no SFT data found)\n")

    # ── Save final checkpoint ──────────────────────────────────────
    model.eval()
    ckpt = {
        "step": pretrain_steps + (1000 if sft_jsonl.exists() else 0),
        "val_loss": best_loss,
        "model": model.state_dict(),
        "config": cfg.__dict__,
    }
    torch.save(ckpt, str(output_path))
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"Model saved to {output_path} ({size_mb:.1f}MB)")
    print(f"Total training steps: {ckpt['step']}")
    print(f"Best val loss: {best_loss:.4f}")
    print(f"\nThe model is now ready! Run: python -m trio agent -m 'Hello'")


if __name__ == "__main__":
    train()
