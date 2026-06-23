#!/bin/bash
# Database backup script for ant-colony
set -e
BASE_DIR="${ANT_COLONY_HOME:-$(cd "$(dirname "$0")/.." && pwd)}"
BACKUP_DIR="${ANT_COLONY_BACKUP_DIR:-$BASE_DIR/data/backups}"
DB_PATH="${ANT_COLONY_DB_PATH:-$BASE_DIR/data/ant-colony.db}"
MAX_BACKUPS=7

mkdir -p "$BACKUP_DIR"
TS=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/ant-colony-$TS.db.gz"

sqlite3 "$DB_PATH" ".backup /tmp/ant-colony-backup.db" 2>/dev/null || cp "$DB_PATH" /tmp/ant-colony-backup.db
gzip -c /tmp/ant-colony-backup.db > "$BACKUP_FILE"
rm /tmp/ant-colony-backup.db
echo "Backup: $BACKUP_FILE ($(du -h $BACKUP_FILE | cut -f1))"

# Cleanup old
ls -t "$BACKUP_DIR"/ant-colony-*.db.gz | tail -n +$((MAX_BACKUPS+1)) | xargs -r rm
echo "Kept last $MAX_BACKUPS backups"
