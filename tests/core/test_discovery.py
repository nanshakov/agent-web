import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select

from agent_web.config import Settings
from agent_web.db.database import create_database, migrate_database
from agent_web.db.models import AgentSegment, AgentSession, Project
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


async def test_existing_agent_segment_does_not_block_other_codex_thread_imports(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}"
    migrate_database(tmp_path, database_url)
    engine, factory = create_database(database_url)
    backend = DiscoveringBackend()
    backend.cwd = repo
    backend.list_threads = lambda limit=100: _threads_with_existing_segment(repo)  # type: ignore[method-assign]
    async with factory() as db:
        project = Project(name="repo", path=str(repo))
        db.add(project)
        await db.flush()
        existing = AgentSession(project_id=project.id, native_thread_id="logical-chat")
        db.add(existing)
        await db.flush()
        db.add(AgentSegment(session_id=existing.id, native_thread_id="native-1", agent="codex"))
        await db.commit()
    service = AgentService(factory, backend, (tmp_path,))
    assert await service.import_existing_codex_sessions() == 1
    async with factory() as db:
        imported = await db.scalar(select(AgentSession).where(AgentSession.native_thread_id == "native-2"))
    assert imported is not None
    await engine.dispose()


async def _threads_with_existing_segment(repo: Path) -> list[dict[str, str]]:
    return [
        {"id": "native-1", "cwd": str(repo), "title": "Already segmented"},
        {"id": "native-2", "cwd": str(repo), "title": "Must import"},
    ]


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
