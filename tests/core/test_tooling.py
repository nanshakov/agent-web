from agent_web.tooling import find_codex


def test_find_codex_returns_path_or_none():
    result = find_codex()
    assert result is None or result.name.lower() == "codex.exe"
