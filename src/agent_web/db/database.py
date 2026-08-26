from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from agent_web.db.models import Base


def create_database(url: str) -> tuple[AsyncEngine, async_sessionmaker]:
    engine = create_async_engine(url)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def migrate_database(data_dir: Path, database_url: str) -> Path | None:
    """Back up SQLite before Alembic upgrade; failure leaves recovery manual."""
    database = data_dir / "agent-web.sqlite3"
    backup = None
    if database.exists():
        backup_dir = data_dir / "backups"
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir / f"agent-web-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.sqlite3"
        shutil.copy2(database, backup)
    config = Config(str(Path(__file__).parents[3] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("sqlite+aiosqlite", "sqlite"))
    command.upgrade(config, "head")
    return backup
