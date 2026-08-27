from __future__ import annotations

import json
import os
import sys
from pathlib import Path


class ClineHistory:
    """Read-only adapter for Cline's on-disk task archive."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        self.storage_dir = storage_dir or self.default_storage_dir()

    @staticmethod
    def default_storage_dir() -> Path:
        if sys.platform == "darwin":
            return Path.home() / "Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev"
        app_data = os.environ.get("APPDATA")
        return Path(app_data or Path.home() / "AppData/Roaming") / "Code/User/globalStorage/saoudrizwan.claude-dev"

    def available(self) -> bool:
        return self.storage_dir.is_dir()

    def tasks(self) -> list[dict[str, str]]:
        history_file = self.storage_dir / "state" / "taskHistory.json"
        try:
            entries = json.loads(history_file.read_text("utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        if not isinstance(entries, list):
            return []
        tasks = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            task_id, prompt, cwd = entry.get("id"), entry.get("task"), entry.get("cwdOnTaskInitialization")
            if isinstance(task_id, str) and isinstance(prompt, str) and isinstance(cwd, str):
                tasks.append({"id": task_id, "title": prompt, "cwd": cwd})
        return tasks

    def messages(self, task_id: str) -> list[dict[str, str]]:
        if Path(task_id).name != task_id:
            return []
        path = self.storage_dir / "tasks" / task_id / "ui_messages.json"
        try:
            entries = json.loads(path.read_text("utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        if not isinstance(entries, list):
            return []
        messages = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("text"), str):
                continue
            messages.append({"role": "user" if entry.get("ask") else "assistant", "content": entry["text"]})
        return messages
