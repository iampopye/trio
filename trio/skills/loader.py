"""Skills loader — reads markdown skill files and injects into agent context.

Skills are .md files with YAML frontmatter:
    ---
    name: github
    description: Interact with GitHub repositories
    alwaysLoad: false
    ---
    # GitHub Skill
    Instructions for using GitHub...

Two loading modes:
    - alwaysLoad: true  → Full content included in system prompt
    - alwaysLoad: false → Summary only, activated via LOAD_SKILL: skill_name
"""

import logging
import re
from pathlib import Path
from typing import Any

from trio.core.config import get_skills_dir

logger = logging.getLogger(__name__)


class Skill:
    """A loaded skill with metadata and content."""

    def __init__(self, name: str, description: str, content: str, always_load: bool = False):
        self.name = name
        self.description = description
        self.content = content
        self.always_load = always_load

    def to_summary(self) -> str:
        return f"- **{self.name}**: {self.description}"

    def to_full_prompt(self) -> str:
        return f"\n## Skill: {self.name}\n{self.content}"


class SkillsLoader:
    """Loads and manages skills from markdown files."""

    def __init__(self):
        self._skills: dict[str, Skill] = {}
        self._builtin_dir = Path(__file__).parent / "builtin"
        self._user_dir = get_skills_dir()

    def load_all(self) -> None:
        """Load skills from builtin/ and user's ~/.trio/skills/."""
        # Built-in skills
        if self._builtin_dir.is_dir():
            for path in self._builtin_dir.glob("*.md"):
                self._load_file(path)

        # User skills
        if self._user_dir.is_dir():
            for path in self._user_dir.glob("*.md"):
                self._load_file(path)

        logger.info(f"Loaded {len(self._skills)} skills: {', '.join(self._skills.keys())}")

    def _load_file(self, path: Path) -> None:
        """Parse a skill markdown file."""
        try:
            text = path.read_text(encoding="utf-8")
            meta, content = self._parse_frontmatter(text)

            name = meta.get("name", path.stem)
            description = meta.get("description", "")
            always_load = meta.get("alwaysLoad", False)

            self._skills[name] = Skill(
                name=name,
                description=description,
                content=content.strip(),
                always_load=always_load,
            )
        except Exception as e:
            logger.warning(f"Failed to load skill {path.name}: {e}")

    def _parse_frontmatter(self, text: str) -> tuple[dict, str]:
        """Parse YAML frontmatter from markdown."""
        match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)', text, re.DOTALL)
        if not match:
            return {}, text

        frontmatter = match.group(1)
        content = match.group(2)

        # Simple YAML parsing (key: value pairs)
        meta = {}
        for line in frontmatter.split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                if value.lower() in ("true", "yes"):
                    meta[key] = True
                elif value.lower() in ("false", "no"):
                    meta[key] = False
                else:
                    meta[key] = value

        return meta, content

    def get_always_load_prompts(self) -> list[str]:
        """Get full prompts for always-loaded skills."""
        return [s.to_full_prompt() for s in self._skills.values() if s.always_load]

    def get_skill_summaries(self) -> str:
        """Get a summary of all on-demand skills."""
        on_demand = [s for s in self._skills.values() if not s.always_load]
        if not on_demand:
            return ""
        lines = ["## Available Skills (use LOAD_SKILL: <name> to activate)"]
        for s in on_demand:
            lines.append(s.to_summary())
        return "\n".join(lines)

    def get_skill(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list_skills(self) -> list[str]:
        return list(self._skills.keys())
