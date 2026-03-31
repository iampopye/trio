"""
Trio AI — Attention Module
Implements:
  - Rotary Position Embeddings (RoPE)
  - Multi-Head Attention (MHA)
  - Grouped Query Attention (GQA) / Multi-Query Attention (MQA)
  - Causal masking
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import math
import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Optional, Tuple


# ── Rotary Position Embedding ──────────────────────────────────────────────────

class RotaryEmbedding(nn.Module):
    """RoPE: encodes position into Q and K by rotation in 2D subspaces."""

    def __init__(self, dim: int, base: int = 10000):
        super().__init__()
        self.dim = dim
        self.base = base
        # Precompute inverse freqs; not a trainable param
        inv_freq = 1.0 / (base ** (torch.arange(0, dim, 2).float() / dim))
        self.register_buffer("inv_freq", inv_freq)
        self._cos_cached = None
        self._sin_cached = None
        self._seq_len_cached = 0

    def _build_cache(self, seq_len: int, device: torch.device):
        if seq_len <= self._seq_len_cached:
            return
        self._seq_len_cached = seq_len
        t = torch.arange(seq_len, device=device).float()
        freqs = torch.outer(t, self.inv_freq)
        emb = torch.cat([freqs, freqs], dim=-1)          # (seq, dim)
        self._cos_cached = emb.cos()[None, None, :, :]   # (1,1,seq,dim)
        self._sin_cached = emb.sin()[None, None, :, :]

    def forward(self, q: torch.Tensor, k: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        seq_len = q.shape[2]
        self._build_cache(seq_len, q.device)
        cos = self._cos_cached[:, :, :seq_len, :].to(q.dtype)
        sin = self._sin_cached[:, :, :seq_len, :].to(q.dtype)
        q = _apply_rotary(q, cos, sin)
        k = _apply_rotary(k, cos, sin)
        return q, k


def _rotate_half(x: torch.Tensor) -> torch.Tensor:
    half = x.shape[-1] // 2
    x1 = x[..., :half]
    x2 = x[..., half:]
    return torch.cat([-x2, x1], dim=-1)


def _apply_rotary(x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    return x * cos + _rotate_half(x) * sin


# ── Multi-Head Attention ───────────────────────────────────────────────────────

class MultiHeadAttention(nn.Module):
    """
    Multi-Head (or Grouped-Query) Causal Attention.

    If num_kv_heads is None  → standard MHA (num_kv_heads = num_heads)
    If num_kv_heads = 1      → Multi-Query Attention (MQA)
    If 1 < num_kv_heads < h  → Grouped-Query Attention (GQA)
    """

    def __init__(
        self,
        d_model: int,
        num_heads: int,
        num_kv_heads: Optional[int] = None,
        dropout: float = 0.0,
        bias: bool = False,
        use_rope: bool = True,
        rope_base: int = 10000,
    ):
        super().__init__()
        assert d_model % num_heads == 0, "d_model must be divisible by num_heads"

        self.num_heads    = num_heads
        self.num_kv_heads = num_kv_heads if num_kv_heads is not None else num_heads
        self.head_dim     = d_model // num_heads
        self.d_model      = d_model
        self.scale        = self.head_dim ** -0.5

        # Q has num_heads, K/V have num_kv_heads
        self.q_proj  = nn.Linear(d_model, num_heads * self.head_dim, bias=bias)
        self.k_proj  = nn.Linear(d_model, self.num_kv_heads * self.head_dim, bias=bias)
        self.v_proj  = nn.Linear(d_model, self.num_kv_heads * self.head_dim, bias=bias)
        self.out_proj = nn.Linear(d_model, d_model, bias=bias)

        self.attn_drop = nn.Dropout(dropout)
        self.resid_drop = nn.Dropout(dropout)

        self.use_rope = use_rope
        if use_rope:
            self.rope = RotaryEmbedding(self.head_dim, base=rope_base)

    def _split_heads(self, x: torch.Tensor, num_h: int) -> torch.Tensor:
        """(B, T, num_h * head_dim) → (B, num_h, T, head_dim)"""
        B, T, _ = x.shape
        x = x.view(B, T, num_h, self.head_dim)
        return x.transpose(1, 2)

    def _repeat_kv(self, kv: torch.Tensor) -> torch.Tensor:
        """Expand KV heads to match Q heads for GQA."""
        if self.num_kv_heads == self.num_heads:
            return kv
        repeat_factor = self.num_heads // self.num_kv_heads
        return kv.repeat_interleave(repeat_factor, dim=1)

    def forward(
        self,
        x: torch.Tensor,
        mask: Optional[torch.Tensor] = None,  # (B, 1, T, T) or (T, T)
    ) -> torch.Tensor:
        B, T, _ = x.shape

        q = self._split_heads(self.q_proj(x), self.num_heads)     # (B,H,T,hd)
        k = self._split_heads(self.k_proj(x), self.num_kv_heads)  # (B,Hkv,T,hd)
        v = self._split_heads(self.v_proj(x), self.num_kv_heads)  # (B,Hkv,T,hd)

        if self.use_rope:
            q, k = self.rope(q, k)

        k = self._repeat_kv(k)   # (B,H,T,hd)
        v = self._repeat_kv(v)   # (B,H,T,hd)

        # Use PyTorch SDPA (Flash Attention) — never materializes full (B,H,T,T) matrix
        # Available in PyTorch 2.0+, massively reduces VRAM usage
        out = F.scaled_dot_product_attention(
            q, k, v,
            attn_mask=None,
            dropout_p=self.attn_drop.p if self.training else 0.0,
            is_causal=True,
        )  # (B,H,T,hd)
        out = out.transpose(1, 2).contiguous().view(B, T, self.d_model)
        out = self.resid_drop(self.out_proj(out))
        return out
