from __future__ import annotations

from dataclasses import dataclass
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

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.data_dir / 'agent-web.sqlite3'}"

