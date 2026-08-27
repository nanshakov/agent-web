"""Manual local verification for OpenCode ACP + LM Studio."""

import asyncio
from pathlib import Path

from agent_web.opencode_acp import OpenCodeAcpBackend


async def main() -> None:
    backend = OpenCodeAcpBackend()
    print(await backend.health())
    session_id = await backend.start_thread(Path.cwd(), model=None, sandbox="read_only")
    print(session_id)
    print(await backend.run_turn(
        session_id, "Reply with exactly: OpenCode ACP ready. Do not use tools.", sandbox="read_only"
    ))


asyncio.run(main())
