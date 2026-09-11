import asyncio
from datetime import datetime, timedelta
import json

import httpx
import pytest

from agent_web.cli import load_settings
from agent_web.config import Settings, write_config
from agent_web.db.database import create_database
from agent_web.db.models import AuditEvent, Base
from agent_web.telemetry import Connection, build_payload, load_state, run_telemetry, send_payload


@pytest.fixture
async def database(tmp_path):
    engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}")
    async with engine.begin() as db:
        await db.run_sync(Base.metadata.create_all)
    yield sessions
    await engine.dispose()


def metrics(payload):
    return {m["name"]: m for m in payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]}


def total(metric):
    return sum(p["asDouble"] for p in metric["sum"]["dataPoints"])


def test_config_token_is_the_only_enable_switch(tmp_path):
    assert Connection.from_config({}) is None
    assert Connection.from_config({"token": "  ", "endpoint": "invalid"}) is None
    config = {"endpoint": "https://otlp-gateway-prod-test.grafana.net/otlp",
              "instance_id": "123", "token": "secret"}
    write_config(tmp_path, {"roots": [], "telemetry": config})
    settings = load_settings(tmp_path)
    connection = Connection.from_config(settings.telemetry)
    assert connection.endpoint.endswith("/otlp/v1/metrics")
    assert "secret" not in repr(settings)
    assert "secret" not in repr(connection)
    assert Connection.from_config({**config, "endpoint": connection.endpoint}) == connection


@pytest.mark.parametrize("endpoint", [
    "http://otlp.grafana.net/otlp", "https://grafana.net.attacker.test/otlp",
    "https://secret@otlp.grafana.net/otlp", "https://otlp.grafana.net/otlp?token=secret",
])
def test_credentials_only_go_to_grafana_https(endpoint):
    with pytest.raises(ValueError):
        Connection.from_config({"endpoint": endpoint, "instance_id": "123", "token": "secret"})


async def test_committed_events_survive_restart_and_exclude_history_and_content(database, tmp_path):
    async with database() as db:
        db.add(AuditEvent(kind="session.created", detail="old private history"))
        await db.commit()
    path = tmp_path / "telemetry-state.json"
    state = await load_state(path, database)
    initial = metrics(await build_payload(state, database))
    assert total(initial["agent_web_chats_created"]) == 0
    start = datetime(2026, 9, 11, 12)
    secret = "TOP_SECRET_prompt_path_native_id"
    async with database() as db:
        for kind, subject, elapsed, detail in [
            ("codex.sessions_imported", "import", 0, secret),
            ("chat.external_messages_synced", "external", 0, secret),
            ("session.created", "chat", 0, secret),
            ("turn.started", "turn", 0, json.dumps({"agent": "codex", "prompt": secret})),
            ("turn.completed", "turn", 10, json.dumps({"agent": "codex", "response": secret})),
            ("turn.started", "failed-turn", 20, json.dumps({"agent": "custom-private-name"})),
            ("turn.failed", "failed-turn", 22, json.dumps({"error_type": "TimeoutError", "trace": secret})),
            ("turn.interrupted", "recovered-turn", 23, secret),
        ]:
            db.add(AuditEvent(kind=kind, subject_id=subject, detail=detail,
                              created_at=start + timedelta(seconds=elapsed)))
        await db.commit()
    payload = await build_payload(state, database)
    assert secret not in json.dumps(payload)
    assert "custom-private-name" not in json.dumps(payload)
    actual = metrics(payload)
    assert total(actual["agent_web_chats_created"]) == 1
    assert total(actual["agent_web_messages_sent"]) == 2
    assert total(actual["agent_web_turns_finished"]) == 3
    assert total(actual["agent_web_errors"]) == 1
    histogram = actual["agent_web_turn_duration_seconds"]["histogram"]["dataPoints"][0]
    assert histogram["count"] == "2"
    assert histogram["sum"] == pytest.approx(12, abs=0.001)
    assert histogram["bucketCounts"] == ["0", "1", "1", "0", "0", "0", "0", "0", "0"]
    restored = await load_state(path, database)
    assert restored == state
    again = metrics(await build_payload(restored, database))
    assert total(again["agent_web_messages_sent"]) == 2
    assert (actual["agent_web_last_activity_timestamp_seconds"]["gauge"]["dataPoints"][0]["asDouble"]
            == again["agent_web_last_activity_timestamp_seconds"]["gauge"]["dataPoints"][0]["asDouble"])


@pytest.mark.parametrize("response", [
    httpx.Response(401, text="secret-server-error"),
    httpx.Response(429), httpx.Response(503),
    httpx.Response(302, headers={"Location": "https://attacker.test"}),
    httpx.Response(200, json={"partialSuccess": {"rejectedDataPoints": "1", "errorMessage": "secret"}}),
])
async def test_export_failures_and_redirects_are_redacted(response, caplog):
    requests = []
    def handler(request):
        requests.append(request)
        return response
    connection = Connection("https://otlp.grafana.net/otlp/v1/metrics", "123", "secret")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert not await send_payload(client, connection, {"resourceMetrics": []})
    assert len(requests) == 1
    assert "secret" not in caplog.text
    assert "Authorization" not in caplog.text


async def test_otlp_json_and_basic_auth():
    def handler(request):
        assert request.headers["authorization"] == "Basic MTIzOnNlY3JldA=="
        assert request.headers["content-type"] == "application/json"
        assert json.loads(request.content) == {"resourceMetrics": []}
        return httpx.Response(200, json={})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await send_payload(client, Connection("https://otlp.grafana.net/otlp/v1/metrics", "123", "secret"),
                                  {"resourceMetrics": []})


async def test_missing_token_does_not_touch_database_or_disk(tmp_path):
    await run_telemetry(Settings(data_dir=tmp_path), None)
    assert not list(tmp_path.iterdir())


async def test_corrupt_state_fails_closed(database, tmp_path, caplog):
    (tmp_path / "telemetry-state.json").write_text('{"secret": "private"}')
    await run_telemetry(Settings(data_dir=tmp_path, telemetry={
        "endpoint": "https://otlp.grafana.net/otlp", "instance_id": "123", "token": "secret",
    }), database)
    assert "Telemetry disabled" in caplog.text
    assert "private" not in caplog.text


async def test_exporter_backoff_and_cancellation(database, tmp_path, monkeypatch):
    import agent_web.telemetry as telemetry
    delays = []
    attempts = []
    async def send(*args):
        attempts.append(True)
        return len(attempts) == 3
    async def sleep(delay):
        delays.append(delay)
        if len(delays) == 3:
            raise asyncio.CancelledError
    monkeypatch.setattr(telemetry, "send_payload", send)
    monkeypatch.setattr(telemetry.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await run_telemetry(Settings(data_dir=tmp_path, telemetry={
            "endpoint": "https://otlp.grafana.net/otlp", "instance_id": "123", "token": "secret",
        }), database)
    assert delays == [120, 240, 60]
