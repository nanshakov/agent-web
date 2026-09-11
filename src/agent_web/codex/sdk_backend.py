from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from agent_web.codex.base import Capabilities
from agent_web.activity import Activity, item_activity


class SdkCodexBackend:
    """Thin adapter around the documented Python SDK.

    Streaming and interrupt are intentionally capability-gated until the spike
    captures the exact notification contract of the pinned SDK version.
    """

    def __init__(self, session_logs_dir: Path | None = None) -> None:
        self._codex = None
        self._threads: dict[str, Any] = {}
        self._capabilities = Capabilities(streaming=True, activity=True, steer=False, interrupt=False)
        self._session_logs_dir = session_logs_dir or Path.home() / ".codex" / "sessions"

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities

    async def _client(self):
        if self._codex is None:
            from openai_codex import AsyncCodex  # type: ignore[import-not-found]

            self._codex = AsyncCodex()
            await self._codex.__aenter__()
        return self._codex

    async def health(self) -> tuple[bool, str]:
        try:
            await self._client()
        except Exception as error:  # SDK errors must leave diagnostics available.
            return False, str(error)
        return True, "ready"

    async def models(self) -> list[dict[str, object]]:
        """Return only model metadata safe to expose on the local UI."""
        response = await (await self._client()).models()
        catalog = []
        for item in response.data:
            efforts = [str(option.reasoning_effort.value) for option in item.supported_reasoning_efforts]
            catalog.append({
                "id": str(item.model),
                "name": str(item.display_name),
                "default": bool(item.is_default),
                "reasoning_efforts": efforts,
                "default_reasoning": str(item.default_reasoning_effort.value),
            })
        return catalog

    async def usage(self) -> dict[str, object]:
        """Read the current account rate-limit snapshot from Codex app-server."""
        from openai_codex.generated.v2_all import (  # type: ignore[import-not-found]
            GetAccountRateLimitsResponse,
        )

        codex = await self._client()
        response = await codex._client.request(
            "account/rateLimits/read", None, response_model=GetAccountRateLimitsResponse
        )
        limits = response.rate_limits

        def window(value):
            if value is None:
                return None
            return {
                "used_percent": value.used_percent,
                "remaining_percent": max(0, 100 - value.used_percent),
                "resets_at": value.resets_at,
                "window_duration_mins": value.window_duration_mins,
            }

        credits = limits.credits
        return {
            "available": True,
            "plan_type": limits.plan_type.value if limits.plan_type else None,
            "primary": window(limits.primary),
            "secondary": window(limits.secondary),
            "credits": None if credits is None else {
                "balance": credits.balance,
                "has_credits": credits.has_credits,
                "unlimited": credits.unlimited,
            },
        }

    async def start_thread(
        self, cwd: Path, *, model: str | None, sandbox: str, reasoning: str | None = None,
        approval_policy: str = "auto",
    ) -> str:
        from openai_codex import ApprovalMode, Sandbox  # type: ignore[import-not-found]

        codex = await self._client()
        kwargs = {
            "cwd": str(cwd), "sandbox": getattr(Sandbox, sandbox),
            "approval_mode": ApprovalMode.auto_review,
        }
        if model:
            kwargs["model"] = model
        if reasoning:
            kwargs["config"] = {"model_reasoning_effort": reasoning}
        thread = await codex.thread_start(**kwargs)
        native_id = str(thread.id)
        self._threads[native_id] = thread
        return native_id

    async def thread_history(self, native_thread_id: str) -> list[dict[str, str]]:
        # Codex Desktop appends its live transcript to the local session journal.
        # It is more current than thread/read while another desktop client owns
        # the thread writer lock, and reading it does not resume or lock a thread.
        journal_history = self._journal_history(native_thread_id)
        if journal_history:
            return journal_history
        codex = await self._client()
        # Keep the SDK path for sessions without a local Desktop journal.
        response = await codex._client.thread_read(native_thread_id, include_turns=True)
        messages: list[dict[str, str]] = []
        for turn in response.thread.turns:
            for item in turn.items:
                message = item.root
                if message.type == "agentMessage":
                    messages.append({"role": "assistant", "content": message.text})
                elif message.type == "userMessage":
                    text = "\n".join(
                        part.root.text for part in message.content
                        if getattr(part.root, "type", None) == "text"
                    )
                    if text:
                        messages.append({"role": "user", "content": text})
        return messages

    def _journal_history(self, native_thread_id: str) -> list[dict[str, str]]:
        """Read the newest complete local Desktop transcript for one thread.

        The journal is append-only, so a partially written final line is ignored.
        Only user and assistant text is returned; settings, tools, and developer
        instructions are deliberately never exposed through Agent Web.
        """
        if not native_thread_id.replace("-", "").isalnum() or not self._session_logs_dir.is_dir():
            return []
        try:
            candidates = list(self._session_logs_dir.rglob(f"*{native_thread_id}*.jsonl"))
            if not candidates:
                return []
            path = max(candidates, key=lambda item: item.stat().st_mtime_ns)
            messages: list[dict[str, str]] = []
            with path.open(encoding="utf-8") as journal:
                for line in journal:
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    payload = item.get("payload", {})
                    if item.get("type") != "response_item" or payload.get("type") != "message":
                        continue
                    role = payload.get("role")
                    if role not in {"user", "assistant"}:
                        continue
                    text = "\n".join(
                        part["text"] for part in payload.get("content", [])
                        if part.get("type") in {"input_text", "output_text"} and part.get("text")
                    )
                    if text:
                        messages.append({"role": role, "content": text})
            return messages
        except OSError:
            return []

    async def list_threads(self, limit: int = 100) -> list[dict[str, str | None]]:
        codex = await self._client()
        response = await codex.thread_list(limit=limit)
        return [
            {
                "id": str(thread.id),
                "cwd": str(thread.cwd.root) if thread.cwd else None,
                "title": str(thread.name) if thread.name else None,
            }
            for thread in response.data
        ]

    async def set_thread_title(self, native_thread_id: str, title: str) -> None:
        thread = self._threads.get(native_thread_id)
        if thread is not None:
            await thread.set_name(title)
            return
        codex = await self._client()
        await codex._client.thread_set_name(native_thread_id, title)

    async def run_turn(
        self, native_thread_id: str, prompt: str, *, sandbox: str,
        model: str | None = None, reasoning: str | None = None,
    ) -> str:
        from openai_codex import Sandbox  # type: ignore[import-not-found]
        from openai_codex.generated.v2_all import ReasoningEffort  # type: ignore[import-not-found]

        thread = self._threads.get(native_thread_id)
        if thread is None:
            codex = await self._client()
            thread = await codex.thread_resume(native_thread_id)
            self._threads[native_thread_id] = thread
        result = await thread.run(
            prompt,
            sandbox=getattr(Sandbox, sandbox),
            model=model,
            effort=ReasoningEffort(reasoning) if reasoning else None,
        )
        return result.final_response

    async def stream_turn(
        self, native_thread_id: str, prompt: str, *, sandbox: str,
        on_delta: Callable[[str], Awaitable[None]], model: str | None = None,
        reasoning: str | None = None,
        on_activity: Callable[[Activity], Awaitable[None]] | None = None,
    ) -> str:
        """Forward Codex agent-message deltas while collecting the final response."""
        from openai_codex import Sandbox  # type: ignore[import-not-found]
        from openai_codex.generated.v2_all import (  # type: ignore[import-not-found]
            AgentMessageDeltaNotification,
            AgentMessageThreadItem,
            ItemCompletedNotification,
            ItemStartedNotification,
            MessagePhase,
            ReasoningEffort,
            TurnCompletedNotification,
            TurnStatus,
        )

        thread = self._threads.get(native_thread_id)
        if thread is None:
            thread = await (await self._client()).thread_resume(native_thread_id)
            self._threads[native_thread_id] = thread
        handle = await thread.turn(
            prompt, sandbox=getattr(Sandbox, sandbox), model=model,
            effort=ReasoningEffort(reasoning) if reasoning else None,
        )
        final_response: str | None = None
        fallback_response: str | None = None
        async for event in handle.stream():
            payload = event.payload
            if on_activity is not None and isinstance(payload, (ItemStartedNotification, ItemCompletedNotification)):
                item = payload.item.root if hasattr(payload.item, "root") else payload.item
                activity = item_activity(item, completed=isinstance(payload, ItemCompletedNotification))
                if activity is not None:
                    await on_activity(activity)
            if isinstance(payload, AgentMessageDeltaNotification):
                await on_delta(payload.delta)
            elif isinstance(payload, ItemCompletedNotification):
                item = payload.item.root if hasattr(payload.item, "root") else payload.item
                if isinstance(item, AgentMessageThreadItem):
                    fallback_response = item.text
                    if item.phase == MessagePhase.final_answer:
                        final_response = item.text
            elif isinstance(payload, TurnCompletedNotification) and payload.turn.id == handle.id:
                if payload.turn.status == TurnStatus.failed:
                    message = payload.turn.error.message if payload.turn.error else "turn failed"
                    raise RuntimeError(message)
        return final_response or fallback_response or ""

    async def interrupt(self, native_thread_id: str) -> bool:
        thread = self._threads.get(native_thread_id)
        interrupt = getattr(thread, "interrupt", None)
        if interrupt is None:
            return False
        await interrupt()
        return True
