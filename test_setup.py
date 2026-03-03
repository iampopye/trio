"""
Trio AI — Quick Test Script
Run this first to verify your environment and the model architecture.
No GPU or large dataset needed — just validates everything imports and runs.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import torch
from config import get_config, NanoConfig
from model.architecture import TrioModel
from data.tokenizer import get_tokenizer, CharTokenizer


def test_tokenizer():
    print("\n── Tokenizer Test ─────────────────────────────────")
    tok = CharTokenizer()
    text = "Hello, I am Trio!"
    ids  = tok.encode(text)
    dec  = tok.decode(ids)
    print(f"  Input:   {text}")
    print(f"  Encoded: {ids}")
    print(f"  Decoded: {dec}")
    print(f"  Vocab size: {tok.vocab_size}")
    assert len(ids) > 0, "Encoding failed"
    print("  ✅ Tokenizer OK")


def test_model_forward():
    print("\n── Model Forward Pass Test ────────────────────────")
    cfg = NanoConfig()
    tok = CharTokenizer()
    cfg.vocab_size = tok.vocab_size

    model = TrioModel(cfg)
    params = model.num_parameters()
    print(f"  Model: {cfg.model_name}")
    print(f"  Parameters: {params / 1e6:.3f}M")

    # Dummy batch
    B, T   = 2, cfg.context_length
    x = torch.randint(0, cfg.vocab_size, (B, T))
    y = torch.randint(0, cfg.vocab_size, (B, T))

    logits, loss = model(x, y)
    print(f"  Input shape:  {x.shape}")
    print(f"  Output shape: {logits.shape}")
    print(f"  Loss:         {loss.item():.4f}")
    assert logits.shape == (B, T, cfg.vocab_size), "Logits shape mismatch"
    assert loss.item() > 0, "Loss should be positive"
    print("  ✅ Forward pass OK")


def test_generation():
    print("\n── Generation Test ────────────────────────────────")
    cfg = NanoConfig()
    tok = CharTokenizer()
    cfg.vocab_size = tok.vocab_size

    model = TrioModel(cfg)

    prompt    = "Hello, I am"
    input_ids = torch.tensor([tok.encode(prompt)], dtype=torch.long)
    output    = model.generate(input_ids, max_new_tokens=20, temperature=1.0)
    text      = tok.decode(output[0].tolist())
    print(f"  Prompt:   {prompt}")
    print(f"  Output:   {text}")
    print("  ✅ Generation OK")


def test_config():
    print("\n── Config Test ────────────────────────────────────")
    for preset in ["nano", "small", "medium"]:
        cfg = get_config(preset)
        params = cfg.num_parameters()
        print(f"  {preset:8s} → {params/1e6:.1f}M params | ctx={cfg.context_length} | d_model={cfg.d_model}")
    print("  ✅ Configs OK")


if __name__ == "__main__":
    print("=" * 55)
    print("  Trio AI — Environment & Architecture Test")
    print("=" * 55)

    try:
        test_config()
        test_tokenizer()
        test_model_forward()
        test_generation()
        print("\n" + "=" * 55)
        print("  ✅ ALL TESTS PASSED — Trio is ready to train!")
        print("=" * 55)
        print("\nNext step: python training/pretrain.py --preset nano")
    except Exception as e:
        import traceback
        print(f"\n❌ TEST FAILED: {e}")
        traceback.print_exc()
