"""
Trio AI — Constitutional AI (CAI) Self-Critique Loop
Implements Anthropic's CAI technique:
  1. Generate initial response
  2. Critique the response against Trio's constitution
  3. Revise the response
  4. Collect revised pairs as new SFT training data
"""

import os
import sys
import json
import argparse
from typing import List, Dict

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_config
from model.architecture import TrioModel
from data.tokenizer import get_tokenizer


# ── Trio's Constitution ────────────────────────────────────────────────────────
# These principles guide self-critique and revision

TRIO_CONSTITUTION = """
# Trio's Constitutional Principles

1. HELPFULNESS: Trio should provide accurate, complete, and useful responses.
   - Do not give vague or evasive answers when a clear answer is possible.
   - Provide concrete examples when explaining complex topics.

2. HONESTY: Trio should be truthful and transparent.
   - Acknowledge uncertainty rather than fabricating information.
   - Do not pretend to have capabilities it does not have.
   - Be clear about being an AI when asked.

3. HARMLESSNESS: Trio should avoid causing harm.
   - Do not assist with illegal activities.
   - Do not generate hateful, discriminatory, or violent content.
   - Do not help create malware, weapons, or dangerous materials.

4. FAIRNESS: Trio should treat all people equally.
   - Do not discriminate based on race, gender, religion, or other characteristics.
   - Present balanced perspectives on controversial topics.

5. PRIVACY: Trio should respect privacy.
   - Do not encourage sharing personal information unnecessarily.
   - Do not assist in unauthorized data collection.

6. SAFETY: Trio should prioritize user safety.
   - Recommend professional help for medical, legal, or mental health issues.
   - Include appropriate warnings for potentially dangerous activities.
"""


# ── CAI Prompts ────────────────────────────────────────────────────────────────

def build_critique_prompt(original_prompt: str, initial_response: str) -> str:
    return f"""Review the following AI response according to these principles:
{TRIO_CONSTITUTION}

Original question: {original_prompt}

Initial response: {initial_response}

Identify specific ways this response violates or could better follow the principles above.
Be specific and constructive in your critique.

Critique:"""


def build_revision_prompt(original_prompt: str, initial_response: str, critique: str) -> str:
    return f"""Revise the following response to address the critique provided.

Original question: {original_prompt}

Initial response: {initial_response}

Critique: {critique}

Write an improved response that addresses the issues raised in the critique
while remaining helpful and informative.

Revised response:"""


# ── CAI Loop ──────────────────────────────────────────────────────────────────

class ConstitutionalAI:
    def __init__(self, model: TrioModel, tokenizer, cfg, device: str = "cpu"):
        self.model     = model
        self.tokenizer = tokenizer
        self.cfg       = cfg
        self.device    = torch.device(device)

    def generate(self, prompt: str, max_new_tokens: int = 200, temperature: float = 0.8) -> str:
        """Generate text from a prompt."""
        self.model.eval()
        ids = self.tokenizer.encode(prompt)
        ids = ids[-self.cfg.context_length:]   # trim to context
        input_ids = torch.tensor([ids], dtype=torch.long).to(self.device)

        with torch.no_grad():
            output_ids = self.model.generate(
                input_ids,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_k=40,
                top_p=0.95,
                eos_token_id=self.tokenizer.eos_token_id,
            )

        # Decode only the new tokens
        new_tokens = output_ids[0, len(ids):].tolist()
        return self.tokenizer.decode(new_tokens).strip()

    def self_critique_revise(self, prompt: str) -> Dict[str, str]:
        """
        Full CAI loop for a single prompt:
        Generate → Critique → Revise
        Returns dict with all three.
        """
        print(f"\n[CAI] Processing: {prompt[:60]}...")

        # Step 1: Initial response
        initial = self.generate(prompt)
        print(f"  ✓ Initial response generated ({len(initial.split())} words)")

        # Step 2: Self-critique
        critique_prompt = build_critique_prompt(prompt, initial)
        critique = self.generate(critique_prompt, max_new_tokens=150, temperature=0.7)
        print(f"  ✓ Critique generated")

        # Step 3: Revision
        revision_prompt = build_revision_prompt(prompt, initial, critique)
        revised = self.generate(revision_prompt, max_new_tokens=250, temperature=0.7)
        print(f"  ✓ Revised response generated ({len(revised.split())} words)")

        return {
            "prompt":   prompt,
            "initial":  initial,
            "critique": critique,
            "revised":  revised,
        }

    def process_dataset(
        self,
        prompts: List[str],
        output_path: str,
        n_revisions: int = 1,
    ) -> List[Dict]:
        """
        Run CAI loop on a list of prompts.
        Saves revised pairs as SFT training data.
        """
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
        results = []

        with open(output_path, "w", encoding="utf-8") as f:
            for i, prompt in enumerate(prompts):
                print(f"\n[CAI] {i+1}/{len(prompts)}")
                try:
                    result = self.self_critique_revise(prompt)
                    results.append(result)

                    # Save as SFT format (using revised response)
                    sft_sample = {
                        "prompt":   f"Human: {prompt}\n\nTrio:",
                        "response": f" {result['revised']}",
                    }
                    f.write(json.dumps(sft_sample) + "\n")
                    f.flush()
                except Exception as e:
                    print(f"  ⚠ Error on prompt {i}: {e}")
                    continue

        print(f"\n✅ CAI complete. {len(results)} samples saved to {output_path}")
        return results


# ── Sample Prompts for CAI ─────────────────────────────────────────────────────

SAMPLE_PROMPTS = [
    "What is artificial intelligence?",
    "How does machine learning work?",
    "Can you explain neural networks simply?",
    "What are the ethical concerns with AI?",
    "How can AI help in healthcare?",
    "What is the difference between AI and human intelligence?",
    "How do language models like you work?",
    "What should I know before starting a career in AI?",
]


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Constitutional AI self-critique loop")
    parser.add_argument("--preset",     type=str, default="nano")
    parser.add_argument("--checkpoint", type=str, default=None)
    parser.add_argument("--prompts",    type=str, default=None,
                        help="Path to text file with one prompt per line")
    parser.add_argument("--output",     type=str, default="data/corpus/cai_sft_data.jsonl")
    args = parser.parse_args()

    cfg       = get_config(args.preset)
    tokenizer = get_tokenizer(args.preset)
    cfg.vocab_size = tokenizer.vocab_size

    model = TrioModel(cfg)

    ckpt_path = args.checkpoint or os.path.join(cfg.checkpoint_dir, "sft", "trio_latest.pt")
    if os.path.exists(ckpt_path):
        ckpt = torch.load(ckpt_path, map_location="cpu")
        model.load_state_dict(ckpt["model"])
        print(f"[CAI] Loaded model from {ckpt_path}")
    else:
        print("[CAI] Warning: No checkpoint found, using random init model")

    # Load custom prompts if provided
    if args.prompts and os.path.exists(args.prompts):
        with open(args.prompts) as f:
            prompts = [l.strip() for l in f if l.strip()]
    else:
        prompts = SAMPLE_PROMPTS
        print(f"[CAI] Using {len(prompts)} sample prompts")

    cai = ConstitutionalAI(model, tokenizer, cfg, device=cfg.device)
    cai.process_dataset(prompts, output_path=args.output)
