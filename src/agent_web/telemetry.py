"""Content-free, cumulative OTLP metrics derived from committed local audit events.

No event payload, exception text, native ID or machine identifier leaves this module.
SQLite remains the durable queue; network retries only send a newer aggregate.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from importlib.metadata import version
import json
import logging
from pathlib import Path
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text

from agent_web.config import Settings

logger = logging.getLogger(__name__)
AGENTS = ("codex", "opencode", "other")
OUTCOMES = ("completed", "failed", "interrupted")
CATEGORIES = ("timeout", "connection", "authentication", "internal", "unknown")
BOUNDS = (1, 5, 15, 30, 60, 120, 300, 600)


@dataclass(frozen=True)
class Connection:
    endpoint: str
    instance_id: str
    token: str = field(repr=False)

    @classmethod
    def from_config(cls, config: dict) -> Connection | None:
        if not isinstance(config, dict):
            raise ValueError("Invalid telemetry configuration")
        token = config.get("token")
        if not token or (isinstance(token, str) and not token.strip()):
            return None
        endpoint = config.get("endpoint", "")
        instance_id = config.get("instance_id", "")
        if not all(isinstance(value, str) for value in (token, endpoint, instance_id)):
            raise ValueError("Invalid telemetry configuration")
        url = urlsplit(endpoint)
        if (url.scheme != "https" or not (url.hostname or "").endswith(".grafana.net")
                or url.username or url.password or url.query or url.fragment
                or url.port not in (None, 443) or not instance_id.strip()):
            raise ValueError("Expected Grafana Cloud HTTPS OTLP endpoint and instance ID")
        endpoint = endpoint.rstrip("/")
        if not endpoint.endswith("/v1/metrics"):
            endpoint += "/v1/metrics"
        return cls(endpoint, instance_id.strip(), token.strip())


async def load_state(path: Path, session_factory) -> dict:
    if path.exists():
        state = json.loads(path.read_text("utf-8"))
        UUID(state["installation_id"])
        if (type(state["baseline_rowid"]) is not int or state["baseline_rowid"] < 0
                or type(state["start_ns"]) is not int or state["start_ns"] <= 0):
            raise ValueError("Invalid telemetry state")
        return state
    async with session_factory() as db:
        baseline = await db.scalar(text("SELECT coalesce(max(rowid), 0) FROM audit_events"))
    state = {"installation_id": str(uuid4()), "baseline_rowid": baseline, "start_ns": time.time_ns()}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state) + "\n", "utf-8")
    temporary.replace(path)
    return state


# Extract only allowlisted categories inside SQLite; never load audit detail into Python.
EVENTS_SQL = """
WITH events AS (
  SELECT kind, created_at,
    CASE WHEN json_valid(detail) THEN json_extract(detail, '$.agent') END AS raw_agent,
    CASE WHEN json_valid(detail) THEN json_extract(detail, '$.error_type') END AS error_type
  FROM audit_events WHERE rowid > :baseline AND rowid <= :upper
    AND kind IN ('session.created', 'turn.started', 'turn.completed', 'turn.failed', 'turn.interrupted')
)
SELECT kind,
  CASE WHEN raw_agent IN ('codex', 'opencode') THEN raw_agent ELSE 'other' END AS agent,
  CASE WHEN error_type IN ('TimeoutError', 'ReadTimeout', 'ConnectTimeout') THEN 'timeout'
       WHEN error_type IN ('ConnectionError', 'ConnectError', 'BrokenPipeError') THEN 'connection'
       WHEN error_type IN ('AuthenticationError', 'PermissionError') THEN 'authentication'
       WHEN error_type IN ('RuntimeError', 'ValueError', 'TypeError', 'KeyError') THEN 'internal'
       ELSE 'unknown' END AS category,
  count(*) AS amount, max(cast(strftime('%s', created_at) AS INTEGER)) AS latest
FROM events GROUP BY kind, agent, category
"""

DURATION_SQL = """
WITH durations AS (
  SELECT max(0, (julianday(f.created_at) - julianday(s.created_at)) * 86400) AS seconds
  FROM audit_events s JOIN audit_events f ON s.subject_id = f.subject_id
  WHERE s.rowid > :baseline AND s.rowid <= :upper AND f.rowid <= :upper AND s.kind = 'turn.started'
    AND f.kind IN ('turn.completed', 'turn.failed')
)
SELECT CASE WHEN seconds <= 1 THEN 0 WHEN seconds <= 5 THEN 1
       WHEN seconds <= 15 THEN 2 WHEN seconds <= 30 THEN 3
       WHEN seconds <= 60 THEN 4 WHEN seconds <= 120 THEN 5
       WHEN seconds <= 300 THEN 6 WHEN seconds <= 600 THEN 7 ELSE 8 END AS bucket,
       count(*) AS amount, sum(seconds) AS seconds
FROM durations GROUP BY bucket
"""


def attribute(key: str, value: str) -> dict:
    return {"key": key, "value": {"stringValue": value}}


async def build_payload(state: dict, session_factory) -> dict:
    async with session_factory() as db:
        upper = await db.scalar(text("SELECT coalesce(max(rowid), 0) FROM audit_events"))
        parameters = {"baseline": state["baseline_rowid"], "upper": upper}
        events = (await db.execute(text(EVENTS_SQL), parameters)).mappings().all()
        durations = (await db.execute(text(DURATION_SQL), parameters)).mappings().all()
    now = str(time.time_ns())
    common = [attribute("installation_id", state["installation_id"])]
    metrics = []

    def point(value: int | float, **labels: str) -> dict:
        return {"attributes": common + [attribute(k, v) for k, v in labels.items()],
                "timeUnixNano": now, "asDouble": value}

    def counter(name: str, points: list[dict]) -> None:
        for item in points:
            item["startTimeUnixNano"] = str(state["start_ns"])
        metrics.append({"name": name, "sum": {"aggregationTemporality": 2,
                                              "isMonotonic": True, "dataPoints": points}})

    def count(kind: str, **filters: str) -> int:
        return sum(row["amount"] for row in events if row["kind"] == kind
                   and all(row[key] == value for key, value in filters.items()))

    counter("agent_web_chats_created", [point(count("session.created"))])
    counter("agent_web_messages_sent", [point(count("turn.started", agent=a), agent=a) for a in AGENTS])
    counter("agent_web_turns_finished", [
        point(count(f"turn.{o}", agent=a), agent=a, outcome=o) for a in AGENTS for o in OUTCOMES
    ])
    counter("agent_web_errors", [point(count("turn.failed", category=c), category=c) for c in CATEGORIES])
    latest = max((row["latest"] or 0 for row in events
                  if row["kind"] in ("session.created", "turn.started")), default=0)
    for name, points in (
        ("agent_web_online", [point(1)]),
        ("agent_web_last_activity_timestamp_seconds", [point(latest)]),
        ("agent_web_build_info", [point(1, version=version("agent-web"))]),
    ):
        metrics.append({"name": name, "gauge": {"dataPoints": points}})
    buckets = [0] * (len(BOUNDS) + 1)
    for row in durations:
        buckets[row["bucket"]] = row["amount"]
    metrics.append({"name": "agent_web_turn_duration_seconds", "histogram": {
        "aggregationTemporality": 2,
        "dataPoints": [{"attributes": common, "timeUnixNano": now,
                        "startTimeUnixNano": str(state["start_ns"]),
                        "count": str(sum(buckets)), "sum": sum(row["seconds"] for row in durations),
                        "bucketCounts": [str(n) for n in buckets], "explicitBounds": list(BOUNDS)}],
    }})
    return {"resourceMetrics": [{"resource": {"attributes": [attribute("service.name", "agent-web")]},
                                 "scopeMetrics": [{"scope": {"name": "agent_web.telemetry"},
                                                   "metrics": metrics}]}]}


async def send_payload(client: httpx.AsyncClient, connection: Connection, payload: dict) -> bool:
    # Do not log URLs, credentials, response bodies or exception representations.
    try:
        response = await client.post(connection.endpoint, json=payload,
                                     auth=httpx.BasicAuth(connection.instance_id, connection.token))
        if not response.is_success:
            logger.warning("Telemetry delivery failed (HTTP %s); will retry", response.status_code)
            return False
        if response.content:
            result = response.json()
            partial = result.get("partialSuccess", {})
            if int(partial.get("rejectedDataPoints", 0)) or partial.get("errorMessage"):
                logger.warning("Telemetry receiver reported partial success; check Grafana ingestion")
                return False
        return True
    except Exception:
        logger.warning("Telemetry delivery failed; will retry")
        return False


async def run_telemetry(settings: Settings, session_factory) -> None:
    try:
        connection = Connection.from_config(settings.telemetry)
        if connection is None:
            return
        state = await load_state(settings.data_dir / "telemetry-state.json", session_factory)
    except Exception:
        logger.warning("Telemetry disabled: check configuration and telemetry-state.json")
        return
    # A single pending request, no unbounded queue; cancellation is handled by app lifespan.
    async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
        delay = 60
        while True:
            try:
                payload = await build_payload(state, session_factory)
                success = await send_payload(client, connection, payload)
            except Exception:
                logger.warning("Telemetry aggregation failed; will retry")
                success = False
            delay = 60 if success else min(delay * 2, 900)
            await asyncio.sleep(delay)
