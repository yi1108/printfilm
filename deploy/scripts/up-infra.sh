#!/usr/bin/env bash
# Start Postgres + Redis only
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="$ROOT/deploy/.env.prod"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Copy deploy/.env.prod.example → deploy/.env.prod first"
  exit 1
fi
docker compose -f "$ROOT/deploy/docker-compose.yml" --env-file "$ENV_FILE" up -d
docker compose -f "$ROOT/deploy/docker-compose.yml" --env-file "$ENV_FILE" ps
