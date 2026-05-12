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
  scripts/deploy-vps.sh
  scripts/render-openclaw-config.sh
  scripts/render-openclue-contract.py
  scripts/openclaw-cron-setup.sh
  scripts/verify.sh
  openclaw/contracts/lifeos_contract.json
  openclaw/workspace/AGENTS.md
  openclaw/workspace/skills/lifeos/SKILL.md
  services/lifeos-api/alembic/versions/0002_lifeos_v11_core.py
)

for path in "${required_files[@]}"; do
  [[ -f "$path" ]] || die "missing $path"
done

for path in scripts/bootstrap.sh scripts/migrate.sh scripts/seed.sh scripts/backup.sh scripts/deploy-vps.sh scripts/render-openclaw-config.sh scripts/openclaw-cron-setup.sh scripts/verify.sh; do
  [[ -x "$path" ]] || die "$path is not executable"
done

[[ -x scripts/render-openclue-contract.py ]] || die "scripts/render-openclue-contract.py is not executable"

for script in scripts/bootstrap.sh scripts/migrate.sh scripts/seed.sh scripts/backup.sh scripts/deploy-vps.sh scripts/render-openclaw-config.sh scripts/openclaw-cron-setup.sh scripts/verify.sh; do
  bash -n "$script"
done

scripts/render-openclue-contract.py --check

for protected_path in \
  ".env" \
  "backups/" \
  "openclaw/config/" \
  "openclaw/workspace/" \
  "openclaw/config/agents/" \
  "openclaw/config/identity/" \
  "openclaw/config/logs/" \
  "openclaw/config/telegram/" \
  "openclaw/config/tasks/" \
  "openclaw/config/cron/" \
  "openclaw/config/openclaw.json" \
  "openclaw/config/openclaw.json.*"; do
  grep -Fq -- "--exclude '$protected_path'" scripts/deploy-vps.sh || die "deploy script must exclude $protected_path"
done

grep -Fq './scripts/openclaw-cron-setup.sh' scripts/deploy-vps.sh || die "deploy script must repair missing cron jobs"
grep -Fq 'openclaw-cli cron status' scripts/deploy-vps.sh || die "deploy script must verify cron status"
grep -Fq 'openclaw/config/openclaw.template.json' scripts/deploy-vps.sh || die "deploy script must sync the OpenClaw config template explicitly"
grep -Fq 'openclaw/workspace/skills/' scripts/deploy-vps.sh || die "deploy script must sync OpenClaw workspace skills explicitly"

if LC_ALL=C grep -R -n --exclude='*.pyc' --exclude-dir='__pycache__' '[^[:print:][:space:]]' .gitignore .env.example docker-compose.yml scripts; then
  die "non-ASCII or control characters detected"
fi

command -v uv >/dev/null 2>&1 || die "uv is required"
(cd services/lifeos-api && uv run pytest tests/test_architecture.py)

command -v docker >/dev/null 2>&1 || die "docker is required"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"
docker compose --env-file "$ENV_FILE" config --quiet

services="$(docker compose --env-file "$ENV_FILE" --profile backup config --services)"
for service in openclue-gateway lifeos-api lifeos-db lifeos-migrate lifeos-backup; do
  printf '%s\n' "$services" | grep -qx "$service" || die "missing compose service $service"
done

printf 'LifeOS infrastructure verification passed using %s.\n' "$ENV_FILE"
