"""
Trio AI — Pre-training Loop
Full training loop with:
  - Checkpointing
  - Cosine LR schedule with linear warmup
  - Gradient clipping
  - Train/val loss logging
  - Resume from checkpoint
"""

import os
import sys
import time
import math
import argparse
import json
from contextlib import nullcontext

import torch

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_config, TrioConfig
from model.architecture import TrioModel
from data.tokenizer import get_tokenizer
from data.dataset import get_dataloaders


# ── Learning Rate Schedule ─────────────────────────────────────────────────────

def get_lr(step: int, cfg: TrioConfig) -> float:
    """Cosine decay with linear warmup."""
    # Warmup phase
    if step < cfg.warmup_iters:
        return cfg.learning_rate * step / cfg.warmup_iters

    # After final step — minimum LR
    if step > cfg.max_iters:
        return cfg.learning_rate * 0.1

    # Cosine decay
    progress = (step - cfg.warmup_iters) / max(1, cfg.max_iters - cfg.warmup_iters)
    decay = 0.5 * (1.0 + math.cos(math.pi * progress))
    min_lr = cfg.learning_rate * 0.1
    return min_lr + decay * (cfg.learning_rate - min_lr)


# ── Checkpoint ─────────────────────────────────────────────────────────────────

def save_checkpoint(model, optimizer, step, val_loss, cfg, path):
    os.makedirs(path, exist_ok=True)
    ckpt = {
        "step":      step,
        "val_loss":  val_loss,
        "model":     model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "config":    cfg.__dict__,
    }
    fpath = os.path.join(path, f"trio_step{step}.pt")
    torch.save(ckpt, fpath)
    # Also save as 'latest'
    torch.save(ckpt, os.path.join(path, "trio_latest.pt"))
    print(f"[Checkpoint] Saved → {fpath}")
    return fpath


def load_checkpoint(path, model, optimizer=None):
    ckpt = torch.load(path, map_location="cpu")
    model.load_state_dict(ckpt["model"])
    if optimizer and "optimizer" in ckpt:
        optimizer.load_state_dict(ckpt["optimizer"])
    print(f"[Checkpoint] Loaded step={ckpt['step']}, val_loss={ckpt['val_loss']:.4f}")
    return ckpt["step"]


# ── Evaluation ─────────────────────────────────────────────────────────────────

@torch.no_grad()
def evaluate(model, val_loader, cfg, ctx) -> float:
    model.eval()
    losses = []
    for i, (x, y) in enumerate(val_loader):
        if i >= cfg.eval_iters:
            break
        x, y = x.to(cfg.device), y.to(cfg.device)
        with ctx:
            _, loss = model(x, y)
        losses.append(loss.item())
    model.train()
    return sum(losses) / len(losses) if losses else float("inf")


# ── Main Training Loop ─────────────────────────────────────────────────────────

def train(preset: str = "nano", resume: bool = False):
    cfg = get_config(preset)
    os.makedirs(cfg.checkpoint_dir, exist_ok=True)
    os.makedirs(cfg.log_dir, exist_ok=True)
    os.makedirs(cfg.data_dir, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  Training: {cfg.model_name}")
    print(f"  Device:   {cfg.device}")
    print(f"  Dtype:    {cfg.dtype}")
    print(f"{'='*60}\n")

    # Device & dtype setup
    device = torch.device(cfg.device)
    dtype_map = {"float32": torch.float32, "float16": torch.float16, "bfloat16": torch.bfloat16}
    pt_dtype = dtype_map.get(cfg.dtype, torch.float32)

    # AMP context (only for CUDA)
    use_amp = (cfg.device == "cuda" and cfg.dtype in ("float16", "bfloat16"))
    ctx = torch.amp.autocast(device_type="cuda", dtype=pt_dtype) if use_amp else nullcontext()
    scaler = torch.cuda.GradScaler() if (use_amp and pt_dtype == torch.float16) else None

    # Tokenizer & data
    tokenizer = get_tokenizer(preset)
    # Update vocab size from actual tokenizer
    cfg.vocab_size = tokenizer.vocab_size
    train_loader, val_loader = get_dataloaders(cfg, tokenizer, mode="pretrain")

    # Model
    model = TrioModel(cfg).to(device)
    print(f"[Model] Parameters: {model.num_parameters() / 1e6:.2f}M")

    # Optimizer
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=cfg.learning_rate,
        betas=(0.9, 0.95),
        weight_decay=cfg.weight_decay,
        fused=False,   # fused only available on CUDA
    )

    # Resume
    start_step = 0
    if resume:
        ckpt_path = os.path.join(cfg.checkpoint_dir, "trio_latest.pt")
        if os.path.exists(ckpt_path):
            start_step = load_checkpoint(ckpt_path, model, optimizer)

    # Log file
    log_path = os.path.join(cfg.log_dir, f"{cfg.model_name}_train.jsonl")
    log_file = open(log_path, "a")

    # Training loop
    model.train()
    iter_count = start_step
    train_iter = iter(train_loader)

    t0 = time.time()
    best_val_loss = float("inf")

    print(f"[Training] Starting from step {start_step} / {cfg.max_iters}")
    print(f"[Training] Effective batch size: {cfg.batch_size * cfg.gradient_accumulation_steps} tokens/step\n")

    for step in range(start_step, cfg.max_iters):
        # Set LR
        lr = get_lr(step, cfg)
        for pg in optimizer.param_groups:
            pg["lr"] = lr

        # Gradient accumulation
        optimizer.zero_grad(set_to_none=True)
        accum_loss = 0.0

        for micro_step in range(cfg.gradient_accumulation_steps):
            try:
                x, y = next(train_iter)
            except StopIteration:
                train_iter = iter(train_loader)
                x, y = next(train_iter)

            x, y = x.to(device), y.to(device)

            with ctx:
                _, loss = model(x, y)
                loss = loss / cfg.gradient_accumulation_steps

            if scaler:
                scaler.scale(loss).backward()
            else:
                loss.backward()

            accum_loss += loss.item()

        # Gradient clip
        if scaler:
            scaler.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)

        if scaler:
            scaler.step(optimizer)
            scaler.update()
        else:
            optimizer.step()

        iter_count += 1

        # Logging
        if step % 50 == 0:
            dt = time.time() - t0
            tok_per_sec = cfg.batch_size * cfg.gradient_accumulation_steps * cfg.context_length / dt
            print(f"Step {step:5d}/{cfg.max_iters} | loss={accum_loss:.4f} | lr={lr:.2e} | {tok_per_sec:.0f} tok/s")
            t0 = time.time()

        # Evaluation
        if step % cfg.eval_interval == 0 or step == cfg.max_iters - 1:
            val_loss = evaluate(model, val_loader, cfg, ctx)
            print(f"\n{'─'*40}")
            print(f"[Eval] Step {step} | train_loss={accum_loss:.4f} | val_loss={val_loss:.4f}")
            print(f"{'─'*40}\n")
            log_file.write(json.dumps({"step": step, "train_loss": accum_loss, "val_loss": val_loss, "lr": lr}) + "\n")
            log_file.flush()

            if val_loss < best_val_loss:
                best_val_loss = val_loss
                save_checkpoint(model, optimizer, step, val_loss, cfg, cfg.checkpoint_dir)

        # Regular checkpoint
        elif step % cfg.save_interval == 0 and step > 0:
            save_checkpoint(model, optimizer, step, accum_loss, cfg, cfg.checkpoint_dir)

    log_file.close()
    print(f"\n✅ Training complete! Best val_loss: {best_val_loss:.4f}")
    print(f"   Checkpoint saved in: {cfg.checkpoint_dir}/")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train the Trio language model")
    parser.add_argument("--preset", type=str, default="nano",
                        choices=["nano", "small", "medium"],
                        help="Model size preset")
    parser.add_argument("--resume", action="store_true",
                        help="Resume training from latest checkpoint")
    args = parser.parse_args()
    train(preset=args.preset, resume=args.resume)
