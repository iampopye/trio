"""trio.ai hardware auto-detection and model recommendation engine.

Detects CPU, GPU, RAM across Windows, macOS, and Linux and recommends
the best trio model tier for the current machine.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

import os
import platform
import shutil
import subprocess  # nosec B404
from dataclasses import dataclass, asdict
from typing import Optional


# ── Data Model ────────────────────────────────────────────────────────────────

@dataclass
class HardwareInfo:
    """Snapshot of detected hardware capabilities."""

    cpu_name: str = "unknown"
    cpu_cores: int = 0
    ram_gb: float = 0.0
    gpu_name: str = "none detected"
    gpu_vram_gb: float = 0.0
    has_cuda: bool = False
    has_metal: bool = False
    has_rocm: bool = False
    os_name: str = "unknown"
    os_version: str = "unknown"

    def to_dict(self) -> dict:
        return asdict(self)


# ── Trio model tiers ──────────────────────────────────────────────────────────

TRIO_MODELS = [
    {"name": "trio-nano",   "params": "3B",  "size_gb": 1.0,  "description": "Ultra-fast, edge/mobile"},
    {"name": "trio-small",  "params": "4B",  "size_gb": 2.5,  "description": "Everyday tasks"},
    {"name": "trio-medium", "params": "8B",  "size_gb": 4.7,  "description": "Balanced quality + speed"},
    {"name": "trio-high",   "params": "9B",  "size_gb": 5.3,  "description": "High quality, multimodal"},
    {"name": "trio-max",    "params": "12B", "size_gb": 7.0,  "description": "Best on consumer GPU"},
    {"name": "trio-pro",    "params": "30B", "size_gb": 18.0, "description": "Premium, pro workloads"},
]


# ── CPU Detection ─────────────────────────────────────────────────────────────

def _detect_cpu_name() -> str:
    """Return a human-readable CPU name."""
    system = platform.system()

    if system == "Windows":
        # Windows: read from environment or wmic
        cpu = os.environ.get("PROCESSOR_IDENTIFIER", "")
        if cpu:
            return cpu
        try:
            out = subprocess.check_output(  # nosec B603 B607
                ["wmic", "cpu", "get", "Name"],
                text=True, timeout=5, stderr=subprocess.DEVNULL,
            ).strip()
            lines = [l.strip() for l in out.splitlines() if l.strip() and l.strip() != "Name"]
            if lines:
                return lines[0]
        except Exception:
            pass  # nosec B110

    elif system == "Linux":
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass  # nosec B110

    elif system == "Darwin":
        try:
            out = subprocess.check_output(  # nosec B603 B607
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                text=True, timeout=5,
            ).strip()
            if out:
                return out
        except Exception:
            pass  # nosec B110

    # Fallback
    return platform.processor() or "unknown"


# ── RAM Detection ─────────────────────────────────────────────────────────────

def _detect_ram_gb() -> float:
    """Return total system RAM in GB."""
    # Try psutil first (cross-platform)
    try:
        import psutil
        return round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except ImportError:
        pass  # nosec B110

    system = platform.system()

    if system == "Windows":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            mem = MEMORYSTATUSEX()
            mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
            return round(mem.ullTotalPhys / (1024 ** 3), 1)
        except Exception:
            pass  # nosec B110

    elif system == "Linux":
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return round(kb / (1024 ** 2), 1)
        except Exception:
            pass  # nosec B110

    elif system == "Darwin":
        try:
            out = subprocess.check_output(  # nosec B603 B607
                ["sysctl", "-n", "hw.memsize"], text=True, timeout=5,
            ).strip()
            return round(int(out) / (1024 ** 3), 1)
        except Exception:
            pass  # nosec B110

    return 0.0


# ── GPU Detection ─────────────────────────────────────────────────────────────

def _detect_gpu() -> tuple[str, float, bool, bool, bool]:
    """Detect GPU and return (name, vram_gb, has_cuda, has_metal, has_rocm)."""
    gpu_name = "none detected"
    gpu_vram_gb = 0.0
    has_cuda = False
    has_metal = False
    has_rocm = False

    # ── NVIDIA (nvidia-smi) ──
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            out = subprocess.check_output(  # nosec B603 B607
                [nvidia_smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                text=True, timeout=5, stderr=subprocess.DEVNULL,
            ).strip()
            if out:
                # Take the first GPU line
                first_line = out.splitlines()[0]
                parts = first_line.split(",")
                gpu_name = parts[0].strip()
                if len(parts) > 1:
                    try:
                        gpu_vram_gb = round(float(parts[1].strip()) / 1024, 1)
                    except ValueError:
                        pass  # nosec B110
                has_cuda = True
                return gpu_name, gpu_vram_gb, has_cuda, has_metal, has_rocm
        except Exception:
            pass  # nosec B110

    # Also check for CUDA via torch (in case nvidia-smi is missing)
    if not has_cuda:
        try:
            import torch  # type: ignore
            if torch.cuda.is_available():
                has_cuda = True
                gpu_name = torch.cuda.get_device_name(0)
                vram_bytes = torch.cuda.get_device_properties(0).total_mem
                gpu_vram_gb = round(vram_bytes / (1024 ** 3), 1)
                return gpu_name, gpu_vram_gb, has_cuda, has_metal, has_rocm
        except Exception:
            pass  # nosec B110

    # ── AMD ROCm ──
    rocm_smi = shutil.which("rocm-smi")
    if rocm_smi:
        has_rocm = True
        try:
            out = subprocess.check_output(  # nosec B603 B607
                [rocm_smi, "--showproductname"],
                text=True, timeout=5, stderr=subprocess.DEVNULL,
            ).strip()
            for line in out.splitlines():
                if "Card series" in line or "GPU" in line:
                    gpu_name = line.split(":")[-1].strip()
                    break
            else:
                gpu_name = "AMD ROCm GPU"
        except Exception:
            gpu_name = "AMD ROCm GPU"

        # Try to get VRAM
        try:
            vram_out = subprocess.check_output(  # nosec B603 B607
                [rocm_smi, "--showmeminfo", "vram"],
                text=True, timeout=5, stderr=subprocess.DEVNULL,
            ).strip()
            for line in vram_out.splitlines():
                if "Total" in line:
                    parts = line.split()
                    for p in parts:
                        try:
                            mb = float(p)
                            if mb > 100:  # likely MB value
                                gpu_vram_gb = round(mb / 1024, 1)
                                break
                        except ValueError:
                            continue
        except Exception:
            pass  # nosec B110

        return gpu_name, gpu_vram_gb, has_cuda, has_metal, has_rocm

    # ── Apple Metal ──
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        has_metal = True
        gpu_name = "Apple Silicon (unified memory)"
        # Apple Silicon shares RAM with GPU; report RAM as available VRAM
        ram = _detect_ram_gb()
        # A reasonable estimate: ~75% of unified memory can be used for ML
        gpu_vram_gb = round(ram * 0.75, 1)
        return gpu_name, gpu_vram_gb, has_cuda, has_metal, has_rocm

    return gpu_name, gpu_vram_gb, has_cuda, has_metal, has_rocm


# ── Public API ────────────────────────────────────────────────────────────────

def detect_hardware() -> HardwareInfo:
    """Auto-detect all hardware specs for the current machine."""
    gpu_name, gpu_vram_gb, has_cuda, has_metal, has_rocm = _detect_gpu()

    return HardwareInfo(
        cpu_name=_detect_cpu_name(),
        cpu_cores=os.cpu_count() or 0,
        ram_gb=_detect_ram_gb(),
        gpu_name=gpu_name,
        gpu_vram_gb=gpu_vram_gb,
        has_cuda=has_cuda,
        has_metal=has_metal,
        has_rocm=has_rocm,
        os_name=platform.system(),
        os_version=platform.release(),
    )


def recommend_model(hardware: HardwareInfo) -> dict:
    """Suggest the best trio model based on detected hardware.

    Returns a dict with keys: name, params, size_gb, description, reason.
    """
    ram = hardware.ram_gb
    vram = hardware.gpu_vram_gb

    # GPU with 8GB+ VRAM or 24GB+ RAM -> trio-pro
    if vram >= 8.0 or ram >= 24.0:
        tier = TRIO_MODELS[5]  # trio-pro
        reason = (
            f"GPU VRAM {vram:.1f} GB >= 8 GB" if vram >= 8.0
            else f"RAM {ram:.1f} GB >= 24 GB"
        )
    elif ram >= 16.0:
        tier = TRIO_MODELS[4]  # trio-max
        reason = f"RAM {ram:.1f} GB is in the 16-24 GB range"
    elif ram >= 12.0:
        tier = TRIO_MODELS[3]  # trio-high
        reason = f"RAM {ram:.1f} GB is in the 12-16 GB range"
    elif ram >= 8.0:
        tier = TRIO_MODELS[2]  # trio-medium
        reason = f"RAM {ram:.1f} GB is in the 8-12 GB range"
    elif ram >= 4.0:
        tier = TRIO_MODELS[1]  # trio-small
        reason = f"RAM {ram:.1f} GB is in the 4-8 GB range"
    else:
        tier = TRIO_MODELS[0]  # trio-nano
        reason = f"RAM {ram:.1f} GB < 4 GB"

    return {**tier, "reason": reason}


def get_gpu_layers(hardware: HardwareInfo, model_size_gb: float) -> int:
    """Calculate optimal n_gpu_layers for llama.cpp / GGUF inference.

    Returns 0 (CPU-only) if no GPU is usable, otherwise estimates
    how many transformer layers can fit in VRAM.
    """
    if not (hardware.has_cuda or hardware.has_metal or hardware.has_rocm):
        return 0

    vram = hardware.gpu_vram_gb
    if vram <= 0:
        return 0

    # Reserve ~500 MB for OS / context buffer overhead
    usable_vram = max(0, vram - 0.5)

    if usable_vram >= model_size_gb:
        # Entire model fits in VRAM -> offload all layers (use 999 as "all")
        return 999

    # Partial offload: proportion of layers that fit
    # Typical GGUF models have ~32-80 layers; use 48 as a reasonable midpoint
    estimated_layers = 48
    fraction = usable_vram / model_size_gb
    return max(1, int(estimated_layers * fraction))


def hardware_summary(hw: Optional[HardwareInfo] = None) -> str:
    """Return a human-readable multi-line summary of detected hardware."""
    if hw is None:
        hw = detect_hardware()

    rec = recommend_model(hw)
    gpu_layers = get_gpu_layers(hw, rec["size_gb"])

    accel = []
    if hw.has_cuda:
        accel.append("CUDA")
    if hw.has_metal:
        accel.append("Metal")
    if hw.has_rocm:
        accel.append("ROCm")
    accel_str = ", ".join(accel) if accel else "none"

    lines = [
        f"OS:          {hw.os_name} {hw.os_version}",
        f"CPU:         {hw.cpu_name} ({hw.cpu_cores} cores)",
        f"RAM:         {hw.ram_gb:.1f} GB",
        f"GPU:         {hw.gpu_name}",
        f"GPU VRAM:    {hw.gpu_vram_gb:.1f} GB",
        f"Accelerator: {accel_str}",
        "",
        f"Recommended: {rec['name']} ({rec['params']}, ~{rec['size_gb']} GB)",
        f"Reason:      {rec['reason']}",
        f"GPU layers:  {gpu_layers} {'(full offload)' if gpu_layers >= 999 else '(partial)' if gpu_layers > 0 else '(CPU only)'}",
    ]
    return "\n".join(lines)
