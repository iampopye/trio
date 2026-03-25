"""Import OpenClaw skills into trio format."""

import os
import re
from pathlib import Path

TRIO_SKILLS = Path("trio/skills/builtin")
existing = {f.stem.lower().replace("-", "_").replace(" ", "_") for f in TRIO_SKILLS.glob("*.md")}
print(f"Existing trio skills: {len(existing)}")


def normalize(name):
    safe = re.sub(r"[^a-z0-9_]", "_", name.lower().replace("-", "_").replace(" ", "_"))
    safe = re.sub(r"_+", "_", safe).strip("_")
    return safe[:100] or "unnamed"


def convert_skill(skill_md_path, source_name):
    """Convert OpenClaw SKILL.md to trio format."""
    content = skill_md_path.read_text(encoding="utf-8", errors="ignore")

    # Extract YAML frontmatter
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not fm_match:
        return None, None

    fm_text = fm_match.group(1)
    body = content[fm_match.end() :]

    # Extract name
    name_match = re.search(r"^name:\s*(.+)$", fm_text, re.MULTILINE)
    name = name_match.group(1).strip().strip('"').strip("'") if name_match else source_name

    # Extract description
    desc = f"{name} skill"
    desc_match = re.search(r'^description:\s*"(.*?)"', fm_text, re.MULTILINE)
    if not desc_match:
        desc_match = re.search(r"^description:\s*'(.*?)'", fm_text, re.MULTILINE)
    if not desc_match:
        desc_match = re.search(r"^description:\s*(.+)$", fm_text, re.MULTILINE)
    if desc_match:
        desc = desc_match.group(1).strip().strip('"').strip("'")

    # Truncate very long descriptions
    if len(desc) > 200:
        desc = desc[:197] + "..."

    # Build trio-format skill
    trio_skill = f"---\nname: {name}\ndescription: {desc}\nalwaysLoad: false\n---\n\n{body.strip()}\n"
    return name, trio_skill


# Process OpenClaw skills from cloned repos
imported = 0
skipped = 0
import tempfile
tmp = Path(tempfile.gettempdir())
sources = [
    tmp / "openclaw" / "skills",
    tmp / "openclaw-master-skills" / "skills",
]

for src_dir in sources:
    if not src_dir.exists():
        print(f"Source not found: {src_dir}")
        continue
    print(f"\nProcessing: {src_dir}")
    for skill_dir in sorted(src_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue

        norm = normalize(skill_dir.name)
        if norm in existing:
            skipped += 1
            continue

        name, converted = convert_skill(skill_md, skill_dir.name)
        if converted is None:
            skipped += 1
            continue

        # Save to trio
        filename = normalize(name) + ".md"
        dest = TRIO_SKILLS / filename
        if dest.exists():
            skipped += 1
            continue

        dest.write_text(converted, encoding="utf-8")
        existing.add(norm)
        imported += 1

print(f"\nImported: {imported}")
print(f"Skipped (duplicates/invalid): {skipped}")
print(f"Total trio skills now: {len(list(TRIO_SKILLS.glob('*.md')))}")
