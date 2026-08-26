#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$ROOT/data"
LOGS="$DATA/logs"
PYTHON="$ROOT/.venv/bin/python"
PORT="${AGENT_WEB_PORT:-8765}"

if [[ ! -x "$PYTHON" ]]; then
  echo "Python environment not found: $PYTHON. Run 'uv sync --extra dev' first." >&2
  exit 1
fi

if command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -ti "tcp:$PORT" -sTCP:LISTEN || true)"
  if [[ -n "$PIDS" ]]; then
    kill $PIDS
  fi
fi

mkdir -p "$LOGS"
nohup "$PYTHON" -m agent_web.cli --data-dir "$DATA" serve --allow-lan --port "$PORT" \
  >"$LOGS/agent-web.out.log" 2>"$LOGS/agent-web.err.log" < /dev/null &

for _ in $(seq 1 60); do
  if curl --fail --silent "http://localhost:$PORT/" >/dev/null; then
    echo "Agent Web is listening on port $PORT."
    exit 0
  fi
  sleep 1
done

echo "Agent Web did not become ready. Check $LOGS/agent-web.err.log" >&2
exit 1
