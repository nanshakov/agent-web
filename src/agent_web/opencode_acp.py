from __future__ import annotations

import asyncio
import os
import sys
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import acp
from acp.schema import (
    AllowedOutcome,
    ClientCapabilities,
    Implementation,
    RequestPermissionResponse,
)

from agent_web.codex.base import Capabilities


OPEN_CODE_COMMAND = Path.home() / "AppData/Roaming/npm/opencode.cmd"


def _permissions(sandbox: str) -> str:
    """Keep the ACP process scoped to its project working directory."""
    permissions: dict[str, Any] = {"*": "allow", "external_directory": "deny"}
    if sandbox == "read_only":
        permissions.update({"edit": "deny", "bash": "deny", "task": "deny"})
    return __import__("json").dumps({"permission": permissions})


class _OpenCodeClient:
    def __init__(self) -> None:
        self.messages: dict[str, list[dict[str, str]]] = {}

    async def session_update(self, session_id: str, update: Any, **_: Any) -> None:
        content = getattr(update, "content", None)
        if getattr(content, "type", None) != "text":
            return
        role = "assistant" if update.session_update == "agent_message_chunk" else "user"
        self.messages.setdefault(session_id, []).append({"role": role, "content": content.text})

    async def request_permission(self, session_id: str, tool_call: Any, options: list[Any], **_: Any):
        # The process receives explicit deny rules for external paths and read-only
        # sessions.  For permitted project work, choose its first allow option.
        allowed = next((item for item in options if item.kind.startswith("allow")), None)
        if allowed is None:
            from acp.schema import DeniedOutcome
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        return RequestPermissionResponse(outcome=AllowedOutcome(option_id=allowed.option_id))


@dataclass
class _Session:
    context: AbstractAsyncContextManager
    connection: Any
    process: asyncio.subprocess.Process
    cwd: Path
    client: _OpenCodeClient
    sandbox: str


class OpenCodeAcpBackend:
    """OpenCode transport implemented through ACP, never through CLI JSON output."""

    def __init__(self, command: Path | None = None) -> None:
        self.command = command or OPEN_CODE_COMMAND
        self._sessions: dict[str, _Session] = {}
        self._known_cwds: dict[str, Path] = {}
        self._capabilities = Capabilities(streaming=False, steer=False, interrupt=True)

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities

    def register_thread(self, native_thread_id: str, cwd: Path) -> None:
        self._known_cwds[native_thread_id] = cwd

    async def health(self) -> tuple[bool, str]:
        if sys.platform == "win32" and not self.command.exists():
            return False, f"OpenCode not found: {self.command}"
        return True, "OpenCode ACP ready; LM Studio is selected by OpenCode configuration"

    async def models(self) -> list[dict[str, object]]:
        return [{"id": "lm-studio/qwen/qwen3.8-27b", "name": "Qwen 3.8 27B (LM Studio)",
                 "default": True, "reasoning_efforts": [], "default_reasoning": ""}]

    async def _open(self, cwd: Path, sandbox: str) -> tuple[Any, _Session]:
        client = _OpenCodeClient()
        environment = dict(os.environ)
        environment["OPENCODE_CONFIG_CONTENT"] = _permissions(sandbox)
        if sys.platform == "win32":
            context = acp.spawn_agent_process(
                client, "cmd.exe", "/c", str(self.command), "acp", cwd=cwd, env=environment
            )
        else:
            context = acp.spawn_agent_process(client, "opencode", "acp", cwd=cwd, env=environment)
        connection, process = await context.__aenter__()
        await connection.initialize(
            protocol_version=acp.PROTOCOL_VERSION,
            client_capabilities=ClientCapabilities(),
            client_info=Implementation(name="Agent Web", version="0.1.0"),
        )
        return connection, _Session(context, connection, process, cwd, client, sandbox)

    async def start_thread(self, cwd: Path, *, model: str | None, sandbox: str,
                           reasoning: str | None = None, approval_policy: str = "auto") -> str:
        del model, reasoning, approval_policy
        connection, session = await self._open(cwd, sandbox)
        response = await connection.new_session(cwd=str(cwd))
        native_id = f"opencode:{response.session_id}"
        self._sessions[native_id] = session
        self._known_cwds[native_id] = cwd
        return native_id

    async def _session(self, native_thread_id: str, sandbox: str) -> _Session:
        existing = self._sessions.get(native_thread_id)
        if existing is not None and existing.sandbox == sandbox:
            return existing
        if existing is not None:
            await existing.context.__aexit__(None, None, None)
            self._sessions.pop(native_thread_id, None)
        cwd = self._known_cwds.get(native_thread_id)
        if cwd is None:
            raise RuntimeError("OpenCode session must be opened from its configured project")
        connection, session = await self._open(cwd, sandbox)
        raw_id = native_thread_id.removeprefix("opencode:")
        await connection.load_session(cwd=str(cwd), session_id=raw_id)
        self._sessions[native_thread_id] = session
        return session

    async def thread_history(self, native_thread_id: str) -> list[dict[str, str]]:
        session = await self._session(native_thread_id, "workspace_write")
        return session.client.messages.get(native_thread_id.removeprefix("opencode:"), [])

    async def list_threads(self, limit: int = 100) -> list[dict[str, str | None]]:
        return []

    async def run_turn(self, native_thread_id: str, prompt: str, *, sandbox: str) -> str:
        session = await self._session(native_thread_id, sandbox)
        raw_id = native_thread_id.removeprefix("opencode:")
        before = len(session.client.messages.get(raw_id, []))
        await session.connection.prompt(session_id=raw_id, prompt=[acp.text_block(prompt)])
        updates = session.client.messages.get(raw_id, [])[before:]
        answer = "".join(item["content"] for item in updates if item["role"] == "assistant")
        return answer or "OpenCode completed the turn without a text response."

    async def interrupt(self, native_thread_id: str) -> bool:
        session = self._sessions.get(native_thread_id)
        if session is None:
            return False
        await session.connection.cancel(native_thread_id.removeprefix("opencode:"))
        return True
