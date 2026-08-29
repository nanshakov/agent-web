from __future__ import annotations

from pathlib import Path

from agent_web.codex.base import Capabilities


class SdkCodexBackend:
    """Thin adapter around the documented Python SDK.

    Streaming and interrupt are intentionally capability-gated until the spike
    captures the exact notification contract of the pinned SDK version.
    """

    def __init__(self) -> None:
        self._codex = None
        self._threads: dict[str, object] = {}
        self._capabilities = Capabilities(streaming=False, steer=False, interrupt=False)

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
        codex = await self._client()
        # Reading through the app-server client deliberately avoids resuming a
        # thread: another Codex client can be actively writing to it.
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

    async def interrupt(self, native_thread_id: str) -> bool:
        thread = self._threads.get(native_thread_id)
        interrupt = getattr(thread, "interrupt", None)
        if interrupt is None:
            return False
        await interrupt()
        return True
