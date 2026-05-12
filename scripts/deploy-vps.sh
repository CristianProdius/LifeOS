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
Usage: scripts/deploy-vps.sh [--dry-run] [--skip-backup] [--host HOST] [--remote-dir DIR]

Safely deploys LifeOS to the VPS without deleting OpenClaw runtime state.

Defaults:
  HOST       ${LIFEOS_DEPLOY_HOST:-jira-microlab-automation}
  DIR        ${LIFEOS_DEPLOY_DIR:-/opt/lifeos}
USAGE
}

host="${LIFEOS_DEPLOY_HOST:-jira-microlab-automation}"
remote_dir="${LIFEOS_DEPLOY_DIR:-/opt/lifeos}"
dry_run=0
skip_backup=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      dry_run=1
      shift
      ;;
    --skip-backup)
      skip_backup=1
      shift
      ;;
    --host)
      [[ $# -ge 2 ]] || die "--host requires a value"
      host="$2"
      shift 2
      ;;
    --remote-dir)
      [[ $# -ge 2 ]] || die "--remote-dir requires a value"
      remote_dir="$2"
      shift 2
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
done

command -v rsync >/dev/null 2>&1 || die "rsync is required"
command -v ssh >/dev/null 2>&1 || die "ssh is required"

if [[ "$dry_run" -eq 0 ]]; then
  ./scripts/verify.sh
fi

remote() {
  ssh -o BatchMode=yes "$host" "$@"
}

if [[ "$dry_run" -eq 0 && "$skip_backup" -eq 0 ]]; then
  remote "cd '$remote_dir' && ./scripts/backup.sh"
fi

rsync_args=(
  -az
  --delete
  --exclude '.env'
  --exclude 'backups/'
  --exclude 'openclaw/config/'
  --exclude 'openclaw/workspace/'
  --exclude 'openclaw/config/agents/'
  --exclude 'openclaw/config/identity/'
  --exclude 'openclaw/config/logs/'
  --exclude 'openclaw/config/telegram/'
  --exclude 'openclaw/config/tasks/'
  --exclude 'openclaw/config/cron/'
  --exclude 'openclaw/config/canvas/'
  --exclude 'openclaw/config/plugin-skills/'
  --exclude 'openclaw/config/openclaw.json'
  --exclude 'openclaw/config/openclaw.json.*'
  --exclude 'services/lifeos-api/.venv/'
  --exclude '**/__pycache__/'
  --exclude '.git/'
  --exclude '.pytest_cache/'
)

if [[ "$dry_run" -eq 1 ]]; then
  rsync_args+=(--dry-run --itemize-changes)
fi

rsync "${rsync_args[@]}" ./ "$host:$remote_dir/"

openclaw_rsync_args=(-az)
if [[ "$dry_run" -eq 1 ]]; then
  openclaw_rsync_args+=(--dry-run --itemize-changes)
fi

if [[ "$dry_run" -eq 0 ]]; then
  remote "mkdir -p '$remote_dir/openclaw/config' '$remote_dir/openclaw/workspace/skills'"
fi
rsync "${openclaw_rsync_args[@]}" \
  openclaw/config/openclaw.template.json \
  "$host:$remote_dir/openclaw/config/openclaw.template.json"
rsync "${openclaw_rsync_args[@]}" \
  openclaw/workspace/AGENTS.md \
  "$host:$remote_dir/openclaw/workspace/AGENTS.md"
rsync "${openclaw_rsync_args[@]}" --delete \
  openclaw/workspace/skills/ \
  "$host:$remote_dir/openclaw/workspace/skills/"

if [[ "$dry_run" -eq 1 ]]; then
  printf 'Dry run completed; no remote commands were executed.\n'
  exit 0
fi

remote "cd '$remote_dir' && ./scripts/bootstrap.sh --prepare-only"
remote "cd '$remote_dir' && docker compose --env-file .env build lifeos-api lifeos-migrate"
remote "cd '$remote_dir' && ./scripts/migrate.sh"
remote "cd '$remote_dir' && docker compose --env-file .env --profile backup up -d --build openclue-gateway lifeos-db lifeos-api lifeos-backup"

remote "cd '$remote_dir' && bash -s" <<'REMOTE_CHECK'
set -euo pipefail

gateway_token="$(grep '^OPENCLAW_GATEWAY_TOKEN=' .env | cut -d= -f2-)"
cron_status() {
  docker compose --env-file .env run --rm --no-deps \
    -e OPENCLAW_STATE_DIR=/tmp/openclaw-admin-state \
    -e OPENCLAW_CONFIG_PATH=/home/node/.openclaw/openclaw.json \
    openclaw-cli cron status --token "$gateway_token"
}

cron_jobs_from_json() {
  python3 -c 'import json,sys; print(json.load(sys.stdin).get("jobs", 0))'
}

status_json="$(cron_status)"
cron_jobs="$(printf '%s\n' "$status_json" | cron_jobs_from_json)"
if [[ "$cron_jobs" != "5" ]]; then
  printf 'OpenClaw cron had %s jobs after deploy; reinstalling reminder jobs.\n' "$cron_jobs" >&2
  ./scripts/openclaw-cron-setup.sh >/dev/null
  status_json="$(cron_status)"
  cron_jobs="$(printf '%s\n' "$status_json" | cron_jobs_from_json)"
fi

if [[ "$cron_jobs" != "5" ]]; then
  printf 'error: OpenClaw cron still has %s jobs after repair; expected 5\n' "$cron_jobs" >&2
  exit 1
fi

docker compose --env-file .env run --rm openclaw-cli models status --probe
docker compose --env-file .env ps
printf 'LifeOS deploy verification passed: OpenClaw cron has 5 jobs.\n'
REMOTE_CHECK
