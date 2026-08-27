"""Read-only Cline ACP compatibility check; does not create a session or send a prompt."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path

import acp
from acp.schema import Implementation


class ProbeClient:
    async def session_update(self, session_id, update, **kwargs) -> None:
        pass

    async def request_permission(self, session_id, tool_call, options, **kwargs):
        return acp.RequestPermissionResponse(selected_option_id=options[0].option_id)


async def main() -> None:
    executable = shutil.which("cline")
    if executable is None and sys.platform == "win32":
        candidate = Path(os.environ.get("APPDATA", "")) / "npm" / "cline.cmd"
        executable = str(candidate) if candidate.exists() else None
    if executable is None:
        raise SystemExit("Cline CLI not found in PATH. Install it with: npm install --global cline")
    async with acp.spawn_agent_process(ProbeClient(), executable, "--acp") as (connection, _process):
        response = await connection.initialize(
            acp.PROTOCOL_VERSION,
            client_info=Implementation(name="Agent Web", version="0.1.0"),
        )
    print(f"ACP ready: {response.agent_info.name} {response.agent_info.version}")


if __name__ == "__main__":
    asyncio.run(main())
