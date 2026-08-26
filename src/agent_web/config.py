from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from platformdirs import user_data_path


def default_data_dir() -> Path:
    return user_data_path("agent-web", "Agent Web")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    allowed_roots: tuple[Path, ...] = ()
    host: str = "127.0.0.1"
    port: int = 8765
    update_repository_url: str | None = None
    update_branch: str = "main"

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.data_dir / 'agent-web.sqlite3'}"


def config_file(data_dir: Path) -> Path:
    return data_dir / "config.json"


def read_config(data_dir: Path) -> dict:
    path = config_file(data_dir)
    return json.loads(path.read_text("utf-8")) if path.exists() else {"roots": []}


def write_config(data_dir: Path, payload: dict) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    config_file(data_dir).write_text(json.dumps(payload, indent=2) + "\n", "utf-8")
