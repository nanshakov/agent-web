import json
from pathlib import Path

from agent_web.opencode_acp import OpenCodeAcpBackend


class RecordingOpenCode(OpenCodeAcpBackend):
    def __init__(self):
        super().__init__(Path("opencode"), Path("lms"))
        self.commands: list[tuple[str, ...]] = []

    async def _run(self, command: Path, *args: str, timeout: float = 30) -> str:
        del timeout
        self.commands.append((command.name, *args))
        if args == ("debug", "config"):
            return json.dumps({
                "model": "lm-studio/local-model",
                "provider": {
                    "lm-studio": {
                        "models": {
                            "local-model": {
                                "name": "Local Model",
                                "limit": {"context": 45_056, "output": 8_192},
                            }
                        }
                    }
                },
            })
        if args == ("server", "status"):
            return "The server is stopped."
        if args == ("ps", "--json"):
            return "[]"
        return ""


async def test_opencode_models_and_lm_studio_launch_use_current_config():
    backend = RecordingOpenCode()

    models = await backend.models()
    selected = await backend._ensure_model_ready("lm-studio/local-model")

    assert models == [{
        "id": "lm-studio/local-model",
        "name": "Local Model",
        "default": True,
        "reasoning_efforts": [],
        "default_reasoning": "",
        "context_length": 45_056,
        "output_limit": 8_192,
    }]
    assert selected == "lm-studio/local-model"
    assert ("lms", "server", "start", "--port", "1234") in backend.commands
    assert (
        "lms", "load", "local-model", "--identifier", "local-model",
        "--context-length", "45056", "--yes",
    ) in backend.commands
