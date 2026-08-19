#!/usr/bin/env bash
# torrentmore — self-contained setup
#   • creates venv + installs deps
#   • provisions tpb.sqlite (extract local .7z, OR download via aria2 torrent/magnet)
#   • (re)builds the FTS5 search index
#   • prints timing for each step
#
# Usage:
#   ./setup.sh                 # use local *.7z if present, else require MAGNET
#   MAGNET='magnet:?xt=...' ./setup.sh   # download via aria2c (brew install aria2)
set -euo pipefail
cd "$(dirname "$0")"

DB="tpb.sqlite"
AUDIO_DB="audiobooks.sqlite"
ARCHIVE="${ARCHIVE:-$(ls *.7z 2>/dev/null | head -1 || true)}"
MAGNET="${MAGNET:-$(cat db.magnet 2>/dev/null || true)}"

ts() { date +%s; }
fmt() { # seconds -> human
  local t=$1
  printf '%dh%02dm%02ds' $((t/3600)) $(((t%3600)/60)) $((t%60))
}

echo "== torrentmore setup =="

# 0) online tooling — aria2 lets setup pull the DB dump via torrent
if ! command -v aria2c >/dev/null 2>&1; then
  echo "[0/4] installing aria2 (torrent downloader)..."
  if command -v brew >/dev/null 2>&1; then
    brew install aria2
  elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y aria2
  else
    echo "      ! install aria2 yourself (brew install aria2)" >&2
  fi
fi

# 1) venv + deps
if [ ! -x venv/bin/python ]; then
  echo "[1/4] creating python venv..."
  python3 -m venv venv
fi
echo "[1/4] installing dependencies..."
./venv/bin/pip install -q -r requirements.txt

# 2) audiobooks db (tiny app data)
if [ ! -f "$AUDIO_DB" ]; then
  echo "[2/4] audiobooks.sqlite missing — creating empty db"
  sqlite3 "$AUDIO_DB" "VACUUM;"
fi

# 3) provision tpb.sqlite
if [ -f "$DB" ]; then
  echo "[3/4] $DB already present ($(du -h "$DB" | cut -f1)) — skipping fetch"
else
  if [ -n "$ARCHIVE" ] && [ -f "$ARCHIVE" ]; then
    echo "[3/4] extracting $ARCHIVE -> $DB ..."
    local_s=0
    local_s=$(ts)
    7z x -y -so "$ARCHIVE" > "$DB"
    echo "      extracted in $(fmt $(( $(ts) - local_s ))) → $(du -h "$DB" | cut -f1)"
  elif command -v aria2c >/dev/null 2>&1 && [ -n "$MAGNET" ]; then
    echo "[3/4] downloading via aria2c (magnet)..."
    local_s=$(ts)
    aria2c --seed-time=0 --console-log-level=warn -d . -o "downloaded.7z" "$MAGNET"
    echo "      downloaded in $(fmt $(( $(ts) - local_s )))"
    7z x -y -so downloaded.7z > "$DB"
    rm -f downloaded.7z
  else
    echo "[3/4] ERROR: no $DB, no local .7z, and no aria2/magnet."
    echo "       do one of:"
    echo "         • place the TPB dump .7z in this folder, or"
    echo "         • brew install aria2 && MAGNET='magnet:?xt=...' ./setup.sh"
    exit 1
  fi
fi

# 4) FTS5 index
echo "[4/4] (re)building FTS5 search index..."
local_s=$(ts)
sqlite3 "$DB" < fts5_migration_v2.sql
echo "      FTS built in $(fmt $(( $(ts) - local_s )))"

echo
echo "== done. run: ./serve.sh   (serves on http://localhost:3000)"
