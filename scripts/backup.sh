#!/usr/bin/env bash
# Backup simple (MVP SQLite): copia consistente de la BD + originales de proyectos. Programar diario (cron / Task Scheduler).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$ROOT/backups}/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$DEST"
if command -v sqlite3 >/dev/null; then sqlite3 "$ROOT/data/tsq.db" ".backup '$DEST/tsq.db'"; else cp "$ROOT/data/tsq.db" "$DEST/tsq.db"; fi
tar -czf "$DEST/projects.tgz" -C "$ROOT/data" projects
cp -r "$ROOT/rules" "$DEST/rules"
echo "Backup en $DEST"
