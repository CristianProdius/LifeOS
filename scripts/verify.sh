#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

ENV_FILE="${ENV_FILE:-.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  ENV_FILE=".env.example"
fi
[[ -f "$ENV_FILE" ]] || die "missing .env.example"

required_files=(
  .gitignore
  .env.example
  docker-compose.yml
  scripts/bootstrap.sh
  scripts/migrate.sh
  scripts/seed.sh
  scripts/backup.sh
  scripts/render-openclaw-config.sh
  scripts/verify.sh
)

for path in "${required_files[@]}"; do
  [[ -f "$path" ]] || die "missing $path"
done

for path in scripts/bootstrap.sh scripts/migrate.sh scripts/seed.sh scripts/backup.sh scripts/render-openclaw-config.sh scripts/verify.sh; do
  [[ -x "$path" ]] || die "$path is not executable"
done

bash -n scripts/bootstrap.sh scripts/migrate.sh scripts/seed.sh scripts/backup.sh scripts/render-openclaw-config.sh scripts/verify.sh

if LC_ALL=C grep -R -n '[^[:print:][:space:]]' .gitignore .env.example docker-compose.yml scripts; then
  die "non-ASCII or control characters detected"
fi

command -v docker >/dev/null 2>&1 || die "docker is required"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"
docker compose --env-file "$ENV_FILE" config --quiet

services="$(docker compose --env-file "$ENV_FILE" --profile backup config --services)"
for service in openclue-gateway lifeos-api lifeos-db lifeos-migrate lifeos-backup; do
  printf '%s\n' "$services" | grep -qx "$service" || die "missing compose service $service"
done

printf 'LifeOS infrastructure verification passed using %s.\n' "$ENV_FILE"
