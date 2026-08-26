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

## Safety status

Authentication, CSRF, WebSocket origin checks, clickjacking protection, CSP, and
DNS-rebinding protection are deliberate technical debt for the LAN-only prototype.
Do not enable port forwarding or public ingress.

