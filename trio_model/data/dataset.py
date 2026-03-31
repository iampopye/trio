"""
Trio AI — Dataset & DataLoader
Supports:
  - Plain text pre-training (packed sequences)
  - Instruction (SFT) chat format
  - Memory-mapped binary files for large datasets
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import os
import json
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
from typing import List, Optional, Union


# ── Pre-training Dataset ───────────────────────────────────────────────────────

class TextDataset(Dataset):
    """
    Loads a plain .txt file and slices it into fixed-length chunks.
    No padding — sequences are packed end-to-end for efficiency.
    Suitable for nano config on your Mac Mini.
    """

    def __init__(
        self,
        file_path: str,
        tokenizer,
        context_length: int = 256,
        split: str = "train",
        val_fraction: float = 0.1,
    ):
        super().__init__()
        assert os.path.exists(file_path), f"Data file not found: {file_path}"  # nosec B101

        with open(file_path, "r", encoding="utf-8") as f:
            raw = f.read()

        print(f"[Dataset] Raw chars: {len(raw):,}")
        all_ids = tokenizer.encode(raw)
        print(f"[Dataset] Total tokens: {len(all_ids):,}")

        # Train / val split
        split_idx = int(len(all_ids) * (1 - val_fraction))
        if split == "train":
            self.ids = all_ids[:split_idx]
        else:
            self.ids = all_ids[split_idx:]

        self.context_length = context_length
        # Number of full sequences we can extract
        self.n_seq = (len(self.ids) - 1) // context_length
        print(f"[Dataset] Split='{split}' — {self.n_seq:,} sequences of length {context_length}")

    def __len__(self) -> int:
        return self.n_seq

    def __getitem__(self, idx: int):
        start = idx * self.context_length
        end   = start + self.context_length
        x = torch.tensor(self.ids[start:end],     dtype=torch.long)
        y = torch.tensor(self.ids[start+1:end+1], dtype=torch.long)
        return x, y


# ── Binary Dataset (for large-scale training) ─────────────────────────────────

class BinaryDataset(Dataset):
    """
    Memory-mapped binary token file for large-scale pre-training.
    Create with: scripts/prepare_data.py
    Format: uint16 numpy array saved as .bin
    """

    def __init__(self, bin_path: str, context_length: int = 1024):
        self.data = np.memmap(bin_path, dtype=np.uint16, mode="r")
        self.context_length = context_length
        self.n_seq = (len(self.data) - 1) // context_length

    def __len__(self) -> int:
        return self.n_seq

    def __getitem__(self, idx: int):
        start = idx * self.context_length
        end   = start + self.context_length
        x = torch.from_numpy(self.data[start:end].astype(np.int64))
        y = torch.from_numpy(self.data[start+1:end+1].astype(np.int64))
        return x, y


# ── SFT Instruction Dataset ────────────────────────────────────────────────────

class InstructionDataset(Dataset):
    """
    Fine-tuning dataset from JSONL file.
    Format: {"prompt": "Human: ...\n\nTrio:", "response": "..."}
    Only the response tokens are used as training targets (prompt masked with -1).
    """

    def __init__(
        self,
        jsonl_path: str,
        tokenizer,
        context_length: int = 1024,
    ):
        super().__init__()
        self.tokenizer = tokenizer
        self.context_length = context_length
        self.samples = []

        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    self.samples.append(json.loads(line))

        print(f"[InstructionDataset] Loaded {len(self.samples):,} samples from {jsonl_path}")

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int):
        sample = self.samples[idx]
        prompt   = sample["prompt"]
        response = sample["response"]

        prompt_ids   = self.tokenizer.encode(prompt)
        response_ids = self.tokenizer.encode(response, add_eos=True)

        # Truncate to context length
        max_len = self.context_length
        combined = (prompt_ids + response_ids)[:max_len + 1]

        x = torch.tensor(combined[:-1], dtype=torch.long)
        y = torch.tensor(combined[1:],  dtype=torch.long)

        # Mask prompt tokens in target (we only train on response)
        prompt_len = min(len(prompt_ids), len(x))
        y[:prompt_len] = -1    # cross_entropy ignores index=-1

        # Pad if needed
        if len(x) < max_len:
            pad_len = max_len - len(x)
            x = torch.cat([x, torch.zeros(pad_len, dtype=torch.long)])
            y = torch.cat([y, torch.full((pad_len,), -1, dtype=torch.long)])

        return x, y


# ── DataLoader Factory ─────────────────────────────────────────────────────────

def get_dataloaders(
    cfg,
    tokenizer,
    mode: str = "pretrain",
    data_path: Optional[str] = None,
):
    """
    Returns train and val DataLoaders based on mode.
    mode: 'pretrain' | 'sft'
    """
    data_path = data_path or cfg.data_dir

    if mode == "pretrain":
        txt_file = os.path.join(data_path, "train.txt")
        if not os.path.exists(txt_file):
            _create_sample_data(txt_file)  # auto-create sample for first run

        train_ds = TextDataset(txt_file, tokenizer, cfg.context_length, split="train")
        val_ds   = TextDataset(txt_file, tokenizer, cfg.context_length, split="val")

    elif mode == "sft":
        jsonl_file = os.path.join(data_path, "sft_data.jsonl")
        if not os.path.exists(jsonl_file):
            _create_sample_sft_data(jsonl_file)

        train_ds = InstructionDataset(jsonl_file, tokenizer, cfg.context_length)
        val_ds   = train_ds   # for quick experiments; use separate val in production

    else:
        raise ValueError(f"Unknown mode: {mode}")

    train_loader = DataLoader(
        train_ds,
        batch_size=cfg.batch_size,
        shuffle=True,
        num_workers=0,   # 0 for Windows/Mac compatibility
        pin_memory=False,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=cfg.batch_size,
        shuffle=False,
        num_workers=0,
    )
    return train_loader, val_loader


# ── Sample Data Generators (for first-run demo) ───────────────────────────────

def _create_sample_data(path: str):
    """Create a tiny sample corpus for testing the pipeline."""
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    sample = """Trio is an AI model built from scratch.
It learns from text data and can answer questions, write code, and have conversations.
The name Trio represents the three pillars of the model: intelligence, helpfulness, and safety.

Artificial intelligence is transforming how we interact with computers.
Language models learn patterns in text and use them to generate new text.
The transformer architecture, introduced in 2017, is the foundation of modern AI.

Hello! I am Trio, your AI assistant. How can I help you today?
I can help you with writing, coding, math, and general questions.
My goal is to be helpful, accurate, and honest in every response.
""" * 200  # repeat to get enough tokens for training
    with open(path, "w", encoding="utf-8") as f:
        f.write(sample)
    print(f"[Dataset] Created sample corpus at {path}")


def _create_sample_sft_data(path: str):
    """Create sample instruction-response pairs for SFT testing."""
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    samples = [
        {"prompt": "Human: What is your name?\n\nTrio:", "response": " I am Trio, an AI assistant built from scratch. How can I help you today?"},
        {"prompt": "Human: What can you do?\n\nTrio:", "response": " I can answer questions, help with writing, assist with coding, explain concepts, and have conversations on a wide range of topics."},
        {"prompt": "Human: Who created you?\n\nTrio:", "response": " I was built from scratch as a custom AI model. My architecture is based on the transformer model, similar to other modern language models."},
        {"prompt": "Human: What is 2 + 2?\n\nTrio:", "response": " 2 + 2 equals 4."},
        {"prompt": "Human: Tell me about artificial intelligence.\n\nTrio:", "response": " Artificial intelligence (AI) is the field of computer science focused on creating systems that can perform tasks that typically require human intelligence, such as understanding language, recognizing patterns, and making decisions."},
    ] * 100  # repeat for enough training samples

    with open(path, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s) + "\n")
    print(f"[Dataset] Created sample SFT data at {path}")
