#!/usr/bin/env bash
# Qeonix Smart Licence Services: one-command local run (macOS / Linux).
# Needs Python 3.12+ and Node.js 20+. First run installs everything (a few minutes); later runs start in seconds.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing: $1. $2"; exit 1; }; }
PY="$(command -v python3.13 || command -v python3.12 || command -v python3 || true)"
[ -n "$PY" ] || { echo "Missing: Python 3.12 or newer (https://www.python.org/downloads/)"; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' || { echo "Python 3.12 or newer is required (found $("$PY" --version))."; exit 1; }
need node "Install Node.js 20 or newer from https://nodejs.org/"
need npm "Install Node.js 20 or newer from https://nodejs.org/"

if [ ! -x backend/.venv-local/bin/uvicorn ]; then
  echo "==> Installing the backend (first run only)"
  "$PY" -m venv backend/.venv-local
  backend/.venv-local/bin/python -m pip install --quiet --upgrade pip
  backend/.venv-local/bin/python -m pip install --quiet -e backend
fi

if [ ! -f frontend/dist/index.html ] || [ -n "$(find frontend/src frontend/index.html -newer frontend/dist/index.html -print -quit 2>/dev/null)" ]; then
  echo "==> Building the portal"
  (cd frontend && { [ -d node_modules ] || npm ci --no-audit --no-fund --loglevel=error; } && npx vite build --logLevel error)
fi

export QEONIX_SERVE_FRONTEND=true
export QEONIX_SEED_DEMO_ON_START=true
export QEONIX_FRONTEND_BASE_URL="http://localhost:${PORT}"
export QEONIX_UAEPASS_ISSUER="http://localhost:${PORT}/mock-uaepass"
export QEONIX_UAEPASS_REDIRECT_URI="http://localhost:${PORT}/api/auth/callback"

URL="http://localhost:${PORT}"
echo "==> Starting on ${URL}  (press Ctrl+C to stop)"
( sleep 4; command -v open >/dev/null && open "$URL" || command -v xdg-open >/dev/null && xdg-open "$URL" ) >/dev/null 2>&1 &
cd backend
exec .venv-local/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
