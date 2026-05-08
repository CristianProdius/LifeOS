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

require_real_value() {
  local key="$1"
  local value="$2"
  case "$value" in
    ""|*change_me*|*replace_me*)
      die "$key must be set to a real value in $ENV_FILE"
      ;;
  esac
}

ENV_FILE="${ENV_FILE:-.env}"
[[ -f "$ENV_FILE" ]] || die "missing $ENV_FILE; copy .env.example to .env and fill real values"

command -v docker >/dev/null 2>&1 || die "docker is required"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"

postgres_db="${POSTGRES_DB:-$(env_value POSTGRES_DB "$ENV_FILE")}"
postgres_user="${POSTGRES_USER:-$(env_value POSTGRES_USER "$ENV_FILE")}"
postgres_password="${POSTGRES_PASSWORD:-$(env_value POSTGRES_PASSWORD "$ENV_FILE")}"
retention_days="${LIFEOS_BACKUP_RETENTION_DAYS:-$(env_value LIFEOS_BACKUP_RETENTION_DAYS "$ENV_FILE")}"
retention_days="${retention_days:-14}"

require_real_value POSTGRES_DB "$postgres_db"
require_real_value POSTGRES_USER "$postgres_user"
require_real_value POSTGRES_PASSWORD "$postgres_password"

mkdir -p backups
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
tmp_file="backups/.lifeos-${timestamp}.dump.tmp"
out_file="backups/lifeos-${timestamp}.dump"

cleanup() {
  rm -f "$tmp_file"
}
trap cleanup EXIT

docker compose --env-file "$ENV_FILE" up -d lifeos-db
docker compose --env-file "$ENV_FILE" exec -T \
  -e "PGPASSWORD=$postgres_password" \
  lifeos-db pg_dump -U "$postgres_user" -d "$postgres_db" -Fc > "$tmp_file"

mv "$tmp_file" "$out_file"
chmod 600 "$out_file"
trap - EXIT

find backups -type f -name 'lifeos-*.dump' -mtime "+$retention_days" -delete
printf 'Wrote %s\n' "$out_file"
