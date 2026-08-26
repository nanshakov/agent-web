from pathlib import Path

from agent_web.config import Settings
from agent_web.db.database import create_database, migrate_database
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
