from __future__ import annotations

import asyncio
import json
import os
import shutil
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


OPEN_CODE_COMMAND = Path(
    shutil.which("opencode") or Path.home() / "AppData/Roaming/npm/opencode.cmd"
)
LMS_COMMAND = Path(shutil.which("lms") or "lms")


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
    model: str | None = None


class OpenCodeAcpBackend:
    """OpenCode transport implemented through ACP, never through CLI JSON output."""

    def __init__(self, command: Path | None = None, lms_command: Path | None = None) -> None:
        self.command = command or OPEN_CODE_COMMAND
        self.lms_command = lms_command or LMS_COMMAND
        self._sessions: dict[str, _Session] = {}
        self._known_cwds: dict[str, Path] = {}
        self._capabilities = Capabilities(streaming=False, steer=False, interrupt=True)

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities

    def register_thread(self, native_thread_id: str, cwd: Path) -> None:
        self._known_cwds[native_thread_id] = cwd

    @staticmethod
    def _command_exists(command: Path) -> bool:
        return command.exists() if command.is_absolute() else shutil.which(str(command)) is not None

    @staticmethod
    def _process_args(command: Path, *args: str) -> list[str]:
        if sys.platform == "win32" and command.suffix.lower() in {".cmd", ".bat"}:
            return ["cmd.exe", "/d", "/s", "/c", str(command), *args]
        return [str(command), *args]

    async def _run(self, command: Path, *args: str, timeout: float = 30) -> str:
        process = await asyncio.create_subprocess_exec(
            *self._process_args(command, *args),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError(f"Command timed out: {command.name}") from None
        output = stdout.decode("utf-8", errors="replace").strip()
        detail = stderr.decode("utf-8", errors="replace").strip() or output
        if process.returncode:
            raise RuntimeError(detail or f"Command failed: {command.name}")
        return output

    async def _config(self) -> dict[str, Any]:
        try:
            value = json.loads(await self._run(self.command, "debug", "config"))
        except (json.JSONDecodeError, RuntimeError) as exc:
            raise RuntimeError(f"Could not read OpenCode configuration: {exc}") from exc
        if not isinstance(value, dict):
            raise RuntimeError("OpenCode configuration is invalid")
        return value

    @staticmethod
    def _configured_models(config: dict[str, Any]) -> list[dict[str, object]]:
        provider = config.get("provider", {}).get("lm-studio", {})
        configured = provider.get("models", {}) if isinstance(provider, dict) else {}
        if not isinstance(configured, dict):
            return []
        default_model = config.get("model")
        result = []
        for model_id, item in configured.items():
            if not isinstance(item, dict):
                continue
            full_id = model_id if "/" in model_id and model_id.startswith("lm-studio/") \
                else f"lm-studio/{model_id}"
            limits = item.get("limit", {}) if isinstance(item.get("limit"), dict) else {}
            result.append({
                "id": full_id,
                "name": str(item.get("name") or model_id),
                "default": full_id == default_model,
                "reasoning_efforts": [],
                "default_reasoning": "",
                "context_length": limits.get("context"),
                "output_limit": limits.get("output"),
            })
        return result

    async def _model_settings(self, requested: str | None) -> tuple[str, dict[str, object]]:
        config = await self._config()
        models = self._configured_models(config)
        selected = requested or next(
            (str(item["id"]) for item in models if item["default"]), None
        )
        match = next((item for item in models if item["id"] == selected), None)
        if not selected or match is None:
            raise RuntimeError("No LM Studio model is configured in OpenCode")
        return selected, match

    async def _ensure_model_ready(self, requested: str | None) -> str:
        selected, settings = await self._model_settings(requested)
        try:
            status = await self._run(self.lms_command, "server", "status")
        except RuntimeError:
            status = ""
        if "running" not in status.lower():
            await self._run(
                self.lms_command, "server", "start", "--port", "1234", timeout=120
            )
        try:
            loaded = json.loads(await self._run(self.lms_command, "ps", "--json"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("LM Studio returned an invalid model list") from exc
        if not isinstance(loaded, list):
            raise RuntimeError("LM Studio returned an invalid model list")
        model_key = selected.removeprefix("lm-studio/")
        current = next(
            (item for item in loaded if item.get("identifier") == model_key), None
        )
        context = settings.get("context_length")
        if current is not None and (not context or current.get("contextLength") == context):
            return selected
        if current is not None:
            await self._run(self.lms_command, "unload", model_key, timeout=120)
        arguments = ["load", model_key, "--identifier", model_key]
        if context:
            arguments.extend(("--context-length", str(context)))
        arguments.append("--yes")
        await self._run(self.lms_command, *arguments, timeout=600)
        return selected

    async def health(self) -> tuple[bool, str]:
        if not self._command_exists(self.command):
            return False, f"OpenCode not found: {self.command}"
        if not self._command_exists(self.lms_command):
            return False, f"LM Studio CLI not found: {self.lms_command}"
        return True, "OpenCode ACP ready; LM Studio is selected by OpenCode configuration"

    async def models(self) -> list[dict[str, object]]:
        return self._configured_models(await self._config())

    async def usage(self) -> dict[str, object]:
        return {
            "available": True,
            "local": True,
            "message": "Local LM Studio model; no cloud limit applies.",
        }

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
        del reasoning, approval_policy
        selected = await self._ensure_model_ready(model)
        connection, session = await self._open(cwd, sandbox)
        try:
            response = await connection.new_session(cwd=str(cwd))
            await connection.set_config_option(
                session_id=response.session_id, config_id="model", value=selected
            )
        except Exception:
            await session.context.__aexit__(*sys.exc_info())
            raise
        native_id = f"opencode:{response.session_id}"
        session.model = selected
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

    async def run_turn(
        self, native_thread_id: str, prompt: str, *, sandbox: str,
        model: str | None = None, reasoning: str | None = None,
    ) -> str:
        del reasoning
        selected = await self._ensure_model_ready(model)
        session = await self._session(native_thread_id, sandbox)
        raw_id = native_thread_id.removeprefix("opencode:")
        if session.model != selected:
            await session.connection.set_config_option(
                session_id=raw_id, config_id="model", value=selected
            )
            session.model = selected
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
