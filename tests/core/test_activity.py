from types import SimpleNamespace

import pytest

from agent_web.codex.sdk_backend import SdkCodexBackend
from agent_web.activity import finish_activity, update_activity
from openai_codex.generated.v2_all import (
    AgentMessageDeltaNotification, ItemStartedNotification, ItemCompletedNotification,
    CommandExecutionThreadItem, FileChangeThreadItem, McpToolCallThreadItem,
)


@pytest.mark.asyncio
async def test_sdk_streams_tools_before_text_and_keeps_arguments_private():
    command = CommandExecutionThreadItem.model_construct(
        id="c1", type="commandExecution", command="secret command", status="inProgress")
    mcp = McpToolCallThreadItem.model_construct(
        id="m1", type="mcpToolCall", server="docs", tool="search", arguments={"secret": "value"}, status="inProgress")
    files = FileChangeThreadItem.model_construct(
        id="f1", type="fileChange", changes=["private diff"], status="completed")
    events = [
        ItemStartedNotification.model_construct(item=SimpleNamespace(root=command)),
        ItemStartedNotification.model_construct(item=SimpleNamespace(root=mcp)),
        ItemCompletedNotification.model_construct(item=SimpleNamespace(root=command.model_copy(update={"status": "completed", "exit_code": 1}))),
        ItemCompletedNotification.model_construct(item=SimpleNamespace(root=files)),
        AgentMessageDeltaNotification.model_construct(delta="text"),
    ]
    class Handle:
        id = "turn"
        async def stream(self):
            for payload in events:
                yield SimpleNamespace(payload=payload)
    class Thread:
        async def turn(self, *args, **kwargs):
            return Handle()
    backend = SdkCodexBackend()
    backend._threads["thread"] = Thread()
    received = []
    async def collect(value):
        received.append(value)
    await backend.stream_turn("thread", "prompt", sandbox="read_only", on_delta=collect, on_activity=collect)
    assert [item["status"] for item in received[:-1]] == ["running", "running", "failed", "completed"]
    assert received[-1] == "text"
    assert received[1]["label"] == "MCP · docs / search"
    assert received[3]["label"] == "File changes · 1 files"
    assert "secret" not in str(received) and "private diff" not in str(received)


def test_activity_snapshot_is_bounded_immutable_and_does_not_invent_success():
    items = []
    for index in range(102):
        items = update_activity(items, {"id": str(index), "kind": "commandExecution", "label": "Command", "status": "running"})
    assert len(items) == 100
    updated = update_activity(items, dict(items[-1], status="completed"))
    assert items[-1]["status"] == "running"
    assert len(updated) == 100
    finished = finish_activity(updated)
    assert finished[-1]["status"] == "completed"
    assert finished[0]["status"] == "interrupted"
