import io
import sqlite3
import time
import zipfile
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from agent_web.codex.base import Capabilities
from agent_web.config import Settings
from agent_web.main import create_app


class FakeCodex:
    capabilities = Capabilities(streaming=False, interrupt=True)

    def __init__(self):
        self.prompts = []
        self.runs = []
        self.starts = []
        self.started_threads = 0

    async def health(self):
        return True, "ready"

    async def models(self):
        return [
            {"id": "test-model", "name": "Test model", "default": True,
             "reasoning_efforts": ["low", "high"], "default_reasoning": "low"},
            {"id": "other-model", "name": "Other model", "default": False,
             "reasoning_efforts": ["low", "high"], "default_reasoning": "low"},
        ]

    async def start_thread(self, cwd: Path, *, model, sandbox, reasoning=None, approval_policy="auto"):
        self.started_threads += 1
        self.starts.append({"model": model, "reasoning": reasoning})
        return "fixture-thread"

    async def thread_history(self, native_thread_id):
        return [{"role": "user", "content": "Earlier question"},
                {"role": "assistant", "content": "Earlier answer"}]

    async def list_threads(self, limit=100):
        return []

    async def run_turn(self, native_thread_id, prompt, *, sandbox, model=None, reasoning=None):
        self.prompts.append(prompt)
        self.runs.append({"thread": native_thread_id, "model": model, "reasoning": reasoning})
        return f"answered: {prompt}"

    async def interrupt(self, native_thread_id):
        return True


class FakeOpenCode(FakeCodex):
    async def start_thread(self, cwd: Path, *, model, sandbox, reasoning=None, approval_policy="auto"):
        self.started_threads += 1
        return "opencode:fixture-session"


class UsageCodex(FakeCodex):
    async def usage(self):
        return {
            "available": True,
            "plan_type": "chatgpt_plus",
            "primary": {"remaining_percent": 72, "window_duration_mins": 300,
                        "resets_at": 1_800_000_000},
            "secondary": None,
            "credits": {"balance": "12.5", "has_credits": True, "unlimited": False},
        }


class SyncingCodex(FakeCodex):
    def __init__(self):
        super().__init__()
        self.history = [{"role": "user", "content": "initial"}]

    async def thread_history(self, native_thread_id):
        return self.history


class LongHistoryCodex(FakeCodex):
    async def thread_history(self, native_thread_id):
        return [{"role": "user", "content": "x" * 120_001}]

    async def run_turn(self, native_thread_id, prompt, *, sandbox, model=None, reasoning=None):
        self.prompts.append(prompt)
        self.runs.append({"thread": native_thread_id, "model": model, "reasoning": reasoning})
        if prompt.startswith("Summarize the work"):
            return "compact handoff summary"
        return f"answered: {prompt}"


class FailingCodex(FakeCodex):
    async def thread_history(self, native_thread_id):
        return []

    async def run_turn(self, native_thread_id, prompt, *, sandbox, model=None, reasoning=None):
        raise RuntimeError("agent process could not start")


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


def test_failed_turn_remains_in_chat_history(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)), backend=FailingCodex())

    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        chat = client.post(f"/api/v1/projects/{project['id']}/sessions").json()
        turn = completed_turn(client, client.post(
            f"/api/v1/sessions/{chat['id']}/turns",
            json={"prompt": "Launch agent", "client_request_id": "failed-agent-start"},
        ))
        history = client.get(f"/api/v1/sessions/{chat['id']}/messages").json()

    assert turn["status"] == "failed"
    assert [(message["role"], message["content"]) for message in history] == [
        ("user", "Launch agent"),
        ("assistant", turn["response"]),
    ]


def test_chat_export_inlines_text_packages_images_and_removes_attachments(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    backend = FakeCodex()
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)), backend=backend)

    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        chat = client.post(f"/api/v1/projects/{project['id']}/sessions").json()
        text_turn = completed_turn(client, client.post(
            f"/api/v1/sessions/{chat['id']}/turns",
            data={"prompt": "", "client_request_id": "attachment-request"},
            files=[("files", ("notes.txt", b"important attachment text", "text/plain"))],
        ))

        assert text_turn["status"] == "completed"
        assert "important attachment text" in backend.prompts[-1]
        assert str(repo / ".agent-web" / "attachments" / chat["id"]) in backend.prompts[-1]
        markdown_export = client.get(f"/api/v1/sessions/{chat['id']}/export")
        assert markdown_export.headers["content-type"].startswith("text/markdown")
        assert 'filename="chat.md"' in markdown_export.headers["content-disposition"]
        assert "important attachment text" in markdown_export.text

        image_turn = completed_turn(client, client.post(
            f"/api/v1/sessions/{chat['id']}/turns",
            data={"prompt": "Inspect image", "client_request_id": "image-attachment-request"},
            files=[("files", ("diagram.png", b"fake image bytes", "image/png"))],
        ))
        assert image_turn["status"] == "completed"
        history = client.get(f"/api/v1/sessions/{chat['id']}/messages").json()
        attachments = [item for message in history for item in message.get("attachments", [])]
        assert [item["name"] for item in attachments] == ["notes.txt", "diagram.png"]

        archive_export = client.get(f"/api/v1/sessions/{chat['id']}/export")
        assert archive_export.headers["content-type"] == "application/zip"
        assert 'filename="chat.zip"' in archive_export.headers["content-disposition"]
        with zipfile.ZipFile(io.BytesIO(archive_export.content)) as archive:
            assert set(archive.namelist()) == {"chat.md", "attachments/diagram.png"}
            markdown = archive.read("chat.md").decode("utf-8")
            assert "important attachment text" in markdown
            assert "![diagram.png](attachments/diagram.png)" in markdown
            assert archive.read("attachments/diagram.png") == b"fake image bytes"
        attachment_dir = repo / ".agent-web" / "attachments" / chat["id"]
        assert len(list(attachment_dir.iterdir())) == 2
        assert ".agent-web/" in (repo / ".git" / "info" / "exclude").read_text("utf-8")

        assert client.delete(f"/api/v1/sessions/{chat['id']}").status_code == 204
        assert not attachment_dir.exists()


def test_deleting_chat_archives_it_and_blocks_access(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)), backend=FakeCodex())
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        chat = client.post(f"/api/v1/projects/{project['id']}/sessions").json()

        deleted = client.delete(f"/api/v1/sessions/{chat['id']}")

        assert deleted.status_code == 204
        assert client.get(f"/api/v1/projects/{project['id']}/sessions").json() == []
        assert client.get(f"/api/v1/sessions/{chat['id']}/messages").status_code == 404
    with sqlite3.connect(tmp_path / "data" / "agent-web.sqlite3") as database:
        archived, native_id = database.execute(
            "SELECT archived, native_thread_id FROM agent_sessions WHERE id = ?", (chat["id"],)
        ).fetchone()
    assert archived == 1
    assert native_id == "fixture-thread"


def test_deleting_busy_chat_is_rejected(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)), backend=FakeCodex())
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        chat = client.post(f"/api/v1/projects/{project['id']}/sessions").json()
        with sqlite3.connect(tmp_path / "data" / "agent-web.sqlite3") as database:
            database.execute(
                "INSERT INTO turns (id, session_id, client_request_id, prompt, status) VALUES (?, ?, ?, ?, ?)",
                (str(uuid4()), chat["id"], "busy-request", "still working", "running"),
            )

        response = client.delete(f"/api/v1/sessions/{chat['id']}")

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "chat_busy"
        assert len(client.get(f"/api/v1/projects/{project['id']}/sessions").json()) == 1


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


def test_global_codex_defaults_and_custom_instructions_apply_to_new_chat(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    backend = FakeCodex()
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)), backend=backend)

    with TestClient(app) as client:
        saved = client.put("/api/v1/settings", json={
            "model": "other-model",
            "reasoning": "high",
            "custom_instructions": "Use Git and keep tests focused.",
        })
        project = client.post(
            "/api/v1/projects", json={"name": "Sample", "path": str(repo)}
        ).json()
        chat = client.post(f"/api/v1/projects/{project['id']}/sessions").json()
        completed_turn(client, client.post(
            f"/api/v1/sessions/{chat['id']}/turns",
            json={"prompt": "Implement it", "client_request_id": "global-settings-turn"},
        ))

    assert saved.status_code == 200
    assert backend.starts[-1] == {"model": "other-model", "reasoning": "high"}
    assert "Use Git and keep tests focused." in backend.prompts[-1]
    assert backend.prompts[-1].endswith("Current user request:\nImplement it")
    assert backend.runs[-1]["model"] == "other-model"
    assert backend.runs[-1]["reasoning"] == "high"


def test_agent_list_includes_codex_usage(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path / "data"), backend=UsageCodex())
    with TestClient(app) as client:
        codex = client.get("/api/v1/agents").json()["codex"]

    assert codex["usage"]["primary"]["remaining_percent"] == 72
    assert codex["usage"]["credits"]["balance"] == "12.5"


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
            "sandbox": "workspace_write", "approval_policy": "auto", "transfer_context": True,
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


def test_switching_codex_model_reuses_native_thread_without_handoff(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    codex = FakeCodex()
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)), backend=codex)
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        chat = client.post(f"/api/v1/projects/{project['id']}/sessions").json()
        completed_turn(client, client.post(f"/api/v1/sessions/{chat['id']}/turns", json={
            "prompt": "before model switch", "client_request_id": "request-before-model-switch",
        }))
        switched = client.post(f"/api/v1/sessions/{chat['id']}/switch", json={
            "agent": "codex", "model": "other-model", "reasoning": "high",
            "sandbox": "workspace_write", "approval_policy": "auto",
        })
        completed_turn(client, client.post(f"/api/v1/sessions/{chat['id']}/turns", json={
            "prompt": "continue natively", "client_request_id": "request-model-switch",
        }))
        context = client.get(f"/api/v1/sessions/{chat['id']}/context").json()
    assert switched.status_code == 201
    assert codex.started_threads == 1
    assert codex.runs[-1] == {"thread": "fixture-thread", "model": "other-model", "reasoning": "high"}
    assert "Previous chat" not in codex.prompts[-1]
    assert len(context["segments"]) == 1
    answer_models = [item["model"] for item in context["messages"]
                     if item["content"].startswith("answered:")]
    assert answer_models == ["", "other-model"]


def test_cross_agent_switch_requires_explicit_context_consent(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)),
                     backend={"codex": FakeCodex(), "opencode": FakeOpenCode()})
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        chat = client.post(f"/api/v1/projects/{project['id']}/sessions").json()
        switched = client.post(f"/api/v1/sessions/{chat['id']}/switch", json={
            "agent": "opencode", "model": "test-model", "reasoning": "high",
            "sandbox": "workspace_write", "approval_policy": "auto",
        })
    assert switched.status_code == 422
    assert switched.json()["detail"]["code"] == "invalid_agent_settings"


def test_cross_agent_switch_can_start_without_context(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    target = FakeOpenCode()
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)),
                     backend={"codex": FakeCodex(), "opencode": target})
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        chat = client.post(f"/api/v1/projects/{project['id']}/sessions").json()
        client.post(f"/api/v1/sessions/{chat['id']}/switch", json={
            "agent": "opencode", "model": "test-model", "reasoning": "high",
            "sandbox": "workspace_write", "approval_policy": "auto", "transfer_context": False,
        })
        completed_turn(client, client.post(f"/api/v1/sessions/{chat['id']}/turns", json={
            "prompt": "start clean", "client_request_id": "request-clean-switch",
        }))
    assert target.prompts[-1] == "start clean"


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
            "sandbox": "workspace_write", "approval_policy": "auto", "transfer_context": True,
        })
        completed_turn(client, client.post(f"/api/v1/sessions/{chat['id']}/turns", json={
            "prompt": "continue", "client_request_id": "request-0004"
        }))
    assert any(prompt.startswith("Summarize the work") for prompt in source.prompts)
    assert "compact handoff summary" in target.prompts[-1]
