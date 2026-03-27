"""Upload trio.ai models to HuggingFace under the trioai organization.

This script takes downloaded GGUF models, renames them with trio branding,
and uploads to HuggingFace so download URLs show trio.ai instead of
third-party model names.

Usage:
    python scripts/upload_models.py --token hf_xxxxx
    python scripts/upload_models.py --token hf_xxxxx --model trio-small
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

# Mapping of trio model names to their local GGUF files
MODEL_FILES = {
    "trio-nano":   "trio-nano-q4_k_m.gguf",
    "trio-small":  "trio-small-q4_k_m.gguf",
    "trio-medium": "trio-medium-q4_k_m.gguf",
    "trio-high":   "trio-high-q4_k_m.gguf",
    "trio-max":    "trio-max-q4_k_m.gguf",
    "trio-pro":    "trio-pro-q4_k_m.gguf",
}

MODEL_DESCRIPTIONS = {
    "trio-nano":   "trio-nano -- ultra-fast 3B model for edge and mobile by trio.ai",
    "trio-small":  "trio-small -- lightweight 4B model for everyday tasks by trio.ai",
    "trio-medium": "trio-medium -- balanced 8B model for quality and speed by trio.ai",
    "trio-high":   "trio-high -- high quality 9B model with multimodal by trio.ai",
    "trio-max":    "trio-max -- best quality 12B model for consumer GPU by trio.ai",
    "trio-pro":    "trio-pro -- premium 30B MoE model for pro workloads by trio.ai",
}

HF_ORG = "trioai"


def upload_model(model_name: str, token: str):
    """Upload a single model to HuggingFace."""
    from huggingface_hub import HfApi, create_repo

    filename = MODEL_FILES.get(model_name)
    if not filename:
        print(f"  Unknown model: {model_name}")
        return False

    local_path = MODELS_DIR / filename
    if not local_path.exists():
        print(f"  File not found: {local_path}")
        print(f"  Download first: python scripts/setup_models.py --model {model_name}")
        return False

    size_gb = local_path.stat().st_size / (1024 ** 3)
    print(f"\n  Uploading {model_name} ({size_gb:.1f} GB) to huggingface.co/{HF_ORG}/{model_name}...")

    api = HfApi(token=token)

    # Create repo if it doesn't exist
    repo_id = f"{HF_ORG}/{model_name}"
    try:
        create_repo(
            repo_id=repo_id,
            token=token,
            repo_type="model",
            exist_ok=True,
            private=False,
        )
    except Exception as e:
        # Org might not exist, create under user instead
        print(f"  Note: Could not create under {HF_ORG} org ({e})")
        print(f"  Trying under your personal account...")
        user_info = api.whoami()
        username = user_info.get("name", "")
        repo_id = f"{username}/{model_name}"
        create_repo(
            repo_id=repo_id,
            token=token,
            repo_type="model",
            exist_ok=True,
            private=False,
        )
        print(f"  Created repo: {repo_id}")

    # Create a README for the model
    readme = f"""---
license: apache-2.0
tags:
  - trio.ai
  - gguf
  - local-inference
---

# {model_name}

{MODEL_DESCRIPTIONS.get(model_name, '')}

## Quick Start

```bash
pip install triobot
trio train --setup --model {model_name}
trio serve
```

## About

Part of the trio.ai model family:
- **trio-nano** -- 3B, ultra-fast
- **trio-small** -- 4B, everyday tasks
- **trio-medium** -- 8B, balanced
- **trio-high** -- 9B, high quality
- **trio-max** -- 12B, best consumer GPU
- **trio-pro** -- 30B MoE, premium

All models are free, local, and private. No API keys needed.

Built by [trio.ai](https://github.com/iampopye/trio)
"""

    # Upload README
    api.upload_file(
        path_or_fileobj=readme.encode("utf-8"),
        path_in_repo="README.md",
        repo_id=repo_id,
        token=token,
    )

    # Upload the GGUF file
    print(f"  Uploading {filename} ({size_gb:.1f} GB)... This may take a while.")
    api.upload_file(
        path_or_fileobj=str(local_path),
        path_in_repo=filename,
        repo_id=repo_id,
        token=token,
    )

    print(f"  [OK] Uploaded: https://huggingface.co/{repo_id}")
    print(f"  Download URL: https://huggingface.co/{repo_id}/resolve/main/{filename}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Upload trio.ai models to HuggingFace")
    parser.add_argument("--token", required=True, help="HuggingFace write token (hf_...)")
    parser.add_argument("--model", help="Upload a specific model (e.g. trio-small)")
    parser.add_argument("--all", action="store_true", help="Upload all available models")
    args = parser.parse_args()

    if args.model:
        models = [args.model]
    elif args.all:
        models = list(MODEL_FILES.keys())
    else:
        # Upload whatever is downloaded
        models = [name for name, fname in MODEL_FILES.items()
                  if (MODELS_DIR / fname).exists()]

    if not models:
        print("No models found to upload. Download first with:")
        print("  python scripts/setup_models.py --model trio-small")
        sys.exit(1)

    print(f"\n  trio.ai Model Upload")
    print(f"  --------------------")
    print(f"  Models to upload: {', '.join(models)}")
    print()

    success = 0
    for name in models:
        try:
            if upload_model(name, args.token):
                success += 1
        except Exception as e:
            print(f"  FAILED {name}: {e}")

    print(f"\n  Done! Uploaded {success}/{len(models)} models.")

    if success > 0:
        print(f"\n  Next: update setup_models.py URLs to point to your HuggingFace repos.")


if __name__ == "__main__":
    main()
