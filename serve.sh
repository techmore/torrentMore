#!/usr/bin/env bash
# torrentmore — run the server (default port 3000)
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x venv/bin/python ]; then
  echo "no venv — run ./setup.sh first" >&2
  exit 1
fi
PORT="${PORT:-3000}"
exec ./venv/bin/python app.py
