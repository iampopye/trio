"""
Trio AI Model — Configuration
Defines nano / small / medium model presets.
"""

from dataclasses import dataclass, field
from typing import Optional
import yaml, os


@dataclass
class TrioConfig:
    # ── Model identity ──────────────────────────────────────────────
    model_name: str = "trio"
    version: str = "0.1.0"

    # ── Architecture ─────────────────────────────────────────────────
    vocab_size: int = 50257          # BPE vocab (GPT-2 compatible to start)
    context_length: int = 256        # max tokens per sequence
    d_model: int = 128               # embedding / hidden dimension
    num_heads: int = 4               # attention heads
    num_layers: int = 4              # transformer blocks
    ff_dim: int = 512                # feed-forward hidden size (4 × d_model)
    dropout: float = 0.1
    bias: bool = False               # no bias → cleaner, faster

    # ── Positional Encoding ──────────────────────────────────────────
    use_rope: bool = True            # Rotary Position Embedding
    rope_base: int = 10000

    # ── Activation ───────────────────────────────────────────────────
    use_swiglu: bool = True          # SwiGLU (Claude-style) vs GELU

    # ── Attention ────────────────────────────────────────────────────
    num_kv_heads: Optional[int] = None   # None = Multi-Head; int = GQA/MQA

    # ── Training ─────────────────────────────────────────────────────
    batch_size: int = 4
    gradient_accumulation_steps: int = 4   # effective batch = 16
    learning_rate: float = 3e-4
    weight_decay: float = 0.1
    max_iters: int = 5000
    warmup_iters: int = 200
    eval_interval: int = 250
    eval_iters: int = 50
    save_interval: int = 500
    grad_clip: float = 1.0

    # ── Data ─────────────────────────────────────────────────────────
    data_dir: str = "data/corpus"
    checkpoint_dir: str = "checkpoints"
    log_dir: str = "logs"

    # ── Device ───────────────────────────────────────────────────────
    device: str = "cpu"             # "cpu" | "cuda" | "mps"
    dtype: str = "float32"          # "float32" | "float16" | "bfloat16"

    # ── Constitutional AI ─────────────────────────────────────────────
    constitution_path: str = "training/constitution.md"

    def num_parameters(self) -> int:
        """Estimate number of trainable parameters."""
        embed    = self.vocab_size * self.d_model
        pos      = self.context_length * self.d_model if not self.use_rope else 0
        attn     = self.num_layers * (4 * self.d_model ** 2)
        ff_size  = self.ff_dim if not self.use_swiglu else int(self.ff_dim * 2 / 3) * 2
        ff       = self.num_layers * (self.d_model * ff_size + ff_size * self.d_model)
        lm_head  = self.d_model * self.vocab_size
        return embed + pos + attn + ff + lm_head

    def save(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(self.__dict__, f, default_flow_style=False)

    @classmethod
    def load(cls, path: str) -> "TrioConfig":
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)


# ── Preset Configs ────────────────────────────────────────────────────────────

def NanoConfig() -> TrioConfig:
    """~1M params — runs on Mac Mini 4GB RAM. For local dev & testing."""
    return TrioConfig(
        model_name="trio-nano",
        vocab_size=10000,
        context_length=256,
        d_model=128,
        num_heads=4,
        num_layers=4,
        ff_dim=512,
        batch_size=4,
        gradient_accumulation_steps=4,
        learning_rate=3e-4,
        max_iters=5000,
        device="cpu",
        dtype="float32",
    )


def SmallConfig() -> TrioConfig:
    """~125M params — runs on Kaggle T4 (16GB VRAM) or Colab Pro."""
    return TrioConfig(
        model_name="trio-small",
        vocab_size=50257,
        context_length=1024,
        d_model=768,
        num_heads=12,
        num_layers=12,
        ff_dim=3072,
        batch_size=8,
        gradient_accumulation_steps=8,
        learning_rate=1e-4,
        max_iters=50000,
        warmup_iters=2000,
        device="cuda",
        dtype="float16",
    )


def MediumConfig() -> TrioConfig:
    """~1B params — runs on RunPod A100 (40GB+ VRAM)."""
    return TrioConfig(
        model_name="trio-medium",
        vocab_size=50257,
        context_length=4096,
        d_model=2048,
        num_heads=16,
        num_layers=24,
        ff_dim=8192,
        num_kv_heads=8,        # Grouped Query Attention
        batch_size=4,
        gradient_accumulation_steps=16,
        learning_rate=3e-5,
        max_iters=200000,
        warmup_iters=5000,
        device="cuda",
        dtype="bfloat16",
    )


PRESETS = {
    "nano":   NanoConfig,
    "small":  SmallConfig,
    "medium": MediumConfig,
}


def get_config(preset: str = "nano") -> TrioConfig:
    if preset not in PRESETS:
        raise ValueError(f"Unknown preset '{preset}'. Choose from: {list(PRESETS.keys())}")
    cfg = PRESETS[preset]()
    params = cfg.num_parameters()
    print(f"[Trio] Config: {cfg.model_name}  |  ~{params/1e6:.1f}M parameters")
    return cfg
