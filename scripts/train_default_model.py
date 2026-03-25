"""Train the default trio-max model on skills data — MAX POWER.

Supports pause/resume: saves checkpoints every 200 steps.
Kill the process anytime, then run again to resume from last checkpoint.

Usage:
    python scripts/train_default_model.py           # Start or resume training
    python scripts/train_default_model.py --reset    # Start fresh (ignores saved progress)
"""

import os
import sys
import time
import math
import json
import argparse
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


# ── Paths ─────────────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).parent.parent / "trio_model" / "data"
REPO_CKPT_DIR = Path(__file__).parent.parent / "trio_model" / "checkpoints"
USER_DIR = Path.home() / ".trio" / "models"
PROGRESS_FILE = Path.home() / ".trio" / "training_progress.json"


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


def detect_ram():
    """Cross-platform RAM detection."""
    try:
        import psutil
        return round(psutil.virtual_memory().total / (1024**3), 1)
    except ImportError:
        pass
    try:
        if sys.platform == "win32":
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong)] + [("_pad" + str(i), ctypes.c_ulonglong) for i in range(6)]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return round(stat.ullTotalPhys / (1024**3), 1)
        elif sys.platform == "darwin":
            import subprocess
            result = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return round(int(result.stdout.strip()) / (1024**3), 1)
        else:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return round(int(line.split()[1]) / (1024**2), 1)
    except Exception:
        pass
    return 8


def save_progress(phase, step, best_loss, model, optimizer, cfg):
    """Save training progress for resume."""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ckpt_path = USER_DIR / "trio-nano-progress.pt"

    torch.save({
        "phase": phase,
        "step": step,
        "best_loss": best_loss,
        "model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "config": cfg.__dict__,
    }, str(ckpt_path))

    with open(PROGRESS_FILE, "w") as f:
        json.dump({"phase": phase, "step": step, "best_loss": best_loss}, f)

    print(f"  [checkpoint saved at phase={phase} step={step}]")


def load_progress():
    """Load saved training progress."""
    if not PROGRESS_FILE.exists():
        return None
    try:
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return None


def train(reset=False):
    train_txt = DATA_DIR / "train.txt"
    sft_jsonl = DATA_DIR / "sft_data.jsonl"

    REPO_CKPT_DIR.mkdir(parents=True, exist_ok=True)
    USER_DIR.mkdir(parents=True, exist_ok=True)
    repo_output = REPO_CKPT_DIR / "trio-nano.pt"
    user_output = USER_DIR / "trio-nano.pt"

    if not train_txt.exists():
        print("Training data not found. Run: python scripts/build_training_data.py")
        return

    # Config
    cfg = get_config("nano")
    tokenizer = get_tokenizer("nano")
    cfg.vocab_size = tokenizer.vocab_size
    device = torch.device(cfg.device)

    cfg.batch_size = 32
    cfg.gradient_accumulation_steps = 1

    num_cores = os.cpu_count() or 1
    ram_gb = detect_ram()

    # Check for resume
    progress = load_progress() if not reset else None
    resuming = progress is not None
    resume_phase = progress["phase"] if resuming else "pretrain"
    resume_step = progress["step"] if resuming else 0
    best_loss = progress["best_loss"] if resuming else float("inf")

    print(f"\n{'='*60}")
    print(f"  TRIO.AI — Model Training (MAX POWER)")
    print(f"  CPU: {num_cores} cores | RAM: {ram_gb}GB")
    print(f"  PyTorch threads: {torch.get_num_threads()}")
    print(f"  Training data: {train_txt.stat().st_size / 1e6:.1f}MB")
    print(f"  SFT pairs: {sum(1 for _ in open(sft_jsonl, encoding='utf-8')) if sft_jsonl.exists() else 0}")
    print(f"  Batch size: {cfg.batch_size}")
    if resuming:
        print(f"  RESUMING from phase={resume_phase} step={resume_step}")
    print(f"{'='*60}\n")

    # ── Build model ───────────────────────────────────────────────
    model = TrioModel(cfg).to(device)

    # torch.compile: only on Linux/macOS with proper C++ compiler
    try:
        import platform
        if (hasattr(torch, "compile")
                and platform.system() != "Windows"
                and device.type != "mps"):
            model = torch.compile(model)
            print("  [torch.compile enabled]")
    except Exception:
        pass

    # Load checkpoint if resuming
    if resuming:
        ckpt_path = USER_DIR / "trio-nano-progress.pt"
        if ckpt_path.exists():
            ckpt = torch.load(str(ckpt_path), map_location=device, weights_only=False)
            model.load_state_dict(ckpt["model"])
            print(f"  [model weights loaded from checkpoint]")

    # ── Data loaders ──────────────────────────────────────────────
    train_ds = TextDataset(str(train_txt), tokenizer, cfg.context_length, split="train")
    val_ds = TextDataset(str(train_txt), tokenizer, cfg.context_length, split="val")
    train_loader = DataLoader(train_ds, batch_size=cfg.batch_size, shuffle=True, num_workers=0, pin_memory=False)
    val_loader = DataLoader(val_ds, batch_size=cfg.batch_size, shuffle=False, num_workers=0)

    pretrain_steps = 2000
    sft_steps = 800
    start_time = time.time()

    # ── Phase 1: Pre-training ─────────────────────────────────────
    if resume_phase == "pretrain":
        print(f"[Phase 1/2] Pre-training {'(resuming)' if resume_step > 0 else ''}...")

        optimizer = torch.optim.AdamW(
            model.parameters(), lr=cfg.learning_rate,
            betas=(0.9, 0.95), weight_decay=0.1,
        )

        # Load optimizer state if resuming
        if resuming and resume_step > 0:
            ckpt_path = USER_DIR / "trio-nano-progress.pt"
            if ckpt_path.exists():
                ckpt = torch.load(str(ckpt_path), map_location=device, weights_only=False)
                if "optimizer" in ckpt:
                    optimizer.load_state_dict(ckpt["optimizer"])

        model.train()
        train_iter = iter(train_loader)

        for step in range(resume_step, pretrain_steps):
            lr = get_lr(step, pretrain_steps, cfg.learning_rate, warmup_iters=150)
            for pg in optimizer.param_groups:
                pg["lr"] = lr

            optimizer.zero_grad(set_to_none=True)

            try:
                x, y = next(train_iter)
            except StopIteration:
                train_iter = iter(train_loader)
                x, y = next(train_iter)

            x, y = x.to(device), y.to(device)
            _, loss = model(x, y)
            loss.backward()
            accum_loss = loss.item()

            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

            if step % 50 == 0:
                elapsed = time.time() - start_time
                done = step - resume_step + 1
                steps_per_sec = done / elapsed if elapsed > 0 else 0
                remaining = pretrain_steps - step
                eta_min = remaining / steps_per_sec / 60 if steps_per_sec > 0 else 0
                print(f"  Step {step:5d}/{pretrain_steps} | loss={accum_loss:.4f} | lr={lr:.2e} | {steps_per_sec:.1f} it/s | ETA: {eta_min:.0f}min")

            if step % 400 == 0 and step > 0:
                val_loss = evaluate(model, val_loader, device)
                print(f"  >>> Val loss: {val_loss:.4f} {'(new best!)' if val_loss < best_loss else ''}")
                if val_loss < best_loss:
                    best_loss = val_loss

            # Save checkpoint every 200 steps for resume
            if step % 200 == 0 and step > 0:
                save_progress("pretrain", step, best_loss, model, optimizer, cfg)

        # Pretrain done — save progress marking SFT as next phase
        save_progress("sft", 0, best_loss, model, optimizer, cfg)

        total_pretrain_time = time.time() - start_time
        print(f"\n  Pre-training done in {total_pretrain_time/60:.1f} min | Best val loss: {best_loss:.4f}\n")

        # Reset for SFT
        resume_step = 0

    # ── Phase 2: SFT ──────────────────────────────────────────────
    if sft_jsonl.exists():
        print(f"[Phase 2/2] Fine-tuning {'(resuming)' if resume_phase == 'sft' and resume_step > 0 else ''}...")

        sft_ds = InstructionDataset(str(sft_jsonl), tokenizer, cfg.context_length)
        sft_loader = DataLoader(sft_ds, batch_size=cfg.batch_size, shuffle=True, num_workers=0)

        sft_lr = cfg.learning_rate * 0.1
        sft_optimizer = torch.optim.AdamW(model.parameters(), lr=sft_lr, weight_decay=0.01)

        # Load SFT optimizer state if resuming into SFT phase
        if resume_phase == "sft" and resume_step > 0:
            ckpt_path = USER_DIR / "trio-nano-progress.pt"
            if ckpt_path.exists():
                ckpt = torch.load(str(ckpt_path), map_location=device, weights_only=False)
                if "optimizer" in ckpt:
                    sft_optimizer.load_state_dict(ckpt["optimizer"])

        model.train()
        sft_iter = iter(sft_loader)
        sft_start = time.time()

        sft_resume = resume_step if resume_phase == "sft" else 0

        for step in range(sft_resume, sft_steps):
            lr = get_lr(step, sft_steps, sft_lr, warmup_iters=50)
            for pg in sft_optimizer.param_groups:
                pg["lr"] = lr

            sft_optimizer.zero_grad(set_to_none=True)

            try:
                x, y = next(sft_iter)
            except StopIteration:
                sft_iter = iter(sft_loader)
                x, y = next(sft_iter)

            x, y = x.to(device), y.to(device)
            _, loss = model(x, y)
            loss.backward()
            accum_loss = loss.item()

            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            sft_optimizer.step()

            if step % 50 == 0:
                elapsed = time.time() - sft_start
                done = step - sft_resume + 1
                steps_per_sec = done / elapsed if elapsed > 0 else 0
                eta_min = (sft_steps - step) / steps_per_sec / 60 if steps_per_sec > 0 else 0
                print(f"  Step {step:5d}/{sft_steps} | loss={accum_loss:.4f} | lr={lr:.2e} | ETA: {eta_min:.0f}min")

            # Save checkpoint every 200 steps
            if step % 200 == 0 and step > 0:
                save_progress("sft", step, best_loss, model, sft_optimizer, cfg)

        sft_time = time.time() - sft_start
        print(f"\n  SFT done in {sft_time/60:.1f} min\n")
        sft_steps_done = sft_steps
    else:
        print("[Phase 2/2] Skipped — no SFT data\n")
        sft_steps_done = 0

    # ── Save final checkpoint ─────────────────────────────────────
    total_steps = pretrain_steps + sft_steps_done
    model.eval()
    ckpt = {
        "step": total_steps,
        "val_loss": best_loss,
        "model": model.state_dict(),
        "config": cfg.__dict__,
    }

    torch.save(ckpt, str(repo_output))
    size_mb = repo_output.stat().st_size / (1024 * 1024)
    print(f"Saved to repo: {repo_output} ({size_mb:.1f}MB)")

    torch.save(ckpt, str(user_output))
    print(f"Saved to user: {user_output}")

    # Clean up progress files
    progress_ckpt = USER_DIR / "trio-nano-progress.pt"
    if progress_ckpt.exists():
        progress_ckpt.unlink()
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()

    total_time = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"  Training complete!")
    print(f"  Total time: {total_time/60:.1f} minutes")
    print(f"  Steps: {total_steps} (pretrain: {pretrain_steps} + SFT: {sft_steps_done})")
    print(f"  Best val loss: {best_loss:.4f}")
    print(f"  Checkpoint: {size_mb:.1f}MB")
    print(f"{'='*60}")
    print(f"\nTest it: trio agent -m 'Hello'")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train trio-max model")
    parser.add_argument("--reset", action="store_true", help="Start fresh, ignore saved progress")
    args = parser.parse_args()
    train(reset=args.reset)
