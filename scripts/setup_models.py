"""Download GGUF model files and register them as Ollama models.

Usage:
    python scripts/setup_models.py              # Download and install both models
    python scripts/setup_models.py --max-only   # Only trio-max
    python scripts/setup_models.py --nano-only  # Only trio-nano
    trio train --setup                          # Same as running this script

Downloads quantized GGUF weights from HuggingFace and creates white-labeled
Ollama models named "trio-max" and "trio-nano".
"""

import os
import sys
import time
import shutil
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from argparse import ArgumentParser


# ── Model definitions ────────────────────────────────────────────────────────

MODELS = {
    "trio-nano": {
        "url": "https://huggingface.co/mrtechgarg/trio-nano/resolve/main/trio-nano-q4_k_m.gguf",
        "filename": "trio-nano-q4_k_m.gguf",
        "modelfile": "trio-nano.Modelfile",
        "description": "trio-nano -- ultra-fast 3B model for edge and mobile",
        "expected_size_gb": 1.8,
        "tier": "nano",
    },
    "trio-small": {
        "url": "https://huggingface.co/mrtechgarg/trio-small/resolve/main/trio-small-q4_k_m.gguf",
        "filename": "trio-small-q4_k_m.gguf",
        "modelfile": "trio-small.Modelfile",
        "description": "trio-small -- lightweight 4B model for everyday tasks",
        "expected_size_gb": 2.8,
        "tier": "small",
    },
    "trio-medium": {
        "url": "https://huggingface.co/mrtechgarg/trio-medium/resolve/main/trio-medium-q4_k_m.gguf",
        "filename": "trio-medium-q4_k_m.gguf",
        "modelfile": "trio-medium.Modelfile",
        "description": "trio-medium -- balanced 8B model for quality and speed",
        "expected_size_gb": 5.0,
        "tier": "medium",
    },
    "trio-high": {
        "url": "https://huggingface.co/mrtechgarg/trio-high/resolve/main/trio-high-q4_k_m.gguf",
        "filename": "trio-high-q4_k_m.gguf",
        "modelfile": "trio-high.Modelfile",
        "description": "trio-high -- high quality 9B model with multimodal support",
        "expected_size_gb": 5.5,
        "tier": "high",
    },
    "trio-max": {
        "url": "https://huggingface.co/mrtechgarg/trio-max/resolve/main/trio-max-q4_k_m.gguf",
        "filename": "trio-max-q4_k_m.gguf",
        "modelfile": "trio-max.Modelfile",
        "description": "trio-max -- best quality 12B model for consumer GPU",
        "expected_size_gb": 7.0,
        "tier": "max",
    },
    "trio-pro": {
        "url": "https://huggingface.co/mrtechgarg/trio-pro/resolve/main/trio-pro-q4_k_m.gguf",
        "filename": "trio-pro-q4_k_m.gguf",
        "modelfile": "trio-pro.Modelfile",
        "description": "trio-pro -- premium 30B MoE model for pro workloads",
        "expected_size_gb": 17.0,
        "tier": "pro",
    },
}

REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = REPO_ROOT / "models"


# ── Progress bar ─────────────────────────────────────────────────────────────

def _format_size(num_bytes: int) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num_bytes) < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def _progress_bar(current: int, total: int, width: int = 40) -> str:
    """Render a simple ASCII progress bar."""
    if total <= 0:
        return "[" + "?" * width + "]"
    frac = min(current / total, 1.0)
    filled = int(width * frac)
    bar = "#" * filled + "-" * (width - filled)
    pct = frac * 100
    return f"[{bar}] {pct:5.1f}%"


# ── Download with resume support ─────────────────────────────────────────────

def download_file(url: str, dest: Path, description: str = "") -> bool:
    """Download a file with progress display and resume-on-interrupt support.

    If a partial file already exists, sends a Range header to resume from
    where the previous download left off.

    Returns True on success, False on failure.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")

    # Determine how much we already have
    existing_bytes = 0
    if partial.exists():
        existing_bytes = partial.stat().st_size
        print(f"  Resuming download from {_format_size(existing_bytes)}...")

    # Build request with optional Range header
    req = urllib.request.Request(url, headers={"User-Agent": "trio-ai/setup"})
    if existing_bytes > 0:
        req.add_header("Range", f"bytes={existing_bytes}-")

    # Try normal SSL first, fall back to unverified on cert errors
    import ssl
    ssl_ctx = None
    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except (urllib.error.URLError, OSError) as first_err:
        if "SSL" in str(first_err) or "CERTIFICATE" in str(first_err).upper():
            print("  SSL cert issue, retrying without verification...")
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            try:
                resp = urllib.request.urlopen(req, timeout=60, context=ssl_ctx)
            except urllib.error.HTTPError as e:
                if e.code == 416:
                    print(f"  File already fully downloaded.")
                    if partial.exists():
                        shutil.move(str(partial), str(dest))
                    return True
                print(f"  HTTP Error {e.code}: {e.reason}")
                return False
            except Exception as e:
                print(f"  Download error: {e}")
                return False
        else:
            raise first_err
    except urllib.error.HTTPError as e:
        if e.code == 416:
            # Range not satisfiable — file is already complete
            print(f"  File already fully downloaded.")
            if partial.exists():
                shutil.move(str(partial), str(dest))
            return True
        print(f"  HTTP Error {e.code}: {e.reason}")
        return False
    except urllib.error.URLError as e:
        print(f"  Connection error: {e.reason}")
        return False
    except Exception as e:
        print(f"  Download error: {e}")
        return False

    # Determine total size
    content_length = resp.headers.get("Content-Length")
    if content_length is not None:
        content_length = int(content_length)

    # Check if server supports range requests
    content_range = resp.headers.get("Content-Range")
    if content_range and existing_bytes > 0:
        # Server acknowledged our range — total size is in the header
        # Format: "bytes START-END/TOTAL"
        try:
            total_size = int(content_range.split("/")[-1])
        except (ValueError, IndexError):
            total_size = existing_bytes + (content_length or 0)
    elif existing_bytes > 0 and content_length is not None:
        # Server ignored Range header and sent full file — start over
        print(f"  Server does not support resume. Downloading from scratch...")
        existing_bytes = 0
        total_size = content_length
    else:
        total_size = content_length or 0

    if description:
        print(f"  {description}")
    if total_size > 0:
        print(f"  Total size: {_format_size(total_size)}")

    # Download
    chunk_size = 1024 * 1024  # 1 MB chunks
    downloaded = existing_bytes
    start_time = time.time()
    last_print_time = 0

    try:
        mode = "ab" if existing_bytes > 0 and content_range else "wb"
        with open(partial, mode) as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)

                now = time.time()
                if now - last_print_time >= 0.5:
                    elapsed = now - start_time
                    speed = (downloaded - existing_bytes) / elapsed if elapsed > 0 else 0
                    if total_size > 0:
                        bar = _progress_bar(downloaded, total_size)
                        eta = (total_size - downloaded) / speed if speed > 0 else 0
                        print(
                            f"\r  {bar}  {_format_size(downloaded)}/{_format_size(total_size)}"
                            f"  {_format_size(int(speed))}/s  ETA: {int(eta)}s   ",
                            end="",
                            flush=True,
                        )
                    else:
                        print(
                            f"\r  Downloaded: {_format_size(downloaded)}  {_format_size(int(speed))}/s   ",
                            end="",
                            flush=True,
                        )
                    last_print_time = now

        print()  # newline after progress bar

    except KeyboardInterrupt:
        print(f"\n  Download interrupted at {_format_size(downloaded)}.")
        print(f"  Partial file saved. Run again to resume.")
        return False
    except Exception as e:
        print(f"\n  Download error: {e}")
        print(f"  Partial file saved at {partial}. Run again to resume.")
        return False

    # Verify size if known
    if total_size > 0 and downloaded < total_size:
        print(f"  Warning: downloaded {_format_size(downloaded)} but expected {_format_size(total_size)}")
        print(f"  Partial file saved. Run again to resume.")
        return False

    # Move partial to final destination
    if dest.exists():
        dest.unlink()
    shutil.move(str(partial), str(dest))
    elapsed = time.time() - start_time
    print(f"  Saved: {dest.name} ({_format_size(dest.stat().st_size)}) in {elapsed:.0f}s")
    return True


# ── Ollama model creation ────────────────────────────────────────────────────

def check_ollama() -> bool:
    """Check if ollama CLI is available."""
    try:
        result = subprocess.run(
            ["ollama", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            version = result.stdout.strip() or result.stderr.strip()
            print(f"  Ollama found: {version}")
            return True
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"  Error checking Ollama: {e}")
    print("  ERROR: Ollama is not installed or not on PATH.")
    print("  Install it from: https://ollama.com/download")
    return False


def create_ollama_model(model_name: str, modelfile_path: Path) -> bool:
    """Create an Ollama model from a Modelfile.

    Runs: ollama create <model_name> -f <modelfile_path>
    The working directory is set to the modelfile's parent so relative
    paths to GGUF files resolve correctly.
    """
    print(f"\n  Creating Ollama model '{model_name}'...")
    print(f"  Modelfile: {modelfile_path}")

    try:
        result = subprocess.run(
            ["ollama", "create", model_name, "-f", str(modelfile_path)],
            cwd=str(modelfile_path.parent),
            capture_output=False,
            timeout=600,
        )
        if result.returncode == 0:
            print(f"  Model '{model_name}' created successfully!")
            return True
        else:
            print(f"  Failed to create model '{model_name}' (exit code {result.returncode})")
            return False
    except subprocess.TimeoutExpired:
        print(f"  Timeout creating model '{model_name}' (>10 minutes)")
        return False
    except Exception as e:
        print(f"  Error creating model: {e}")
        return False


def verify_ollama_model(model_name: str) -> bool:
    """Verify a model is registered in Ollama by listing models."""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return model_name in result.stdout
    except Exception:
        pass
    return False


# ── Main setup flow ──────────────────────────────────────────────────────────

def setup(models_to_install: list[str] | None = None):
    """Download GGUF files and register them as Ollama models.

    Args:
        models_to_install: List of model names to install.
            If None, installs all models.
    """
    if models_to_install is None:
        models_to_install = list(MODELS.keys())

    print()
    print("=" * 64)
    print("  trio.ai — Model Setup")
    print("  Downloads and installs local AI models via Ollama")
    print("=" * 64)
    print()

    # Check prerequisites
    print("[1/3] Checking prerequisites...")
    if not check_ollama():
        sys.exit(1)
    print()

    # Download GGUF files
    print("[2/3] Downloading model weights...")
    downloaded = []
    for name in models_to_install:
        info = MODELS[name]
        dest = MODELS_DIR / info["filename"]

        if dest.exists():
            size_gb = dest.stat().st_size / (1024 ** 3)
            print(f"\n  {info['description']}")
            print(f"  Already downloaded: {dest.name} ({size_gb:.2f} GB)")
            downloaded.append(name)
            continue

        print(f"\n  Downloading {info['description']}...")
        print(f"  Source: trio.ai model registry")
        if download_file(info["url"], dest, description=""):
            downloaded.append(name)
        else:
            print(f"  FAILED to download {name}. Skipping Ollama registration.")
    print()

    # Create Ollama models
    print("[3/3] Registering models with Ollama...")
    created = []
    for name in downloaded:
        info = MODELS[name]
        modelfile_path = MODELS_DIR / info["modelfile"]
        gguf_path = MODELS_DIR / info["filename"]

        if not modelfile_path.exists():
            print(f"  Modelfile not found: {modelfile_path}")
            continue
        if not gguf_path.exists():
            print(f"  GGUF file not found: {gguf_path}")
            continue

        if create_ollama_model(name, modelfile_path):
            created.append(name)

    # Summary
    print()
    print("=" * 64)
    print("  Setup Complete!")
    print(f"  Downloaded: {len(downloaded)}/{len(models_to_install)} models")
    print(f"  Registered: {len(created)}/{len(downloaded)} models in Ollama")
    print("=" * 64)

    if created:
        print("\n  Installed models:")
        for name in created:
            verified = verify_ollama_model(name)
            status = "OK" if verified else "may need verification"
            print(f"    - {name} ({status})")

        print(f"\n  Test with:")
        print(f"    ollama run trio-max 'Hello, who are you?'")
        print(f"    trio agent -m 'Hello'")
    else:
        print("\n  No models were fully installed.")
        print("  Check the errors above and try again.")

    print()
    return len(created) == len(models_to_install)


# ── CLI entry point ──────────────────────────────────────────────────────────

def main():
    parser = ArgumentParser(description="Download and install trio.ai models")
    parser.add_argument(
        "--model",
        choices=list(MODELS.keys()),
        help="Install a specific model (e.g. trio-small, trio-max)",
    )
    parser.add_argument(
        "--tier",
        choices=["nano", "small", "medium", "high", "max", "pro"],
        help="Install by tier name",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Install all 6 models",
    )
    parser.add_argument(
        "--recommended",
        action="store_true",
        help="Install trio-nano + trio-small (lightweight, runs on any machine)",
    )
    args = parser.parse_args()

    if args.model:
        models = [args.model]
    elif args.tier:
        models = [f"trio-{args.tier}"]
    elif args.all:
        models = list(MODELS.keys())
    elif args.recommended:
        models = ["trio-nano", "trio-small"]
    else:
        # Default: install trio-small (best balance for most users)
        models = ["trio-small"]

    success = setup(models_to_install=models)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
