"""
Trio AI — BPE Tokenizer
Wraps tiktoken (GPT-2/GPT-4 compatible) with Trio-specific special tokens.
For nano config, uses a smaller character-level fallback.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import os
import json
import regex as re
from typing import List, Optional


# ── Special Tokens ─────────────────────────────────────────────────────────────

SPECIAL_TOKENS = {
    "<pad>":   0,
    "<eos>":   1,
    "<bos>":   2,
    "<unk>":   3,
    "<|human|>":    4,    # user turn marker
    "<|trio|>":     5,    # assistant turn marker
    "<|system|>":   6,    # system prompt marker
    "<|endturn|>":  7,    # end of turn
}


# ── Tiktoken Wrapper (for Small/Medium configs) ────────────────────────────────

class TrioTokenizer:
    """
    Production tokenizer using tiktoken BPE (GPT-2/cl100k compatible).
    Use this for Small and Medium configs (vocab_size=50257 or 100277).
    """

    def __init__(self, encoding: str = "gpt2"):
        try:
            import tiktoken
            self._enc = tiktoken.get_encoding(encoding)
            self.vocab_size = self._enc.n_vocab
            print(f"[Trio Tokenizer] Loaded tiktoken '{encoding}' — vocab size: {self.vocab_size}")
        except ImportError:
            raise ImportError("Run: pip install tiktoken")

    def encode(self, text: str, add_bos: bool = False, add_eos: bool = False) -> List[int]:
        ids = self._enc.encode(text, allowed_special="all")
        if add_bos:
            ids = [SPECIAL_TOKENS["<bos>"]] + ids
        if add_eos:
            ids = ids + [SPECIAL_TOKENS["<eos>"]]
        return ids

    def decode(self, ids: List[int]) -> str:
        # Filter out special token ids before decoding
        filtered = [i for i in ids if i not in SPECIAL_TOKENS.values()]
        return self._enc.decode(filtered)

    def encode_chat(self, messages: List[dict]) -> List[int]:
        """
        Encode a chat conversation.
        messages: [{"role": "human"/"trio"/"system", "content": "..."}]
        """
        ids = []
        for msg in messages:
            role = msg.get("role", "human")
            content = msg.get("content", "")
            if role == "system":
                ids += [SPECIAL_TOKENS["<|system|>"]] + self.encode(content) + [SPECIAL_TOKENS["<|endturn|>"]]
            elif role == "human":
                ids += [SPECIAL_TOKENS["<|human|>"]] + self.encode(content) + [SPECIAL_TOKENS["<|endturn|>"]]
            elif role == "trio":
                ids += [SPECIAL_TOKENS["<|trio|>"]] + self.encode(content) + [SPECIAL_TOKENS["<|endturn|>"]]
        # Add trio turn start
        ids += [SPECIAL_TOKENS["<|trio|>"]]
        return ids

    @property
    def eos_token_id(self) -> int:
        return SPECIAL_TOKENS["<eos>"]

    @property
    def bos_token_id(self) -> int:
        return SPECIAL_TOKENS["<bos>"]


# ── Character-Level Tokenizer (for Nano config — no dependencies) ──────────────

class CharTokenizer:
    """
    Simple character-level tokenizer for the nano config.
    No external dependencies. Build vocab from your training text.
    """

    def __init__(self, vocab_path: Optional[str] = None):
        if vocab_path and os.path.exists(vocab_path):
            self.load(vocab_path)
        else:
            # Default printable ASCII vocab
            chars = [chr(i) for i in range(32, 127)] + ["\n", "\t"]
            self._stoi = {c: i + len(SPECIAL_TOKENS) for i, c in enumerate(chars)}
            self._itos = {i: c for c, i in self._stoi.items()}
            # Add specials
            for tok, idx in SPECIAL_TOKENS.items():
                self._stoi[tok] = idx
                self._itos[idx] = tok
            self.vocab_size = len(self._stoi)
            print(f"[Trio CharTokenizer] Vocab size: {self.vocab_size}")

    def train_from_text(self, text: str, save_path: Optional[str] = None):
        """Build vocab from all unique characters in text."""
        chars = sorted(set(text))
        self._stoi = {c: i + len(SPECIAL_TOKENS) for i, c in enumerate(chars)}
        self._itos = {i: c for c, i in self._stoi.items()}
        for tok, idx in SPECIAL_TOKENS.items():
            self._stoi[tok] = idx
            self._itos[idx] = tok
        self.vocab_size = len(self._stoi)
        if save_path:
            self.save(save_path)
        print(f"[Trio CharTokenizer] Trained vocab size: {self.vocab_size}")

    def encode(self, text: str, add_bos: bool = False, add_eos: bool = False) -> List[int]:
        ids = [self._stoi.get(c, SPECIAL_TOKENS["<unk>"]) for c in text]
        if add_bos:
            ids = [SPECIAL_TOKENS["<bos>"]] + ids
        if add_eos:
            ids = ids + [SPECIAL_TOKENS["<eos>"]]
        return ids

    def decode(self, ids: List[int]) -> str:
        return "".join(self._itos.get(i, "?") for i in ids
                       if i not in SPECIAL_TOKENS.values())

    def save(self, path: str):
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump({"stoi": self._stoi, "itos": {str(k): v for k, v in self._itos.items()}}, f)
        print(f"[Trio CharTokenizer] Saved to {path}")

    def load(self, path: str):
        with open(path) as f:
            data = json.load(f)
        self._stoi = data["stoi"]
        self._itos = {int(k): v for k, v in data["itos"].items()}
        self.vocab_size = len(self._stoi)
        print(f"[Trio CharTokenizer] Loaded from {path} — vocab size: {self.vocab_size}")

    @property
    def eos_token_id(self) -> int:
        return SPECIAL_TOKENS["<eos>"]

    @property
    def bos_token_id(self) -> int:
        return SPECIAL_TOKENS["<bos>"]


# ── Factory ────────────────────────────────────────────────────────────────────

def get_tokenizer(preset: str = "nano", vocab_path: Optional[str] = None):
    """Return the appropriate tokenizer for a given config preset."""
    if preset == "nano":
        return CharTokenizer(vocab_path)
    else:
        return TrioTokenizer(encoding="gpt2")
