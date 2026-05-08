#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

ENV_FILE="${ENV_FILE:-.env}"
[[ -f "$ENV_FILE" ]] || die "missing $ENV_FILE; copy .env.example to .env and fill real values"

command -v docker >/dev/null 2>&1 || die "docker is required"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"

docker compose --env-file "$ENV_FILE" up -d lifeos-db
docker compose --env-file "$ENV_FILE" run --rm lifeos-migrate
