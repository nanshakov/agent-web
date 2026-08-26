from pathlib import Path

from agent_web.config import read_config, write_config


def test_config_preserves_update_source(tmp_path: Path):
    write_config(tmp_path, {"roots": ["F:/projects"], "update_repository_url": "https://example.test/agent-web.git", "update_branch": "main"})
    assert read_config(tmp_path)["update_repository_url"] == "https://example.test/agent-web.git"
