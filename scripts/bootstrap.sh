#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
Usage: scripts/bootstrap.sh [--prepare-only]

Creates local runtime directories, creates .env from .env.example when needed,
checks placeholder secrets, and starts the Docker Compose stack.
USAGE
}

env_value() {
  local key="$1"
  local file="${2:-.env}"
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
  local value
  value="$(env_value "$key" .env)"
  case "$value" in
    ""|*change_me*|*replace_me*)
      die "$key must be set to a real value in .env"
      ;;
  esac
}

validate_numeric_id() {
  local key="$1"
  local value
  value="$(env_value "$key" .env)"
  [[ "$value" =~ ^-?[0-9]+$ ]] || die "$key must be a numeric Telegram id in .env"
}

validate_database_url() {
  python3 - .env <<'PY'
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

env_path = Path(sys.argv[1])
values = {}
for line in env_path.read_text(encoding="utf-8").splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        continue
    key, value = stripped.split("=", 1)
    value = value.strip().strip('"').strip("'")
    values[key.strip()] = value

url = values.get("DATABASE_URL", "")
parts = urlsplit(url)
expected = {
    "username": values.get("POSTGRES_USER", "lifeos"),
    "password": values.get("POSTGRES_PASSWORD", ""),
    "hostname": "lifeos-db",
    "path": "/" + values.get("POSTGRES_DB", "lifeos"),
}

problems = []
if parts.username != expected["username"]:
    problems.append("POSTGRES_USER does not match DATABASE_URL username")
if unquote(parts.password or "") != expected["password"]:
    problems.append("POSTGRES_PASSWORD does not match DATABASE_URL password")
if parts.hostname != expected["hostname"]:
    problems.append("DATABASE_URL host must be lifeos-db for Docker Compose")
if parts.path != expected["path"]:
    problems.append("POSTGRES_DB does not match DATABASE_URL database name")

if problems:
    print("error: " + "; ".join(problems), file=sys.stderr)
    raise SystemExit(1)
PY
}

prepare_only=0
case "${1:-}" in
  "")
    ;;
  --prepare-only)
    prepare_only=1
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

command -v docker >/dev/null 2>&1 || die "docker is required"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"

mkdir -p openclaw/config openclaw/workspace backups

if [[ ! -f .env ]]; then
  [[ -f .env.example ]] || die ".env.example is missing"
  cp .env.example .env
  chmod 600 .env
  cat <<'MESSAGE'
Created .env from .env.example.
Edit .env with real Telegram, gateway, and database secrets, then rerun bootstrap.
MESSAGE
  exit 0
fi

require_real_value OPENCLAW_GATEWAY_TOKEN
require_real_value TELEGRAM_BOT_TOKEN
require_real_value POSTGRES_PASSWORD
require_real_value DATABASE_URL
require_real_value LIFEOS_API_TOKEN
require_real_value TELEGRAM_ALLOWED_USER_ID
require_real_value TELEGRAM_ALLOWED_GROUP_ID
require_real_value TELEGRAM_TOPIC_DAILY_ID
require_real_value TELEGRAM_TOPIC_SPORT_ID
require_real_value TELEGRAM_TOPIC_BUSINESS_ID
require_real_value TELEGRAM_TOPIC_FINANCE_ID
require_real_value TELEGRAM_TOPIC_FOOD_ID
require_real_value TELEGRAM_TOPIC_REVIEW_ID
require_real_value TELEGRAM_TOPIC_ADMIN_ID
validate_numeric_id TELEGRAM_ALLOWED_USER_ID
validate_numeric_id TELEGRAM_ALLOWED_GROUP_ID
validate_numeric_id TELEGRAM_TOPIC_DAILY_ID
validate_numeric_id TELEGRAM_TOPIC_SPORT_ID
validate_numeric_id TELEGRAM_TOPIC_BUSINESS_ID
validate_numeric_id TELEGRAM_TOPIC_FINANCE_ID
validate_numeric_id TELEGRAM_TOPIC_FOOD_ID
validate_numeric_id TELEGRAM_TOPIC_REVIEW_ID
validate_numeric_id TELEGRAM_TOPIC_ADMIN_ID
validate_database_url

scripts/render-openclaw-config.sh

if [[ "$(uname -s)" == "Linux" && "$(id -u)" -eq 0 ]]; then
  chown 1000:1000 openclaw openclaw/config openclaw/workspace
  chown -R 1000:1000 openclaw/config openclaw/workspace
fi

if [[ "$prepare_only" -eq 1 ]]; then
  printf 'Prepared LifeOS runtime directories and validated .env placeholders.\n'
  exit 0
fi

docker compose --env-file .env --profile backup up -d --build \
  openclue-gateway \
  lifeos-db \
  lifeos-api \
  lifeos-backup
