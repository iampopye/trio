"""
trio_model — Trio LLM Engine
Decoder-only transformer with RoPE, RMSNorm, SwiGLU, and GQA.
Train from scratch, fine-tune with SFT + Constitutional AI.
"""

from .config import TrioConfig, get_config, NanoConfig, SmallConfig, MediumConfig
from .model.architecture import TrioModel
from .model.attention import MultiHeadAttention

__all__ = [
    "TrioConfig", "get_config", "NanoConfig", "SmallConfig", "MediumConfig",
    "TrioModel", "MultiHeadAttention",
]
