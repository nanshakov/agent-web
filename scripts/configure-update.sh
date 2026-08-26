#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <repository-url> [branch]" >&2
  exit 2
fi

"$PYTHON" -m agent_web.cli --data-dir "$ROOT/data" configure-update \
  --repository-url "$1" --branch "${2:-main}"
