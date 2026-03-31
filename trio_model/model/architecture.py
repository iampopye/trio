"""
Trio AI — Core Architecture
Decoder-only Transformer with:
  - RMSNorm (instead of LayerNorm)
  - SwiGLU feed-forward (Claude/LLaMA style)
  - RoPE attention (in attention.py)
  - Tied input/output embeddings
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import math
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.checkpoint import checkpoint as grad_checkpoint
from typing import Optional

from trio_model.config import TrioConfig
from trio_model.model.attention import MultiHeadAttention


# ── RMS Normalization ──────────────────────────────────────────────────────────

class RMSNorm(nn.Module):
    """Root Mean Square Layer Normalization — faster & more stable than LayerNorm."""

    def __init__(self, dim: int, eps: float = 1e-6):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def _norm(self, x: torch.Tensor) -> torch.Tensor:
        return x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.weight * self._norm(x.float()).type_as(x)


# ── SwiGLU Feed-Forward ────────────────────────────────────────────────────────

class SwiGLUFeedForward(nn.Module):
    """
    SwiGLU activation: FFN(x) = (Wx ⊙ swish(Vx)) W2
    Used in PaLM, LLaMA, Claude.
    """

    def __init__(self, d_model: int, ff_dim: int, bias: bool = False):
        super().__init__()
        # Hidden dim adjusted to keep param count similar to standard FFN
        hidden = int(2 * ff_dim / 3)
        hidden = _make_multiple(hidden, 256)  # align to 256 for CUDA efficiency
        self.w1 = nn.Linear(d_model, hidden, bias=bias)  # gate
        self.w2 = nn.Linear(hidden, d_model, bias=bias)  # output
        self.w3 = nn.Linear(d_model, hidden, bias=bias)  # value

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.w2(F.silu(self.w1(x)) * self.w3(x))


class GELUFeedForward(nn.Module):
    """Standard GELU feed-forward (fallback when SwiGLU is disabled)."""

    def __init__(self, d_model: int, ff_dim: int, bias: bool = False):
        super().__init__()
        self.fc1 = nn.Linear(d_model, ff_dim, bias=bias)
        self.fc2 = nn.Linear(ff_dim, d_model, bias=bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc2(F.gelu(self.fc1(x)))


def _make_multiple(n: int, multiple: int) -> int:
    return ((n + multiple - 1) // multiple) * multiple


# ── Transformer Block ──────────────────────────────────────────────────────────

class TrioBlock(nn.Module):
    """Single Trio transformer block: Norm → Attention → Norm → FFN."""

    def __init__(self, cfg: TrioConfig):
        super().__init__()
        self.norm1 = RMSNorm(cfg.d_model)
        self.attn  = MultiHeadAttention(
            d_model      = cfg.d_model,
            num_heads    = cfg.num_heads,
            num_kv_heads = cfg.num_kv_heads,
            dropout      = cfg.dropout,
            bias         = cfg.bias,
            use_rope     = cfg.use_rope,
            rope_base    = cfg.rope_base,
        )
        self.norm2 = RMSNorm(cfg.d_model)
        if cfg.use_swiglu:
            self.ff = SwiGLUFeedForward(cfg.d_model, cfg.ff_dim, cfg.bias)
        else:
            self.ff = GELUFeedForward(cfg.d_model, cfg.ff_dim, cfg.bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Pre-norm residual (more stable than post-norm)
        x = x + self.attn(self.norm1(x))
        x = x + self.ff(self.norm2(x))
        return x


# ── Main Trio Model ────────────────────────────────────────────────────────────

class TrioModel(nn.Module):
    """
    Trio: A decoder-only language model.

    Architecture:
        Token Embedding → [N × TrioBlock] → RMSNorm → LM Head
    """

    def __init__(self, cfg: TrioConfig):
        super().__init__()
        self.cfg = cfg

        self.token_embedding = nn.Embedding(cfg.vocab_size, cfg.d_model)
        self.drop            = nn.Dropout(cfg.dropout)
        self.blocks          = nn.ModuleList([TrioBlock(cfg) for _ in range(cfg.num_layers)])
        self.norm_f          = RMSNorm(cfg.d_model)
        self._use_gradient_checkpointing = False

        # LM head — tied weights with token embedding (saves params, improves perf)
        self.lm_head = nn.Linear(cfg.d_model, cfg.vocab_size, bias=False)
        self.lm_head.weight = self.token_embedding.weight   # weight tying

        # Init weights
        self.apply(self._init_weights)
        # Scale residual projections (GPT-2 style)
        for name, p in self.named_parameters():
            if name.endswith("out_proj.weight") or name.endswith("w2.weight"):
                nn.init.normal_(p, mean=0.0, std=0.02 / math.sqrt(2 * cfg.num_layers))

    def _init_weights(self, module: nn.Module):
        if isinstance(module, nn.Linear):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)
            if module.bias is not None:
                nn.init.zeros_(module.bias)
        elif isinstance(module, nn.Embedding):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def forward(
        self,
        input_ids: torch.Tensor,           # (B, T)
        targets: Optional[torch.Tensor] = None,   # (B, T) for training
    ):
        B, T = input_ids.shape
        assert T <= self.cfg.context_length, (
            f"Sequence length {T} exceeds model context length {self.cfg.context_length}"
        )

        # Embed tokens
        x = self.drop(self.token_embedding(input_ids))  # (B, T, d_model)

        # Pass through transformer blocks (with optional gradient checkpointing)
        for block in self.blocks:
            if self._use_gradient_checkpointing and self.training:
                x = grad_checkpoint(block, x, use_reentrant=False)
            else:
                x = block(x)

        x = self.norm_f(x)           # final norm
        logits = self.lm_head(x)     # (B, T, vocab_size)

        if targets is not None:
            # Cross-entropy loss (shift already handled in dataset)
            loss = F.cross_entropy(
                logits.view(-1, self.cfg.vocab_size),
                targets.view(-1),
                ignore_index=-1,
            )
            return logits, loss

        return logits, None

    @torch.no_grad()
    def generate(
        self,
        input_ids: torch.Tensor,      # (B, T_prompt)
        max_new_tokens: int = 200,
        temperature: float = 0.8,
        top_k: int = 50,
        top_p: float = 0.95,
        eos_token_id: Optional[int] = None,
    ) -> torch.Tensor:
        """Autoregressive generation with temperature, top-k, and top-p sampling."""
        self.eval()
        for _ in range(max_new_tokens):
            ctx = input_ids[:, -self.cfg.context_length:]     # trim to ctx window
            logits, _ = self(ctx)
            logits = logits[:, -1, :] / temperature            # last token logits

            # Top-k filter
            if top_k > 0:
                v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
                logits[logits < v[:, [-1]]] = -float("inf")

            # Top-p (nucleus) filter
            if top_p < 1.0:
                sorted_logits, sorted_idx = torch.sort(logits, descending=True)
                cum_probs = torch.cumsum(F.softmax(sorted_logits, dim=-1), dim=-1)
                remove = cum_probs - F.softmax(sorted_logits, dim=-1) > top_p
                sorted_logits[remove] = -float("inf")
                logits = torch.scatter(logits, 1, sorted_idx, sorted_logits)

            probs  = F.softmax(logits, dim=-1)
            next_t = torch.multinomial(probs, num_samples=1)
            input_ids = torch.cat([input_ids, next_t], dim=1)

            if eos_token_id is not None and (next_t == eos_token_id).all():
                break

        return input_ids

    def gradient_checkpointing_enable(self):
        """Enable gradient checkpointing to save VRAM (trades compute for memory)."""
        self._use_gradient_checkpointing = True

    def gradient_checkpointing_disable(self):
        """Disable gradient checkpointing."""
        self._use_gradient_checkpointing = False

    def num_parameters(self, only_trainable: bool = True) -> int:
        params = self.parameters() if not only_trainable else (
            p for p in self.parameters() if p.requires_grad
        )
        return sum(p.numel() for p in params)
