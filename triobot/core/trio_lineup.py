"""Single source of truth for the 6 trio model tiers.

Each :class:`TrioTier` describes a model the ``triobot`` launcher can
download from HuggingFace and register with the local Ollama daemon.

The lineup here is consumed by:

- ``triobot.cli.launch_cmd`` — the arrow-key picker + orchestrator
- ``triobot.core.hf_download`` — HuggingFace GGUF downloader
- ``triobot.core.ollama_local`` — Ollama daemon and ``ollama create`` wrappers
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class TrioTier:
    """One tier in the trio model lineup."""

    name: str
    hf_repo: str
    gguf_filename: str
    modelfile_name: str
    size_gb: float
    params: str
    description: str

    @property
    def hf_url(self) -> str:
        """Direct HuggingFace download URL for the GGUF blob."""
        return (
            f"https://huggingface.co/{self.hf_repo}/resolve/main/"
            f"{self.gguf_filename}"
        )


# ── The lineup ────────────────────────────────────────────────────────────────
#
# Repos: mrtechgarg/trio-<tier>      (HuggingFace, public)
# GGUF:  trio-<tier>-q4_k_m.gguf     (matches bundled Modelfiles)
# Sizes: locked by user spec.        (do not edit without coordination)
TRIO_LINEUP: Tuple[TrioTier, ...] = (
    TrioTier(
        name="trio-nano",
        hf_repo="mrtechgarg/trio-nano",
        gguf_filename="trio-nano-q4_k_m.gguf",
        modelfile_name="trio-nano.Modelfile",
        size_gb=1.0,
        params="3B",
        description="Ultra-fast, edge/mobile",
    ),
    TrioTier(
        name="trio-small",
        hf_repo="mrtechgarg/trio-small",
        gguf_filename="trio-small-q4_k_m.gguf",
        modelfile_name="trio-small.Modelfile",
        size_gb=2.4,
        params="4B",
        description="Everyday tasks",
    ),
    TrioTier(
        name="trio-medium",
        hf_repo="mrtechgarg/trio-medium",
        gguf_filename="trio-medium-q4_k_m.gguf",
        modelfile_name="trio-medium.Modelfile",
        size_gb=5.0,
        params="8B",
        description="Balanced quality + speed",
    ),
    TrioTier(
        name="trio-high",
        hf_repo="mrtechgarg/trio-high",
        gguf_filename="trio-high-q4_k_m.gguf",
        modelfile_name="trio-high.Modelfile",
        size_gb=5.7,
        params="9B",
        description="High quality, multimodal",
    ),
    TrioTier(
        name="trio-max",
        hf_repo="mrtechgarg/trio-max",
        gguf_filename="trio-max-q4_k_m.gguf",
        modelfile_name="trio-max.Modelfile",
        size_gb=7.5,
        params="12B",
        description="Best on consumer GPU",
    ),
    TrioTier(
        name="trio-pro",
        hf_repo="mrtechgarg/trio-pro",
        gguf_filename="trio-pro-q4_k_m.gguf",
        modelfile_name="trio-pro.Modelfile",
        size_gb=18.0,
        params="30B",
        description="Premium, pro workloads",
    ),
)


# ── Public lookup helpers ─────────────────────────────────────────────────────

def tier_names() -> tuple[str, ...]:
    """Return the tier names in lineup order."""
    return tuple(t.name for t in TRIO_LINEUP)


def get_tier(name: str) -> TrioTier | None:
    """Look up a tier by ``name`` (case-sensitive). Returns ``None`` if missing."""
    for tier in TRIO_LINEUP:
        if tier.name == name:
            return tier
    return None
