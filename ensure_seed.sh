#!/usr/bin/env bash
# waits for the DB download to complete, then seeds it (be our own seeder)
set -uo pipefail
cd "$(dirname "$0")"
DL_DIR="$(pwd)/tmp-dl"
MAG="$(cat db.magnet)"
ARCHIVE="$DL_DIR/The Pirate Bay & YTS - Full Database Backup -  2024-06-01.sqlite.7z"
echo "[seed] watching for completed download in $DL_DIR"
for i in $(seq 1 200); do
  if [ -f "$ARCHIVE" ] && [ ! -f "$ARCHIVE.aria2" ]; then
    echo "[seed] download complete — starting seeder"
    exec aria2c --seed-time=0 --enable-rpc --rpc-listen-port=6801 \
      --dir="$DL_DIR" "$MAG"
  fi
  sleep 10
done
echo "[seed] gave up waiting (200 tries)"
