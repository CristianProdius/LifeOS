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
  ' .env
}

require_env() {
  local key="$1"
  local value
  value="$(env_value "$key")"
  [[ -n "$value" ]] || die "$key must be set in .env"
  printf '%s' "$value"
}

compose_cron() {
  docker compose run --rm --no-deps \
    -e OPENCLAW_STATE_DIR=/tmp/openclaw-admin-state \
    -e OPENCLAW_CONFIG_PATH=/home/node/.openclaw/openclaw.json \
    openclaw-cli cron "$@" --token "$gateway_token"
}

remove_existing_jobs() {
  local jobs_json
  jobs_json="$(compose_cron list --all --json)"
  python3 - "$jobs_json" <<'PY' | while IFS= read -r job_id; do
import json
import sys

target_names = {
    "daily_wake_checkin",
    "daily_plan_lock",
    "midday_review",
    "evening_shutdown",
    "sunday_weekly_plan",
}

payload = json.loads(sys.argv[1])
for job in payload.get("jobs", []):
    if job.get("name") in target_names and job.get("id"):
        print(job["id"])
PY
    compose_cron rm "$job_id" >/dev/null
  done
}

add_job() {
  local name="$1"
  local cron_expr="$2"
  local topic_id="$3"
  local description="$4"
  local message="$5"
  local group_id="$6"
  local timezone="$7"

  compose_cron add \
    --name "$name" \
    --description "$description" \
    --cron "$cron_expr" \
    --tz "$timezone" \
    --agent main \
    --session isolated \
    --channel telegram \
    --to "$group_id" \
    --thread-id "$topic_id" \
    --announce \
    --best-effort-deliver \
    --timeout-seconds 180 \
    --message "$message" \
    --json >/dev/null
}

[[ -f .env ]] || die ".env is missing"
command -v docker >/dev/null 2>&1 || die "docker is required"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"

group_id="$(require_env TELEGRAM_ALLOWED_GROUP_ID)"
gateway_token="$(require_env OPENCLAW_GATEWAY_TOKEN)"
daily_topic_id="$(require_env TELEGRAM_TOPIC_DAILY_ID)"
review_topic_id="$(require_env TELEGRAM_TOPIC_REVIEW_ID)"
timezone="$(env_value OPENCLAW_TIMEZONE)"
timezone="${timezone:-$(env_value OPENCLAW_TZ)}"
timezone="${timezone:-Europe/Chisinau}"

remove_existing_jobs

add_job \
  "daily_wake_checkin" \
  "35 6 * * *" \
  "$daily_topic_id" \
  "06:35 readiness, sleep, blockers, and top constraint." \
  "OpenClue 06:35 wake check. Query LifeOS first for today's plan, habits, tasks, and workout state. Post a concise Daily-topic check-in asking whether Cristian is out of bed, sleep quality, readiness, and the one blocker. Never invent completed habits. For any button callback, submit Telegram callback values unchanged to POST /telegram/actions." \
  "$group_id" \
  "$timezone"

add_job \
  "daily_plan_lock" \
  "0 7 * * *" \
  "$daily_topic_id" \
  "07:00 daily plan proposal or confirmation." \
  "OpenClue 07:00 daily plan. Call POST /daily/command-center, then render the returned four mandatory commitments: one health action, one business deliverable, one anti-distraction guardrail, and one admin/review item. Use the returned buttons. For any button callback, submit Telegram callback values unchanged to POST /telegram/actions." \
  "$group_id" \
  "$timezone"

add_job \
  "midday_review" \
  "30 12 * * *" \
  "$daily_topic_id" \
  "12:30 progress check and afternoon adjustment." \
  "OpenClue 12:30 midday review. Query LifeOS first for today's tasks and habit logs. Ask what shipped, whether walking/deep work happened, and choose the single next action for the afternoon." \
  "$group_id" \
  "$timezone"

add_job \
  "evening_shutdown" \
  "30 21 * * *" \
  "$daily_topic_id" \
  "21:30 completion capture and next-day prep." \
  "OpenClue 21:30 evening shutdown. Query LifeOS first for tasks, habits, workouts, food, and finance notes. Ask for completion status, one lesson, and the first action for tomorrow morning." \
  "$group_id" \
  "$timezone"

add_job \
  "sunday_weekly_plan" \
  "0 20 * * SUN" \
  "$review_topic_id" \
  "Sunday 20:00 weekly review and next-week plan." \
  "OpenClue Sunday weekly review. Query LifeOS first for the week: task completion, habit logs, workouts, finance changes, and missed commitments. Summarize trends, pick next week's top priorities, and ask for confirmation." \
  "$group_id" \
  "$timezone"

compose_cron list --all --json
