from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Capabilities:
    streaming: bool = False
    steer: bool = False
    interrupt: bool = False
    sandboxes: tuple[str, ...] = ("read_only", "workspace_write", "full_access")


class CodexBackend(Protocol):
    @property
    def capabilities(self) -> Capabilities: ...

    async def health(self) -> tuple[bool, str]: ...

    async def models(self) -> list[dict[str, object]]: ...

    async def start_thread(
        self, cwd: Path, *, model: str | None, sandbox: str, reasoning: str | None = None
    ) -> str: ...

    async def list_threads(self, limit: int = 100) -> list[dict[str, str | None]]: ...

    async def run_turn(self, native_thread_id: str, prompt: str, *, sandbox: str) -> str: ...

    async def interrupt(self, native_thread_id: str) -> bool: ...


class UnavailableCodexBackend:
    def __init__(self, reason: str = "Codex backend is not configured") -> None:
        self.reason = reason
        self._capabilities = Capabilities()

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities

    async def health(self) -> tuple[bool, str]:
        return False, self.reason

    async def models(self) -> list[dict[str, object]]:
        return []

    async def start_thread(
        self, cwd: Path, *, model: str | None, sandbox: str, reasoning: str | None = None
    ) -> str:
        raise RuntimeError(self.reason)

    async def list_threads(self, limit: int = 100) -> list[dict[str, str | None]]:
        return []

    async def run_turn(self, native_thread_id: str, prompt: str, *, sandbox: str) -> str:
        raise RuntimeError(self.reason)

    async def interrupt(self, native_thread_id: str) -> bool:
        return False
