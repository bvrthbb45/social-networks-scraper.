#!/usr/bin/env bash
# Encrypted backup of the database and the evidence-media volume.
#   scripts/backup.sh [OUTPUT_DIR]        (default: ./backups, created with mode 700)
# The passphrase comes from .backup-passphrase. Encryption keys in .env are NOT included: keep them elsewhere.
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
out="${1:-backups}"
mkdir -p "$out"
chmod 700 "$out"
[ -r .backup-passphrase ] || { echo "missing .backup-passphrase (run scripts/gen-secrets.sh)" >&2; exit 1; }
set -a
# shellcheck source=/dev/null
. ./.env
set +a
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
enc() { openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt -pass file:.backup-passphrase; }

docker compose exec -T db pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" | enc > "$out/db-$stamp.dump.enc"
docker compose exec -T api tar -C /data -cf - media | enc > "$out/media-$stamp.tar.enc"
( cd "$out" && sha256sum "db-$stamp.dump.enc" "media-$stamp.tar.enc" > "SHA256-$stamp.txt" )
echo "backup written to $out (stamp $stamp)"
