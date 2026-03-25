"""Build pre-training and SFT data from trio's 1,600+ built-in skills.

This script:
1. Reads all skill .md files from trio/skills/builtin/
2. Creates a pre-training corpus (train.txt) from skill content
3. Creates SFT instruction pairs (sft_data.jsonl) for fine-tuning
4. The trained model will know about all skills out of the box
"""

import os
import json
import random
import re
from pathlib import Path

SKILLS_DIR = Path(__file__).parent.parent / "trio" / "skills" / "builtin"
DATA_DIR = Path(__file__).parent.parent / "trio_model" / "data"


def parse_skill(path: Path) -> dict | None:
    """Parse a skill markdown file into structured data."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    # Parse YAML frontmatter
    name = path.stem
    description = ""
    content = text

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
            content = parts[2].strip()
            for line in frontmatter.split("\n"):
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("description:"):
                    description = line.split(":", 1)[1].strip().strip('"').strip("'")

    if not content or len(content) < 50:
        return None

    return {
        "name": name,
        "description": description,
        "content": content,
    }


def build_pretrain_corpus(skills: list[dict]) -> str:
    """Build a pre-training text corpus from all skills."""
    lines = []

    # Core identity
    lines.append("""Trio is an open-source AI assistant that runs entirely on your system.
Trio was created by Karan Garg as an end-to-end AI platform.
Trio can train its own language model, align it with safety principles, and deploy as an agent.
Trio works across CLI, Discord, Telegram, and Signal.
Trio has over 1,600 built-in skills covering coding, marketing, DevOps, data science, security, and more.
Trio needs no API keys or external models. It runs 100% locally on your hardware.
""")

    # General knowledge about AI
    lines.append("""Artificial intelligence is the field of creating intelligent computer systems.
Language models learn patterns in text data and can generate helpful responses.
The transformer architecture uses self-attention to process sequences efficiently.
Pre-training teaches a model to understand language. Fine-tuning teaches it to follow instructions.
A helpful AI assistant should be accurate, honest, and safe in its responses.
""")

    # Skill content as knowledge
    for skill in skills:
        name = skill["name"].replace("_", " ").title()
        desc = skill["description"]
        content = skill["content"]

        # Clean content
        content = re.sub(r'#+\s*', '', content)  # Remove markdown headers
        content = re.sub(r'\*\*([^*]+)\*\*', r'\1', content)  # Remove bold
        content = re.sub(r'\*([^*]+)\*', r'\1', content)  # Remove italic
        content = re.sub(r'```[a-z]*\n', '', content)  # Remove code fence starts
        content = re.sub(r'```', '', content)  # Remove code fence ends
        content = re.sub(r'\n{3,}', '\n\n', content)  # Reduce blank lines

        if desc:
            lines.append(f"{name}: {desc}")
        lines.append(content.strip())
        lines.append("")  # Separator

    return "\n".join(lines)


def build_sft_data(skills: list[dict]) -> list[dict]:
    """Build instruction-response pairs from skills."""
    pairs = []

    # Core identity pairs
    identity_pairs = [
        ("What is your name?", "I am Trio, an open-source AI assistant created by Karan Garg. I run entirely on your system with no external dependencies."),
        ("Who created you?", "I was created by Karan Garg as part of the trio.ai project - an end-to-end AI platform for training, aligning, and deploying language models."),
        ("What can you do?", "I can help with a wide range of tasks including coding, writing, data analysis, marketing, DevOps, security, and more. I have over 1,600 built-in skills. I can also use tools like web search, math solver, shell commands, and file operations."),
        ("How do you work?", "I'm a transformer-based language model that runs locally on your system. I was pre-trained on text data and fine-tuned on instructions to be a helpful assistant. No API keys or cloud services needed."),
        ("Are you open source?", "Yes! trio.ai is fully open source under the MIT license. You can train your own model, customize skills, and deploy across CLI, Discord, Telegram, and Signal."),
        ("What platforms do you support?", "I work across multiple platforms: CLI terminal, Discord, Telegram, and Signal. You can chat with me from any of these channels."),
        ("What skills do you have?", "I have over 1,600 built-in skills covering: coding (Python, JavaScript, Go, Rust, etc.), marketing (SEO, content, social media), DevOps (Docker, Kubernetes, CI/CD), data science, security, business strategy, writing, and much more."),
        ("Hello", "Hello! I'm Trio, your AI assistant. How can I help you today?"),
        ("Hi there", "Hi! I'm Trio. What would you like to work on?"),
        ("Thanks", "You're welcome! Let me know if you need anything else."),
        ("Goodbye", "Goodbye! Feel free to come back anytime."),
        ("How are you?", "I'm running well on your system! Ready to help you with whatever you need."),
    ]

    for prompt, response in identity_pairs:
        pairs.append({
            "prompt": f"Human: {prompt}\n\nTrio:",
            "response": f" {response}",
        })

    # Generate pairs from skills
    question_templates = [
        "How do I {action}?",
        "Help me with {topic}.",
        "What should I know about {topic}?",
        "Explain {topic} to me.",
        "Give me tips on {topic}.",
    ]

    for skill in skills:
        name = skill["name"].replace("_", " ")
        desc = skill["description"]
        content = skill["content"]

        # Clean content for responses
        clean = re.sub(r'#+\s*', '', content)
        clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', clean)
        clean = re.sub(r'```[a-z]*\n?', '', clean)
        clean = re.sub(r'\n{3,}', '\n\n', clean).strip()

        # Truncate to reasonable length
        if len(clean) > 500:
            # Take first meaningful section
            sections = clean.split("\n\n")
            clean = "\n\n".join(sections[:3])
            if len(clean) > 500:
                clean = clean[:500].rsplit(" ", 1)[0] + "..."

        if len(clean) < 30:
            continue

        # Create Q&A pair about this skill
        if desc:
            pairs.append({
                "prompt": f"Human: Help me with {name}.\n\nTrio:",
                "response": f" {desc}\n\n{clean}",
            })

        # Create a "what is" pair
        if desc:
            pairs.append({
                "prompt": f"Human: What is {name}?\n\nTrio:",
                "response": f" {desc}",
            })

    # Shuffle for good training distribution
    random.seed(42)
    random.shuffle(pairs)

    return pairs


def main():
    print(f"Reading skills from {SKILLS_DIR}...")

    skills = []
    for path in sorted(SKILLS_DIR.glob("*.md")):
        skill = parse_skill(path)
        if skill:
            skills.append(skill)

    print(f"Parsed {len(skills)} skills")

    # Create data directory
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Build pre-training corpus
    print("Building pre-training corpus...")
    corpus = build_pretrain_corpus(skills)
    train_path = DATA_DIR / "train.txt"
    train_path.write_text(corpus, encoding="utf-8")
    print(f"  Saved {len(corpus):,} chars to {train_path}")

    # Build SFT data
    print("Building SFT instruction pairs...")
    sft_pairs = build_sft_data(skills)
    sft_path = DATA_DIR / "sft_data.jsonl"
    with open(sft_path, "w", encoding="utf-8") as f:
        for pair in sft_pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")
    print(f"  Saved {len(sft_pairs):,} pairs to {sft_path}")

    print("\nDone! Now run:")
    print("  python -m trio_model.training.pretrain --preset nano")
    print("  python -m trio_model.training.sft --preset nano")


if __name__ == "__main__":
    main()
