#!/usr/bin/env bash
# Real API (PostgreSQL) + built web app + real Chromium: the whole reviewer workflow, end to end.
# Needs: TEST_PG_URL pointing at an EMPTY database, built web app (npm run build), backend deps, Chromium.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${TEST_PG_URL:?set TEST_PG_URL to an empty PostgreSQL database}"
TMP="$(mktemp -d)"
trap 'kill $(jobs -p) 2>/dev/null || true; rm -rf "$TMP"' EXIT
: "${CHROMIUM_PATH:=/opt/pw-browsers/chromium-1194/chrome-linux/chrome}"
[ -x "$CHROMIUM_PATH" ] && export CHROMIUM_PATH || unset CHROMIUM_PATH

export DATABASE_URL="$TEST_PG_URL" ENVIRONMENT=development MEDIA_DIR="$TMP/media" REFRESH_COOKIE_PATH=/api/auth
export JWT_SECRET="$(python3 -c 'print("j"*48)')"
export FIELD_ENCRYPTION_KEY="$(python3 -c 'import base64;print(base64.b64encode(b"k"*32).decode())')"
export BLIND_INDEX_KEY="$(python3 -c 'import base64;print(base64.b64encode(b"b"*32).decode())')"
export PYTHONPATH="$PWD/../backend" E2E_OUT="$TMP"

(cd ../backend && python3 -m alembic downgrade base >/dev/null 2>&1; python3 -m alembic upgrade head >/dev/null)
(cd ../backend && exec uvicorn app.main:app --port 8000 >"$TMP/api.log" 2>&1) &
npx vite preview --port 4173 >"$TMP/web.log" 2>&1 &
for _ in $(seq 1 60); do curl -fs localhost:4173/api/health >/dev/null 2>&1 && break; sleep 0.5; done
export ADMIN_INVITE="$(cd ../backend && python3 -m app.cli create-admin admin@example.org | tail -1)"
node e2e/review.mjs || { echo "--- api log ---"; tail -30 "$TMP/api.log"; exit 1; }
