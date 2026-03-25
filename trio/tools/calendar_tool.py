"""Calendar tool — manage events with local JSONL storage."""

import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from trio.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


def _get_calendar_path() -> Path:
    p = Path.home() / ".trio" / "calendar.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class CalendarTool(BaseTool):
    """Manage calendar events: create, list, update, delete."""

    @property
    def name(self) -> str:
        return "calendar"

    @property
    def description(self) -> str:
        return (
            "Manage calendar events. Actions: create (new event), list (upcoming events), "
            "update (modify event), delete (remove event)."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "update", "delete"],
                    "description": "Calendar action",
                },
                "title": {"type": "string", "description": "Event title"},
                "start_time": {"type": "string", "description": "Start time (ISO format or natural language)"},
                "end_time": {"type": "string", "description": "End time (ISO format)"},
                "description": {"type": "string", "description": "Event description"},
                "event_id": {"type": "string", "description": "Event ID (for update/delete)"},
                "days_ahead": {"type": "integer", "description": "Days to look ahead (for list)", "default": 7},
            },
            "required": ["action"],
        }

    def _load_events(self) -> list[dict]:
        path = _get_calendar_path()
        if not path.exists():
            return []
        events = []
        for line in path.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events

    def _save_events(self, events: list[dict]) -> None:
        path = _get_calendar_path()
        with open(path, "w", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        action = params.get("action", "")

        try:
            if action == "create":
                title = params.get("title", "Untitled")
                event = {
                    "id": str(uuid.uuid4())[:8],
                    "title": title,
                    "start_time": params.get("start_time", ""),
                    "end_time": params.get("end_time", ""),
                    "description": params.get("description", ""),
                    "created": datetime.now().isoformat(),
                }
                events = self._load_events()
                events.append(event)
                self._save_events(events)
                return ToolResult(
                    output=f"Event created: {title} (ID: {event['id']})",
                    metadata={"event_id": event["id"]},
                )

            elif action == "list":
                events = self._load_events()
                if not events:
                    return ToolResult(output="No events scheduled.")
                lines = []
                for ev in events[-20:]:
                    lines.append(
                        f"[{ev['id']}] {ev['title']}\n"
                        f"    Start: {ev.get('start_time', '?')} | End: {ev.get('end_time', '?')}\n"
                        f"    {ev.get('description', '')}"
                    )
                return ToolResult(output="\n\n".join(lines))

            elif action == "update":
                eid = params.get("event_id", "")
                if not eid:
                    return ToolResult(output="Error: event_id required", success=False)
                events = self._load_events()
                for ev in events:
                    if ev["id"] == eid:
                        if params.get("title"):
                            ev["title"] = params["title"]
                        if params.get("start_time"):
                            ev["start_time"] = params["start_time"]
                        if params.get("end_time"):
                            ev["end_time"] = params["end_time"]
                        if params.get("description"):
                            ev["description"] = params["description"]
                        self._save_events(events)
                        return ToolResult(output=f"Event {eid} updated.")
                return ToolResult(output=f"Event {eid} not found.", success=False)

            elif action == "delete":
                eid = params.get("event_id", "")
                if not eid:
                    return ToolResult(output="Error: event_id required", success=False)
                events = self._load_events()
                before = len(events)
                events = [e for e in events if e["id"] != eid]
                if len(events) == before:
                    return ToolResult(output=f"Event {eid} not found.", success=False)
                self._save_events(events)
                return ToolResult(output=f"Event {eid} deleted.")

            else:
                return ToolResult(output=f"Unknown action: {action}", success=False)

        except Exception as e:
            return ToolResult(output=f"Calendar error: {e}", success=False)
