# Agent Web

Mobile-first LAN Web UI for local Codex and OpenCode sessions. OpenCode is connected
through ACP and can use a local LM Studio model without a cloud account.
Chrome-only, and intended for a trusted home LAN.

## Development

```powershell
uv sync --extra dev
uv run agent-web init --root C:\Projects
uv run agent-web serve --allow-lan
uv run agent-web run-tests
```

## OpenCode + LM Studio

On Windows, install OpenCode globally, start the LM Studio local server on
`http://127.0.0.1:1234/v1`, then select **OpenCode · LM Studio** in a project's
Agent settings. Agent Web starts `opencode acp`, not the CLI JSON mode. The
user-level OpenCode configuration is `~/.config/opencode/opencode.json` and is
set to `lm-studio/qwen/qwen3.8-27b` on this machine.

Read-only chats deny edits, shell commands, and subagents. Workspace-write
chats deny paths outside the project's working directory while allowing
autonomous work inside it.

## Continuing with another agent

A visible chat can contain several internal agent segments. In an open chat,
choose an agent, model, reasoning level, and access mode, then use **Switch for
next message**. The next message carries the previous Agent Web history to the
new agent while the old segment remains visible. The chat panel can export the
portable history as `context.json` or `context.md`.

The server binds to `127.0.0.1` by default. `--allow-lan` binds it to `0.0.0.0`.
Without application authentication, never expose it outside a trusted LAN.

## Updates

Windows:

```powershell
.\scripts\configure-update.ps1 -RepositoryUrl "https://github.com/account/agent-web.git"
.\scripts\check-update.ps1
.\scripts\apply-update.ps1
```

macOS:

```bash
./scripts/configure-update.sh https://github.com/account/agent-web.git
./scripts/check-update.sh
./scripts/apply-update.sh
```

## Safety status

Authentication, CSRF, WebSocket origin checks, clickjacking protection, CSP, and
DNS-rebinding protection are deliberate technical debt for the LAN-only prototype.
Do not enable port forwarding or public ingress.
