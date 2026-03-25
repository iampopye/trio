"""Notes tool — create and manage markdown notes."""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from trio.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


def _get_notes_dir() -> Path:
    p = Path.home() / ".trio" / "notes"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _sanitize_filename(title: str) -> str:
    safe = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')
    return safe[:100] or "untitled"


class NotesTool(BaseTool):
    """Create, read, search, and manage notes stored as markdown files."""

    @property
    def name(self) -> str:
        return "notes"

    @property
    def description(self) -> str:
        return (
            "Manage notes stored in ~/.trio/notes/ as markdown files. "
            "Actions: create, read, list, search, append, delete."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "read", "list", "search", "append", "delete"],
                    "description": "Note action to perform",
                },
                "title": {"type": "string", "description": "Note title (used as filename)"},
                "content": {"type": "string", "description": "Note content (markdown)"},
                "query": {"type": "string", "description": "Search query (for search action)"},
            },
            "required": ["action"],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        action = params.get("action", "")
        notes_dir = _get_notes_dir()

        try:
            if action == "create":
                title = params.get("title", "")
                content = params.get("content", "")
                if not title:
                    return ToolResult(output="Error: title required", success=False)
                filename = _sanitize_filename(title) + ".md"
                path = notes_dir / filename
                header = f"# {title}\n\n_Created: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n\n"
                path.write_text(header + content, encoding="utf-8")
                return ToolResult(output=f"Note created: {filename}")

            elif action == "read":
                title = params.get("title", "")
                if not title:
                    return ToolResult(output="Error: title required", success=False)
                filename = _sanitize_filename(title) + ".md"
                path = notes_dir / filename
                if not path.exists():
                    # Try fuzzy match
                    matches = [f for f in notes_dir.glob("*.md") if title.lower() in f.stem.lower()]
                    if matches:
                        path = matches[0]
                    else:
                        return ToolResult(output=f"Note not found: {title}", success=False)
                content = path.read_text(encoding="utf-8")
                if len(content) > 4000:
                    content = content[:4000] + "\n... (truncated)"
                return ToolResult(output=content)

            elif action == "list":
                files = sorted(notes_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
                if not files:
                    return ToolResult(output="No notes found.")
                lines = []
                for f in files[:50]:
                    size = f.stat().st_size
                    mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                    lines.append(f"  {f.stem}  ({size}B, {mtime})")
                return ToolResult(output=f"Notes ({len(files)}):\n" + "\n".join(lines))

            elif action == "search":
                query = params.get("query", "").lower()
                if not query:
                    return ToolResult(output="Error: query required", success=False)
                matches = []
                for f in notes_dir.glob("*.md"):
                    content = f.read_text(encoding="utf-8").lower()
                    if query in content or query in f.stem.lower():
                        # Find matching line
                        for line in f.read_text(encoding="utf-8").split("\n"):
                            if query in line.lower():
                                matches.append(f"  {f.stem}: {line.strip()[:100]}")
                                break
                        else:
                            matches.append(f"  {f.stem}: (title match)")
                if not matches:
                    return ToolResult(output=f"No notes matching: {query}")
                return ToolResult(output=f"Found {len(matches)} match(es):\n" + "\n".join(matches[:20]))

            elif action == "append":
                title = params.get("title", "")
                content = params.get("content", "")
                if not title:
                    return ToolResult(output="Error: title required", success=False)
                filename = _sanitize_filename(title) + ".md"
                path = notes_dir / filename
                if not path.exists():
                    return ToolResult(output=f"Note not found: {title}", success=False)
                with open(path, "a", encoding="utf-8") as f:
                    f.write("\n" + content)
                return ToolResult(output=f"Appended to: {filename}")

            elif action == "delete":
                title = params.get("title", "")
                if not title:
                    return ToolResult(output="Error: title required", success=False)
                filename = _sanitize_filename(title) + ".md"
                path = notes_dir / filename
                if not path.exists():
                    return ToolResult(output=f"Note not found: {title}", success=False)
                path.unlink()
                return ToolResult(output=f"Note deleted: {filename}")

            else:
                return ToolResult(output=f"Unknown action: {action}", success=False)

        except Exception as e:
            return ToolResult(output=f"Notes error: {e}", success=False)
