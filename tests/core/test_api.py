from pathlib import Path

from fastapi.testclient import TestClient

from agent_web.codex.base import Capabilities
from agent_web.config import Settings
from agent_web.main import create_app


class FakeCodex:
    capabilities = Capabilities(streaming=False, interrupt=True)

    async def health(self):
        return True, "ready"

    async def models(self):
        return [{"id": "test-model", "name": "Test model", "default": True,
                 "reasoning_efforts": ["low", "high"], "default_reasoning": "low"}]

    async def start_thread(self, cwd: Path, *, model, sandbox, reasoning=None):
        return "fixture-thread"

    async def list_threads(self, limit=100):
        return []

    async def run_turn(self, native_thread_id, prompt, *, sandbox):
        return f"answered: {prompt}"

    async def interrupt(self, native_thread_id):
        return True


def test_project_session_and_turn_lifecycle(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)), backend=FakeCodex())
    with TestClient(app) as client:
        created = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)})
        assert created.status_code == 201
        project_id = created.json()["id"]
        session = client.post(f"/api/v1/projects/{project_id}/sessions")
        assert session.status_code == 201
        turn = client.post(
            f"/api/v1/sessions/{session.json()['id']}/turns",
            json={"prompt": "hello", "client_request_id": "request-0001"},
        )
        assert turn.json()["response"] == "answered: hello"


def test_project_outside_allowed_root_is_rejected(tmp_path: Path):
    allowed = tmp_path / "allowed"
    rejected = tmp_path / "outside"
    (rejected / ".git").mkdir(parents=True)
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(allowed,)), backend=FakeCodex())
    with TestClient(app) as client:
        response = client.post("/api/v1/projects", json={"name": "No", "path": str(rejected)})
    assert response.status_code == 422


def test_update_endpoint_reports_not_configured(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path / "data"), backend=FakeCodex())
    with TestClient(app) as client:
        response = client.get("/api/v1/update")
    assert response.json() == {"state": "not_configured"}


def test_project_agent_settings_and_codex_status(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)), backend=FakeCodex())
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        saved = client.put(
            f"/api/v1/projects/{project['id']}/agent-settings",
            json={"model": "test-model", "reasoning": "high"},
        )
        status = client.get("/api/v1/codex/status")
    assert saved.json()["reasoning"] == "high"
    assert status.json()["models"][0]["id"] == "test-model"
    assert status.json()["usage"]["available"] is False
