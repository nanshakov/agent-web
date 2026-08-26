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

    async def start_thread(self, cwd: Path, *, model: str | None, sandbox: str) -> str:
        from openai_codex import Sandbox  # type: ignore[import-not-found]

        codex = await self._client()
        kwargs = {"cwd": str(cwd), "sandbox": getattr(Sandbox, sandbox)}
        if model:
            kwargs["model"] = model
        thread = await codex.thread_start(**kwargs)
        native_id = str(thread.id)
        self._threads[native_id] = thread
        return native_id

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

    async def run_turn(self, native_thread_id: str, prompt: str, *, sandbox: str) -> str:
        from openai_codex import Sandbox  # type: ignore[import-not-found]

        thread = self._threads.get(native_thread_id)
        if thread is None:
            codex = await self._client()
            thread = await codex.thread_resume(native_thread_id)
            self._threads[native_thread_id] = thread
        result = await thread.run(prompt, sandbox=getattr(Sandbox, sandbox))
        return result.final_response

    async def interrupt(self, native_thread_id: str) -> bool:
        thread = self._threads.get(native_thread_id)
        interrupt = getattr(thread, "interrupt", None)
        if interrupt is None:
            return False
        await interrupt()
        return True
