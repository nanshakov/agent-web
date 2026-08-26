#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$ROOT/.venv/bin/python" -m agent_web.cli --data-dir "$ROOT/data" update apply --yes
exec "$ROOT/scripts/restart-agent-web.sh"
