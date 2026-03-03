"""
Trio AI — Supervised Fine-Tuning (SFT)
Fine-tunes a pre-trained Trio checkpoint on instruction-response pairs
to create a helpful assistant. Uses prompt masking so loss is computed
only on assistant responses, not user prompts.
"""

import os
import sys
import math
import argparse
import json
import time

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_config
from model.architecture import TrioModel
from data.tokenizer import get_tokenizer
from data.dataset import get_dataloaders
from training.pretrain import get_lr, save_checkpoint, evaluate
from contextlib import nullcontext


def sft_train(preset: str = "nano", base_checkpoint: str = None):
    cfg = get_config(preset)
    # SFT uses lower LR than pretraining
    cfg.learning_rate = cfg.learning_rate * 0.1
    cfg.max_iters     = max(cfg.max_iters // 5, 1000)  # shorter fine-tune
    cfg.warmup_iters  = 100

    os.makedirs(cfg.checkpoint_dir, exist_ok=True)
    os.makedirs(cfg.log_dir, exist_ok=True)

    device = torch.device(cfg.device)
    ctx    = nullcontext()  # can add AMP here for CUDA

    # Tokenizer & SFT dataset
    tokenizer = get_tokenizer(preset)
    cfg.vocab_size = tokenizer.vocab_size
    train_loader, val_loader = get_dataloaders(cfg, tokenizer, mode="sft")

    # Load model
    model = TrioModel(cfg).to(device)

    # Load pre-trained weights if available
    if base_checkpoint:
        if os.path.exists(base_checkpoint):
            ckpt = torch.load(base_checkpoint, map_location=device)
            model.load_state_dict(ckpt["model"])
            print(f"[SFT] Loaded base model from {base_checkpoint}")
        else:
            print(f"[SFT] Checkpoint not found at {base_checkpoint}, training from scratch")
    else:
        # Try to auto-find latest checkpoint
        latest = os.path.join(cfg.checkpoint_dir, "trio_latest.pt")
        if os.path.exists(latest):
            ckpt = torch.load(latest, map_location=device)
            model.load_state_dict(ckpt["model"])
            print(f"[SFT] Auto-loaded pre-trained checkpoint from {latest}")
        else:
            print("[SFT] No checkpoint found, starting SFT from random init (not recommended)")

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=cfg.learning_rate,
        betas=(0.9, 0.95),
        weight_decay=0.01,  # lighter weight decay for fine-tuning
    )

    print(f"\n{'='*60}")
    print(f"  Fine-tuning: {cfg.model_name}-sft")
    print(f"  Max steps:   {cfg.max_iters}")
    print(f"  LR:          {cfg.learning_rate}")
    print(f"{'='*60}\n")

    model.train()
    train_iter = iter(train_loader)
    best_val_loss = float("inf")
    log_path = os.path.join(cfg.log_dir, f"{cfg.model_name}_sft.jsonl")

    with open(log_path, "a") as log_file:
        t0 = time.time()
        for step in range(cfg.max_iters):
            lr = get_lr(step, cfg)
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
                with ctx:
                    _, loss = model(x, y)
                    loss = loss / cfg.gradient_accumulation_steps
                loss.backward()
                accum_loss += loss.item()

            torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
            optimizer.step()

            if step % 25 == 0:
                dt = time.time() - t0
                print(f"[SFT] Step {step:4d}/{cfg.max_iters} | loss={accum_loss:.4f} | lr={lr:.2e}")
                t0 = time.time()

            if step % cfg.eval_interval == 0 or step == cfg.max_iters - 1:
                val_loss = evaluate(model, val_loader, cfg, ctx)
                print(f"\n[SFT Eval] Step {step} | val_loss={val_loss:.4f}\n")
                log_file.write(json.dumps({"step": step, "val_loss": val_loss}) + "\n")
                log_file.flush()

                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    sft_dir = os.path.join(cfg.checkpoint_dir, "sft")
                    save_checkpoint(model, optimizer, step, val_loss, cfg, sft_dir)

    print(f"\n✅ SFT complete! Best val_loss: {best_val_loss:.4f}")
    print(f"   SFT checkpoint saved in: {cfg.checkpoint_dir}/sft/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fine-tune Trio on instruction data")
    parser.add_argument("--preset",     type=str, default="nano", choices=["nano", "small", "medium"])
    parser.add_argument("--checkpoint", type=str, default=None, help="Path to pre-trained checkpoint")
    args = parser.parse_args()
    sft_train(preset=args.preset, base_checkpoint=args.checkpoint)
