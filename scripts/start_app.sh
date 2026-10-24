#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python ]]; then
  echo 'Install first: uv sync --locked --extra dev --extra console' >&2
  exit 1
fi
.venv/bin/python -c 'import streamlit, plotly, httpx' || exit 1
export FULFILIQ_WRITE_TOKEN="${FULFILIQ_WRITE_TOKEN:-$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')}"
export FULFILIQ_API_URL="http://127.0.0.1:${FULFILIQ_API_PORT:-8000}"
api_pid=''
console_pid=''
cleanup() {
  [[ -z "$console_pid" ]] || kill "$console_pid" 2>/dev/null || true
  [[ -z "$api_pid" ]] || kill "$api_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM
.venv/bin/uvicorn fulfilliq.api.main:app --host 127.0.0.1 --port "${FULFILIQ_API_PORT:-8000}" &
api_pid=$!
# Wait for readiness, but permit a degraded database so the console can explain setup requirements.
.venv/bin/python - <<'PY'
import os, time, urllib.error, urllib.request
for _ in range(60):
    try:
        urllib.request.urlopen(os.environ['FULFILIQ_API_URL'] + '/health', timeout=1)
        break
    except urllib.error.HTTPError:
        break
    except (OSError, TimeoutError):
        time.sleep(.5)
else:
    raise SystemExit('Backend did not start. Check port availability and logs.')
PY
.venv/bin/streamlit run src/fulfilliq/console/app.py --server.address 127.0.0.1 \
  --server.port "${FULFILIQ_CONSOLE_PORT:-8501}" --server.headless true \
  --browser.gatherUsageStats false &
console_pid=$!
echo "Console: http://127.0.0.1:${FULFILIQ_CONSOLE_PORT:-8501} · Swagger: $FULFILIQ_API_URL/docs"
wait -n "$api_pid" "$console_pid" 2>/dev/null || {
  # macOS ships bash 3.2 without wait -n.
  while kill -0 "$api_pid" 2>/dev/null && kill -0 "$console_pid" 2>/dev/null; do sleep 1; done
}
