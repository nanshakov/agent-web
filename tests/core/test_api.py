import io
import re
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
        self.titles = []
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

    async def set_thread_title(self, native_thread_id, title):
        self.titles.append({"thread": native_thread_id, "title": title})

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


class BusyThenReadyCodex(FakeCodex):
    def __init__(self):
        super().__init__()
        self.attempts = 0

    async def run_turn(self, native_thread_id, prompt, *, sandbox, model=None, reasoning=None):
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError(
                "JSON-RPC error -32600: thread fixture-thread already has an active writer"
            )
        return await super().run_turn(
            native_thread_id, prompt, sandbox=sandbox, model=model, reasoning=reasoning
        )


class PermanentlyBusyCodex(FakeCodex):
    async def start_thread(self, cwd: Path, *, model, sandbox, reasoning=None, approval_policy="auto"):
        self.started_threads += 1
        native_id = f"fixture-thread-{self.started_threads}"
        self.starts.append({"model": model, "reasoning": reasoning})
        return native_id

    async def run_turn(self, native_thread_id, prompt, *, sandbox, model=None, reasoning=None):
        self.prompts.append(prompt)
        self.runs.append({"thread": native_thread_id, "model": model, "reasoning": reasoning})
        if native_thread_id == "fixture-thread-1":
            raise RuntimeError(
                "JSON-RPC error -32600: thread fixture-thread-1 already has an active writer"
            )
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
        assert sessions[0]["created_at"]
        assert sessions[0]["last_activity_at"]
        history = client.get(f"/api/v1/sessions/{session.json()['id']}/messages").json()
        assert all(message["created_at"] for message in history)
        with sqlite3.connect(tmp_path / "data" / "agent-web.sqlite3") as database:
            database.execute("UPDATE agent_sessions SET title = NULL")
        legacy_sessions = client.get(f"/api/v1/projects/{project_id}/sessions").json()
        assert legacy_sessions[0]["title"] == "hello"


def test_configured_telemetry_counts_api_requests_once(tmp_path: Path, monkeypatch):
    import json
    import threading
    import agent_web.telemetry as telemetry

    sent = threading.Event()
    async def send(*args):
        sent.set()
        return True
    monkeypatch.setattr(telemetry, "send_payload", send)
    repo = tmp_path / "project"
    repo.mkdir()
    settings = Settings(data_dir=tmp_path / "data", allowed_roots=(repo,), telemetry={
        "endpoint": "https://otlp.grafana.net/otlp", "instance_id": "123", "token": "secret",
    })
    app = create_app(settings, backend=FakeCodex())
    with TestClient(app) as client:
        assert sent.wait(5), "Configured exporter must start with the application"
        project = client.post("/api/v1/projects", json={"name": "Private", "path": str(repo)}).json()
        chat = client.post(f"/api/v1/projects/{project['id']}/sessions").json()
        request = {"prompt": "PRIVATE_PROMPT", "client_request_id": "telemetry-retry"}
        url = f"/api/v1/sessions/{chat['id']}/turns"
        completed_turn(client, client.post(url, json=request))
        completed_turn(client, client.post(url, json=request))
        state = json.loads((settings.data_dir / "telemetry-state.json").read_text())
        payload = client.portal.call(telemetry.build_payload, state, app.state.service.session_factory)
        metrics = {m["name"]: m for m in payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]}
        for name in ("agent_web_chats_created", "agent_web_messages_sent", "agent_web_turns_finished"):
            assert sum(p["asDouble"] for p in metrics[name]["sum"]["dataPoints"]) == 1
        assert "PRIVATE_PROMPT" not in json.dumps(payload)
        assert str(repo) not in json.dumps(payload)


def test_sessions_are_ordered_by_latest_activity(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)), backend=FakeCodex())
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        with sqlite3.connect(tmp_path / "data" / "agent-web.sqlite3") as database:
            database.executemany(
                "INSERT INTO agent_sessions (id, project_id, native_thread_id, title, archived, created_at) "
                "VALUES (?, ?, ?, ?, 0, ?)",
                [
                    ("old-chat", project["id"], "old-thread", "Older", "2026-01-01 10:00:00"),
                    ("new-chat", project["id"], "new-thread", "Newer", "2026-01-02 10:00:00"),
                ],
            )
            database.execute(
                "INSERT INTO turns (id, session_id, client_request_id, prompt, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("old-turn", "old-chat", "old-request", "A newer message", "completed", "2026-01-03 10:00:00"),
            )
            database.commit()
        sessions = client.get(f"/api/v1/projects/{project['id']}/sessions").json()

    assert [session["id"] for session in sessions] == ["old-chat", "new-chat"]
    assert all(session["last_activity_at"] for session in sessions)


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
        with sqlite3.connect(tmp_path / "data" / "agent-web.sqlite3") as database:
            audit_events = database.execute(
                "SELECT kind, subject_id, detail FROM audit_events WHERE subject_id = ? ORDER BY created_at",
                (turn["id"],),
            ).fetchall()

    assert turn["status"] == "failed"
    assert "RuntimeError: agent process could not start" in turn["response"]
    assert "Traceback:" in turn["response"]
    assert [(message["role"], message["content"]) for message in history] == [
        ("user", "Launch agent"),
        ("assistant", turn["response"]),
    ]
    assert [event[0] for event in audit_events] == ["turn.started", "turn.dispatched", "turn.failed"]
    assert all(event[1] == turn["id"] for event in audit_events)
    assert all('"session_id"' in event[2] for event in audit_events)
    assert '"error_type":"RuntimeError"' in audit_events[-1][2]
    trace_log = (tmp_path / "data" / "logs" / "turn-trace.log").read_text(encoding="utf-8")
    assert f"turn_id={turn['id']}" in trace_log
    assert "event=failed" in trace_log
    assert "Launch agent" not in trace_log


def test_running_turn_is_visible_in_chat_history_and_is_audited(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)), backend=FakeCodex())

    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        chat = client.post(f"/api/v1/projects/{project['id']}/sessions").json()
        with sqlite3.connect(tmp_path / "data" / "agent-web.sqlite3") as database:
            segment_id = database.execute(
                "SELECT id FROM agent_segments WHERE session_id = ?", (chat["id"],)
            ).fetchone()[0]
            database.execute(
                "INSERT INTO turns (id, session_id, segment_id, client_request_id, prompt, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid4()), chat["id"], segment_id, "running-history-request", "still working", "running"),
            )
            database.commit()
        history = client.get(f"/api/v1/sessions/{chat['id']}/messages").json()

    assert [(message["role"], message["content"]) for message in history] == [
        ("user", "Earlier question"),
        ("assistant", "Earlier answer"),
        ("user", "still working"),
    ]
    assert history[-1]["turn_id"]
    assert history[-1]["status"] == "running"


def test_turn_retries_when_native_codex_thread_has_an_active_writer(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    backend = BusyThenReadyCodex()
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)), backend=backend)
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        session = client.post(f"/api/v1/projects/{project['id']}/sessions").json()
        turn = completed_turn(client, client.post(
            f"/api/v1/sessions/{session['id']}/turns",
            json={"prompt": "status", "client_request_id": "active-writer-retry"},
        ))

    assert turn["status"] == "completed"
    assert turn["response"] == "answered: status"
    assert backend.attempts == 2


def test_turn_rotates_a_permanently_busy_native_thread_and_transfers_history(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    backend = PermanentlyBusyCodex()
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)), backend=backend)
    app.state.service.NATIVE_THREAD_BUSY_RETRY_ATTEMPTS = 2
    app.state.service.NATIVE_THREAD_BUSY_RETRY_DELAY_SECONDS = 0

    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        session = client.post(f"/api/v1/projects/{project['id']}/sessions").json()
        turn = completed_turn(client, client.post(
            f"/api/v1/sessions/{session['id']}/turns",
            json={"prompt": "continue", "client_request_id": "active-writer-rollover"},
        ))
        context = client.get(f"/api/v1/sessions/{session['id']}/context").json()

    assert turn["status"] == "completed"
    assert backend.started_threads == 2
    assert backend.runs[-1]["thread"] == "fixture-thread-2"
    assert "Previous chat" in backend.prompts[-1]
    assert "Earlier answer" in backend.prompts[-1]
    assert [segment["status"] for segment in context["segments"]] == ["superseded", "active"]


def test_react_routes_serve_bundled_assets_without_masking_api_errors(tmp_path: Path):
    root = tmp_path / "projects"
    root.mkdir()
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)), backend=FakeCodex())
    with TestClient(app) as client:
        home = client.get("/")
        assert '<div id="root"></div>' in home.text
        assert home.headers["cache-control"] == "no-cache"
        assert client.get("/projects/example/chats/existing").text == home.text
        assert client.get("/projects/example").text == home.text
        match = re.search(r'src="(/assets/[^"]+\.js)"', home.text)
        assert match is not None
        asset = match.group(1)
        assert client.get(asset).status_code == 200
        assert client.get("/api/v1/missing").status_code == 404
        assert client.get("/assets/missing.js").status_code == 404


def test_session_websocket_replays_turn_state(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)), backend=FakeCodex())
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        chat = client.post(f"/api/v1/projects/{project['id']}/sessions").json()
        app.state.service._publish_turn_event({
            "type": "turn.completed", "turn_id": "turn-1", "session_id": chat["id"],
            "status": "completed", "content": "streamed answer",
        })
        with client.websocket_connect(f"/api/v1/ws/sessions/{chat['id']}") as websocket:
            event = websocket.receive_json()

    assert event == {
        "type": "turn.completed", "turn_id": "turn-1", "session_id": chat["id"],
        "status": "completed", "content": "streamed answer",
        "rendered_content": "<p>streamed answer</p>\n",
    }


def test_tool_activity_survives_websocket_replay_and_server_restart(tmp_path: Path):
    class ActivityCodex(FakeCodex):
        capabilities = Capabilities(streaming=True, activity=True)

        async def stream_turn(self, native_thread_id, prompt, *, on_delta, on_activity, **kwargs):
            await on_delta("Working text")
            await on_activity({"id": "tool1", "kind": "mcpToolCall", "label": "MCP · docs / search", "status": "running"})
            await on_activity({"id": "tool1", "kind": "mcpToolCall", "label": "MCP · docs / search", "status": "completed"})
            await on_activity({"id": "tool2", "kind": "commandExecution", "label": "Command", "status": "running"})
            return "Done"

    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    settings = Settings(data_dir=tmp_path / "data", allowed_roots=(root,))
    app = create_app(settings, backend=ActivityCodex())
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        chat = client.post(f"/api/v1/projects/{project['id']}/sessions").json()
        turn = completed_turn(client, client.post(f"/api/v1/sessions/{chat['id']}/turns", json={"prompt": "test", "client_request_id": "activity"}))
        assert turn["status"] == "completed"
        with client.websocket_connect(f"/api/v1/ws/sessions/{chat['id']}") as websocket:
            event = websocket.receive_json()
        assert event["content"] == "Done"
        assert [item["status"] for item in event["activities"]] == ["completed", "interrupted"]
    with TestClient(create_app(settings, backend=ActivityCodex())) as client:
        messages = client.get(f"/api/v1/sessions/{chat['id']}/messages").json()
        answer = next(m for m in messages if m.get("turn_id") == turn["id"] and m["role"] == "assistant")
        assert answer["activities"] == event["activities"]


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
            json={"prompt": "Как работает Alois Roots", "client_request_id": "global-settings-turn"},
        ))

    assert saved.status_code == 200
    assert backend.starts[-1] == {"model": "other-model", "reasoning": "high"}
    assert "Use Git and keep tests focused." in backend.prompts[-1]
    assert backend.prompts[-1].endswith("Current user request:\nКак работает Alois Roots")
    assert backend.titles == [{"thread": "fixture-thread", "title": "Как работает Alois Roots"}]
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


def test_new_session_accepts_agent_settings_before_creation_and_lists_active_settings(tmp_path: Path):
    root = tmp_path / "projects"
    repo = root / "sample"
    (repo / ".git").mkdir(parents=True)
    codex, opencode = FakeCodex(), FakeOpenCode()
    app = create_app(Settings(data_dir=tmp_path / "data", allowed_roots=(root,)),
                     backend={"codex": codex, "opencode": opencode})
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "Sample", "path": str(repo)}).json()
        session = client.post(f"/api/v1/projects/{project['id']}/sessions", json={
            "agent": "opencode", "model": "test-model", "reasoning": "high",
            "sandbox": "read_only", "approval_policy": "auto",
        })
        listed = client.get(f"/api/v1/projects/{project['id']}/sessions").json()
    assert session.status_code == 201
    assert opencode.started_threads == 1
    assert listed[0]["agent"] == "opencode"
    assert listed[0]["model"] == "test-model"
    assert listed[0]["reasoning"] == "high"
    assert listed[0]["sandbox"] == "read_only"


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
