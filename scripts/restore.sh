#!/usr/bin/env bash
# Restores a backup made by backup.sh into the RUNNING stack. Replaces the current database and media.
#   scripts/restore.sh BACKUPS_DIR STAMP
set -euo pipefail
cd "$(dirname "$0")/.."
dir="${1:?backups directory}"; stamp="${2:?stamp, e.g. 20261007T030000Z}"
[ -r .backup-passphrase ] || { echo "missing .backup-passphrase" >&2; exit 1; }
( cd "$dir" && sha256sum -c "SHA256-$stamp.txt" )
echo "This REPLACES the current database and evidence files with the backup from $stamp."
read -r -p 'Type RESTORE to continue: ' answer
[ "$answer" = "RESTORE" ] || { echo "cancelled"; exit 1; }
# shellcheck source=/dev/null
set -a; . ./.env; set +a
dec() { openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -pass file:.backup-passphrase; }

docker compose stop api daily proxy
dec < "$dir/db-$stamp.dump.enc" | docker compose exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner
docker compose run --rm --no-deps -T --entrypoint sh api -c 'rm -rf /data/media/* ' || true
dec < "$dir/media-$stamp.tar.enc" | docker compose run --rm --no-deps -T --entrypoint tar api -C /data -xf -
docker compose up -d
echo "restored from $stamp"
