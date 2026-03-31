"""
Trio AI — Inference Server
FastAPI-based chat server that loads a trained Trio checkpoint
and serves it through a REST API + interactive CLI.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import os
import argparse
import json
from typing import List, Optional

import torch

from trio_model.config import get_config
from trio_model.model.architecture import TrioModel
from trio_model.data.tokenizer import get_tokenizer


# ── Generation Engine ──────────────────────────────────────────────────────────

class TrioEngine:
    """Loads Trio and handles text generation."""

    def __init__(self, checkpoint_path: str, preset: str = "nano"):
        self.device = torch.device(get_config(preset).device)

        print(f"[Trio Engine] Loading model from: {checkpoint_path}")

        if os.path.exists(checkpoint_path):
            ckpt = torch.load(checkpoint_path, map_location=self.device, weights_only=False)
            saved_cfg = ckpt.get("config", {})
            saved_vocab = saved_cfg.get("vocab_size", 0)

            # Auto-detect tokenizer from checkpoint vocab size
            # BPE models (Kaggle-trained) have vocab_size ~50257
            # CharTokenizer models have vocab_size ~105
            if saved_vocab > 1000:
                self.tokenizer = get_tokenizer("small")  # BPE tokenizer
                self.cfg = get_config(preset)
                # Override config with saved values from checkpoint
                for k, v in saved_cfg.items():
                    if hasattr(self.cfg, k):
                        setattr(self.cfg, k, v)
                print(f"[Trio Engine] Detected BPE model (vocab={saved_vocab})")
            else:
                self.cfg = get_config(preset)
                self.tokenizer = get_tokenizer(preset)
                self.cfg.vocab_size = self.tokenizer.vocab_size

            self.model = TrioModel(self.cfg).to(self.device)
            self.model.load_state_dict(ckpt["model"])
            step = ckpt.get("step", "?")
            val_loss = ckpt.get("val_loss", "?")
            print(f"[Trio Engine] Loaded! Step={step}, val_loss={val_loss}")
        else:
            self.cfg = get_config(preset)
            self.tokenizer = get_tokenizer(preset)
            self.cfg.vocab_size = self.tokenizer.vocab_size
            self.model = TrioModel(self.cfg).to(self.device)
            print(f"[Trio Engine] Checkpoint not found at {checkpoint_path}")
            print("[Trio Engine] Using random weights (for testing only)")

        self.model.eval()

    def chat(
        self,
        messages: List[dict],
        max_new_tokens: int = 300,
        temperature: float = 0.7,
        top_k: int = 50,
        top_p: float = 0.95,
    ) -> str:
        """
        Generate a response for a conversation.
        messages: [{"role": "human"/"trio", "content": "..."}]
        """
        # Build prompt from conversation history
        prompt = self._format_chat(messages)
        ids    = self.tokenizer.encode(prompt)
        ids    = ids[-self.cfg.context_length + max_new_tokens:]   # leave room for response
        input_ids = torch.tensor([ids], dtype=torch.long).to(self.device)

        with torch.no_grad():
            output_ids = self.model.generate(
                input_ids,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_k=top_k,
                top_p=top_p,
                eos_token_id=self.tokenizer.eos_token_id,
            )

        new_tokens = output_ids[0, len(ids):].tolist()
        response   = self.tokenizer.decode(new_tokens).strip()

        # Clean up response (stop at next human turn)
        for stop in ["Human:", "<|human|>", "\n\n\n"]:
            if stop in response:
                response = response[:response.index(stop)].strip()

        return response

    def _format_chat(self, messages: List[dict]) -> str:
        """Format conversation history into a prompt string."""
        lines = []
        for msg in messages:
            role    = msg.get("role", "human")
            content = msg.get("content", "").strip()
            if role == "system":
                lines.append(f"System: {content}")
            elif role == "human":
                lines.append(f"Human: {content}")
            elif role == "trio":
                lines.append(f"Trio: {content}")
        lines.append("Trio:")  # model should complete this
        return "\n\n".join(lines)

    def complete(self, text: str, max_new_tokens: int = 200, temperature: float = 0.8) -> str:
        """Raw text completion (no chat formatting)."""
        ids = self.tokenizer.encode(text)
        ids = ids[-self.cfg.context_length:]
        input_ids = torch.tensor([ids], dtype=torch.long).to(self.device)
        with torch.no_grad():
            out = self.model.generate(input_ids, max_new_tokens=max_new_tokens,
                                      temperature=temperature, top_k=50)
        new_tokens = out[0, len(ids):].tolist()
        return self.tokenizer.decode(new_tokens)


# ── FastAPI Server ─────────────────────────────────────────────────────────────

def create_app(engine: TrioEngine):
    try:
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        from pydantic import BaseModel
    except ImportError:
        print("Run: pip install fastapi uvicorn pydantic")
        return None

    app = FastAPI(
        title="Trio AI API",
        description="Trio — A custom language model built from scratch",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    class Message(BaseModel):
        role: str       # "human" | "trio" | "system"
        content: str

    class ChatRequest(BaseModel):
        messages: List[Message]
        max_new_tokens: int = 300
        temperature: float = 0.7
        top_k: int = 50
        top_p: float = 0.95

    class ChatResponse(BaseModel):
        response: str
        model: str = "trio"

    class CompletionRequest(BaseModel):
        prompt: str
        max_new_tokens: int = 200
        temperature: float = 0.8

    @app.get("/")
    def root():
        return {
            "name": "Trio AI",
            "version": "0.1.0",
            "status": "ready",
            "params": f"{engine.model.num_parameters()/1e6:.1f}M",
        }

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/v1/chat", response_model=ChatResponse)
    def chat(req: ChatRequest):
        msgs = [m.dict() for m in req.messages]
        response = engine.chat(
            msgs,
            max_new_tokens=req.max_new_tokens,
            temperature=req.temperature,
            top_k=req.top_k,
            top_p=req.top_p,
        )
        return ChatResponse(response=response)

    @app.post("/v1/complete")
    def complete(req: CompletionRequest):
        result = engine.complete(req.prompt, req.max_new_tokens, req.temperature)
        return {"completion": result}

    return app


# ── Interactive CLI Chat ───────────────────────────────────────────────────────

def cli_chat(engine: TrioEngine):
    print("\n" + "="*60)
    print("  Welcome to Trio AI  |  Type 'exit' to quit")
    print("  Type 'clear' to start a new conversation")
    print("="*60 + "\n")

    history = []
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() == "exit":
            print("Goodbye!")
            break
        if user_input.lower() == "clear":
            history = []
            print("\n[Conversation cleared]\n")
            continue

        history.append({"role": "human", "content": user_input})
        response = engine.chat(history)

        if not response:
            response = "I'm still learning. Please ask me again!"

        print(f"\nTrio: {response}\n")
        history.append({"role": "trio", "content": response})


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trio AI Inference Server")
    parser.add_argument("--preset",     type=str, default="nano")
    parser.add_argument("--checkpoint", type=str, default=None)
    parser.add_argument("--mode",       type=str, default="cli",
                        choices=["cli", "api"],
                        help="'cli' for interactive chat, 'api' for REST server")
    parser.add_argument("--host",       type=str, default="0.0.0.0")
    parser.add_argument("--port",       type=int, default=8080)
    args = parser.parse_args()

    cfg = get_config(args.preset)

    # Find checkpoint
    ckpt_path = args.checkpoint
    if not ckpt_path:
        # Look in SFT dir first, then pretrain
        for candidate in [
            os.path.join(cfg.checkpoint_dir, "sft", "trio_latest.pt"),
            os.path.join(cfg.checkpoint_dir, "trio_latest.pt"),
        ]:
            if os.path.exists(candidate):
                ckpt_path = candidate
                break
    if not ckpt_path:
        ckpt_path = os.path.join(cfg.checkpoint_dir, "trio_latest.pt")

    engine = TrioEngine(ckpt_path, preset=args.preset)

    if args.mode == "cli":
        cli_chat(engine)
    else:
        try:
            import uvicorn
            app = create_app(engine)
            if app:
                print(f"\n[Trio API] Starting server at http://{args.host}:{args.port}")
                print(f"[Trio API] API docs at http://localhost:{args.port}/docs\n")
                uvicorn.run(app, host=args.host, port=args.port)
        except ImportError:
            print("Run: pip install uvicorn fastapi")
