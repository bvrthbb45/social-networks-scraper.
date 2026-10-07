#!/usr/bin/env bash
# Creates .env (mode 600) from .env.example with freshly generated secrets, plus a backup passphrase file.
# Refuses to overwrite anything: rotating keys is a deliberate act (see docs/deployment.md).
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
[ -e .env ] && { echo ".env already exists - not touching it" >&2; exit 1; }
[ -e .backup-passphrase ] && { echo ".backup-passphrase already exists - not touching it" >&2; exit 1; }

pw="$(openssl rand -hex 24)"
sed -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${pw}|" \
    -e "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+psycopg://opsec:${pw}@db:5432/opsec|" \
    -e "s|^ENVIRONMENT=.*|ENVIRONMENT=production|" \
    -e "s|^FIELD_ENCRYPTION_KEY=.*|FIELD_ENCRYPTION_KEY=$(openssl rand -base64 32)|" \
    -e "s|^BLIND_INDEX_KEY=.*|BLIND_INDEX_KEY=$(openssl rand -base64 32)|" \
    -e "s|^JWT_SECRET=.*|JWT_SECRET=$(openssl rand -base64 48 | tr -d '\n')|" \
    .env.example > .env
printf '%s\n' "REFRESH_COOKIE_PATH=/api/auth" >> .env
openssl rand -base64 36 > .backup-passphrase

echo "Created .env and .backup-passphrase (both private to this user)."
echo "IMPORTANT: copy FIELD_ENCRYPTION_KEY, BLIND_INDEX_KEY and .backup-passphrase to a safe place that is NOT"
echo "the same place as the database backups. Without them an encrypted backup cannot be read."
