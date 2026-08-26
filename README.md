# Agent Web

Mobile-first LAN Web UI for local Codex sessions. The first build is Codex-only,
Chrome-only, and intended for a trusted home LAN.

## Development

```powershell
uv sync --extra dev
uv run agent-web init --root C:\Projects
uv run agent-web serve --allow-lan
uv run agent-web run-tests
```

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
