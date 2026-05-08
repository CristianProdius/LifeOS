#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

env_value() {
  local key="$1"
  local file="$2"
  awk -F= -v key="$key" '
    $0 ~ /^[[:space:]]*#/ { next }
    $1 == key {
      sub(/^[^=]*=/, "", $0)
      gsub(/^"/, "", $0)
      gsub(/"$/, "", $0)
      gsub(/^'\''/, "", $0)
      gsub(/'\''$/, "", $0)
      print
      exit
    }
  ' "$file"
}

ENV_FILE="${ENV_FILE:-.env}"
[[ -f "$ENV_FILE" ]] || die "missing $ENV_FILE; copy .env.example to .env and fill real values"

command -v docker >/dev/null 2>&1 || die "docker is required"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"

seed_command="${LIFEOS_SEED_COMMAND:-$(env_value LIFEOS_SEED_COMMAND "$ENV_FILE")}"
seed_command="${seed_command:-python -m lifeos_api.seed}"

docker compose --env-file "$ENV_FILE" up -d lifeos-db
docker compose --env-file "$ENV_FILE" run --rm --no-deps lifeos-api /bin/sh -lc "$seed_command"
