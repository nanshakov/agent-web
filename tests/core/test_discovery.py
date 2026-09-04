import asyncio
from pathlib import Path

import pytest

from agent_web.config import Settings
from agent_web.db.database import create_database, migrate_database
from agent_web.main import periodically_import
from agent_web.service import AgentService


class DiscoveringBackend:
    async def list_threads(self, limit=100):
        return [{"id": "native-1", "cwd": str(self.cwd), "title": "Existing Codex chat"}]


async def test_existing_threads_are_imported_only_inside_roots(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    backend = DiscoveringBackend()
    backend.cwd = repo
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}"
    migrate_database(tmp_path, database_url)
    engine, factory = create_database(database_url)
    service = AgentService(factory, backend, (tmp_path,))
    assert await service.import_existing_codex_sessions() == 1
    assert await service.import_existing_codex_sessions() == 0
    assert len(await service.list_projects()) == 1
    await engine.dispose()


async def test_periodic_import_repeats_after_the_configured_interval():
    calls = 0
    waits = 0

    async def discover() -> None:
        nonlocal calls
        calls += 1

    async def stop_after_second_wait(interval: float) -> None:
        nonlocal waits
        assert interval == 300
        waits += 1
        if waits == 2:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await periodically_import(discover, interval=300, sleep=stop_after_second_wait)

    assert calls == 2
