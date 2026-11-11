#!/usr/bin/env bash
# Wipe the public demo and seed it again.
#
# The seed data is anchored to today's date, so a demo left alone goes stale;
# and the demo account is writable, so anything a visitor changed (including
# its password) or synced from their own phone stays until the next reset.
# Run this once to bring the demo up, then nightly from the systemd timer.
set -euo pipefail

repo="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo"

env_file="deploy/demo/.env"
if [[ ! -f "$env_file" ]]; then
  echo "error: $env_file not found — copy deploy/demo/.env.example and fill it in" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
. "$env_file"
set +a

: "${DEMO_ADMIN_PASSWORD:?set DEMO_ADMIN_PASSWORD in $env_file}"
: "${DEMO_ATHLETE_PASSWORD:?set DEMO_ATHLETE_PASSWORD in $env_file}"
port="${DEMO_API_PORT:-8011}"

compose=(docker compose --env-file "$env_file"
  -f docker-compose.demo.yml -f deploy/demo/docker-compose.public.yml)

# A registry hiccup must not leave the demo stale: reset with the images
# already on the host and pick up the new one tomorrow.
"${compose[@]}" pull --quiet || echo "warning: image pull failed, reusing local images" >&2
"${compose[@]}" down --volumes
"${compose[@]}" up --detach --no-build

echo "waiting for the API…"
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${port}/api/health" 2>/dev/null | grep -q '"database": *"ok"'; then
    ready=1
    break
  fi
  sleep 2
done
if [[ -z "${ready:-}" ]]; then
  echo "error: API did not become healthy on 127.0.0.1:${port}" >&2
  "${compose[@]}" logs --tail 40 app >&2
  exit 1
fi

python3 scripts/seed_demo.py \
  --url "http://127.0.0.1:${port}" \
  --admin-password "$DEMO_ADMIN_PASSWORD" \
  --athlete-username "${DEMO_ATHLETE_USERNAME:-sofia}" \
  --athlete-password "$DEMO_ATHLETE_PASSWORD" \
  >/dev/null

echo "demo reset and seeded: $(curl -fsS "http://127.0.0.1:${port}/api/health")"
