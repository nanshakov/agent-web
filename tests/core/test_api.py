import sqlite3
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agent_web.codex.base import Capabilities
from agent_web.config import Settings
from agent_web.main import create_app


class FakeCodex:
    capabilities = Capabilities(streaming=False, interrupt=True)

    def __init__(self):
        self.prompts = []

    async def health(self):
        return True, "ready"

    async def models(self):
        return [{"id": "test-model", "name": "Test model", "default": True,
                 "reasoning_efforts": ["low", "high"], "default_reasoning": "low"}]

    async def start_thread(self, cwd: Path, *, model, sandbox, reasoning=None, approval_policy="auto"):
        return "fixture-thread"

    async def thread_history(self, native_thread_id):
        return [{"role": "user", "content": "Earlier question"},
                {"role": "assistant", "content": "Earlier answer"}]

    async def list_threads(self, limit=100):
        return []

    async def run_turn(self, native_thread_id, prompt, *, sandbox):
        self.prompts.append(prompt)
        return f"answered: {prompt}"

    async def interrupt(self, native_thread_id):
        return True


class FakeOpenCode(FakeCodex):
    async def start_thread(self, cwd: Path, *, model, sandbox, reasoning=None, approval_policy="auto"):
        return "opencode:fixture-session"


class SyncingCodex(FakeCodex):
    def __init__(self):
        super().__init__()
        self.history = [{"role": "user", "content": "initial"}]

    async def thread_history(self, native_thread_id):
        return self.history


class LongHistoryCodex(FakeCodex):
    async def thread_history(self, native_thread_id):
        return [{"role": "user", "content": "x" * 120_001}]

    async def run_turn(self, native_thread_id, prompt, *, sandbox):
        self.prompts.append(prompt)
        if prompt.startswith("Summarize the work"):
            return "compact handoff summary"
        return f"answered: {prompt}"


def completed_turn(client: TestClient, response):
    assert response.status_code == 200
    turn_id = response.json()["id"]
    for _ in range(50):
        turn = client.get(f"/api/v1/turns/{turn_id}")
        assert turn.status_code == 200
        if turn.json()["status"] != "running":
            return turn.json()
        time.sleep(0.01)
    raise AssertionError("turn did not complete")


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
        turn = completed_turn(client, client.post(
            f"/api/v1/sessions/{session.json()['id']}/turns",
            json={"prompt": "hello", "client_request_id": "request-0001"},
        ))
        assert turn["response"] == "answered: hello"
        assert turn["rendered_response"] == "<p>answered: hello</p>\n"
        sessions = client.get(f"/api/v1/projects/{project_id}/sessions").json()
        assert sessions[0]["title"] == "hello"
        with sqlite3.connect(tmp_path / "data" / "agent-web.sqlite3") as database:
            database.execute("UPDATE agent_sessions SET title = NULL")
        legacy_sessions = client.get(f"/api/v1/projects/{project_id}/sessions").json()
        assert legacy_sessions[0]["title"] == "hello"


def test_project_outside_allowed_root_is_rejected(tmp_path: Path):
    allowed = tmp_path / "allowed"
    rejected = tmp_path / "outside"
    (rejected / ".git").mkdir(parents=True)
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(allowed,)), backend=FakeCodex())
    with TestClient(app) as client:
        response = client.post("/api/v1/projects", json={"name": "No", "path": str(rejected)})
    assert response.status_code == 422


def test_non_git_folder_inside_allowed_root_is_accepted(tmp_path: Path):
    root = tmp_path / "projects"
    folder = root / "scratch"
    folder.mkdir(parents=True)
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)), backend=FakeCodex())
    with TestClient(app) as client:
        response = client.post("/api/v1/projects", json={"name": "Scratch", "path": str(folder)})
    assert response.status_code == 201


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
            json={"model": "test-model", "reasoning": "high", "sandbox": "read_only",
                  "approval_policy": "auto"},
        )
        status = client.get("/api/v1/codex/status")
    assert saved.json()["reasoning"] == "high"
    assert saved.json()["sandbox"] == "read_only"
    assert status.json()["models"][0]["id"] == "test-model"
    assert status.json()["usage"]["available"] is False


def test_imported_session_history_is_available(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)), backend=FakeCodex())
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        session = client.post(f"/api/v1/projects/{project['id']}/sessions").json()
        history = client.get(f"/api/v1/sessions/{session['id']}/messages")
    assert history.json()[-1]["content"] == "Earlier answer"
    assert history.json()[-1]["rendered_content"] == "<p>Earlier answer</p>\n"


def test_opencode_can_be_selected_per_project(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)),
                     backend={"codex": FakeCodex(), "opencode": FakeOpenCode()})
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        saved = client.put(
            f"/api/v1/projects/{project['id']}/agent-settings",
            json={"agent": "opencode", "model": "test-model", "reasoning": None,
                  "sandbox": "workspace_write", "approval_policy": "auto"},
        )
        session = client.post(f"/api/v1/projects/{project['id']}/sessions")
    assert saved.json()["agent"] == "opencode"
    assert session.json()["native_thread_id"].startswith("opencode:")


def test_switching_agent_keeps_one_chat_and_hands_off_history(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    codex, opencode = FakeCodex(), FakeOpenCode()
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)),
                     backend={"codex": codex, "opencode": opencode})
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        chat = client.post(f"/api/v1/projects/{project['id']}/sessions").json()
        completed_turn(client, client.post(f"/api/v1/sessions/{chat['id']}/turns", json={
            "prompt": "remember this", "client_request_id": "request-0002"
        }))
        switched = client.post(f"/api/v1/sessions/{chat['id']}/switch", json={
            "agent": "opencode", "model": "test-model", "reasoning": "high",
            "sandbox": "workspace_write", "approval_policy": "auto",
        })
        turn = completed_turn(client, client.post(f"/api/v1/sessions/{chat['id']}/turns", json={
            "prompt": "continue", "client_request_id": "request-0003"
        }))
        context = client.get(f"/api/v1/sessions/{chat['id']}/context")
    assert switched.status_code == 201
    assert "Previous chat" in opencode.prompts[-1]
    assert "remember this" in opencode.prompts[-1]
    assert turn["status"] == "completed"
    assert len(context.json()["segments"]) == 2


def test_opening_chat_syncs_new_native_messages(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    backend = SyncingCodex()
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)), backend=backend)
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        chat = client.post(f"/api/v1/projects/{project['id']}/sessions").json()
        assert client.get(f"/api/v1/sessions/{chat['id']}/messages").json()[-1]["content"] == "initial"
        backend.history.append({"role": "assistant", "content": "written outside Agent Web"})
        history = client.get(f"/api/v1/sessions/{chat['id']}/messages").json()
    assert history[-1]["content"] == "written outside Agent Web"


def test_opening_chat_places_new_native_messages_after_saved_turns(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    backend = SyncingCodex()
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)), backend=backend)
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        chat = client.post(f"/api/v1/projects/{project['id']}/sessions").json()
        completed_turn(client, client.post(f"/api/v1/sessions/{chat['id']}/turns", json={
            "prompt": "saved locally", "client_request_id": "request-history-order",
        }))
        backend.history = [
            {"role": "user", "content": "saved locally"},
            {"role": "assistant", "content": "answered: saved locally"},
            {"role": "user", "content": "written outside Agent Web"},
        ]
        history = client.get(f"/api/v1/sessions/{chat['id']}/messages").json()
    assert [message["content"] for message in history] == [
        "saved locally", "answered: saved locally", "written outside Agent Web",
    ]


def test_long_history_uses_source_agent_summary_for_handoff(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    source, target = LongHistoryCodex(), FakeOpenCode()
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)),
                     backend={"codex": source, "opencode": target})
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        chat = client.post(f"/api/v1/projects/{project['id']}/sessions").json()
        client.post(f"/api/v1/sessions/{chat['id']}/switch", json={
            "agent": "opencode", "model": "test-model", "reasoning": "high",
            "sandbox": "workspace_write", "approval_policy": "auto",
        })
        completed_turn(client, client.post(f"/api/v1/sessions/{chat['id']}/turns", json={
            "prompt": "continue", "client_request_id": "request-0004"
        }))
    assert any(prompt.startswith("Summarize the work") for prompt in source.prompts)
    assert "compact handoff summary" in target.prompts[-1]
