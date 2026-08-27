# Cline ACP findings

Checked on Windows, 27 August 2026.

- Cline CLI 3.0.60 is installed from the official `cline` npm package.
- `cline --acp` starts successfully over stdio.
- `agent-client-protocol` 0.12.1 successfully initialized ACP with Cline.
- Cline reported agent name `cline`, version `3.0.60`, and session capabilities.
- A new ACP session correctly requires Cline authentication before it can start.

Run the repeatable check after Cline updates:

```powershell
uv run python spike/cline_acp_test.py
```

The check does not create a session, send a prompt, or change a project.
