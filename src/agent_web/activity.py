"""Small, bounded activity snapshots; tool arguments and output stay private."""
from __future__ import annotations

from typing import TypedDict


class Activity(TypedDict):
    id: str
    kind: str
    label: str
    status: str


def item_activity(item, *, completed: bool) -> Activity | None:
    kind = getattr(item, "type", "")
    if kind == "commandExecution":
        label = "Command"
    elif kind == "fileChange":
        label = f"File changes · {len(item.changes)} files"
    elif kind == "mcpToolCall":
        label = f"MCP · {item.server} / {item.tool}"
    elif kind == "dynamicToolCall":
        label = f"Tool · {item.tool}"
    else:
        return None
    status = "running"
    if completed:
        raw = getattr(item.status, "value", item.status)
        failed = raw in ("failed", "declined") or getattr(item, "success", None) is False
        failed = failed or getattr(item, "exit_code", None) not in (None, 0)
        status = "failed" if failed else "completed"
    return {"id": item.id, "kind": kind, "label": label[:240], "status": status}


def update_activity(items: list[Activity], activity: Activity) -> list[Activity]:
    result = [item.copy() for item in items]
    for index, item in enumerate(result):
        if item["id"] == activity["id"]:
            result[index] = activity.copy()
            break
    else:
        result.append(activity.copy())
    # Bound every replay / persisted snapshot even on very long turns.
    return result[-100:]


def finish_activity(items: list[Activity]) -> list[Activity]:
    # A missing tool completion is not proof that the tool succeeded.
    result = [item.copy() for item in items]
    for item in result:
        if item["status"] == "running":
            item["status"] = "interrupted"
    return result
