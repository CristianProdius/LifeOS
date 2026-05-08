#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ENV_FILE:-.env}"

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
  ' "$ENV_FILE"
}

[[ -f "$ENV_FILE" ]] || die "$ENV_FILE is missing"
TOKEN="$(env_value TELEGRAM_BOT_TOKEN)"
case "$TOKEN" in
  ""|*replace_me*|*change_me*)
    die "TELEGRAM_BOT_TOKEN must be set in $ENV_FILE"
    ;;
esac

python3 - "$TOKEN" <<'PY'
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

token = sys.argv[1]
url = f"https://api.telegram.org/bot{token}/getUpdates?allowed_updates=%5B%22message%22,%22callback_query%22%5D"

try:
    with urllib.request.urlopen(url, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
except urllib.error.HTTPError as exc:
    detail = exc.read().decode("utf-8", errors="replace")
    print(f"Telegram API error {exc.code}: {detail}", file=sys.stderr)
    raise SystemExit(1)

if not payload.get("ok"):
    print(json.dumps(payload, indent=2), file=sys.stderr)
    raise SystemExit(1)

updates = payload.get("result", [])
if not updates:
    print("No updates found. Send one message in each LifeOS forum topic, then rerun this script.")
    raise SystemExit(0)

seen: set[tuple[int | None, int | None]] = set()
for update in updates:
    message = update.get("message") or (update.get("callback_query") or {}).get("message") or {}
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    chat_id = chat.get("id")
    thread_id = message.get("message_thread_id")
    key = (chat_id, thread_id)
    if key in seen:
        continue
    seen.add(key)
    print(
        "chat_id={chat_id} chat_type={chat_type} title={title!r} "
        "message_thread_id={thread_id} from_id={from_id} username={username!r} text={text!r}".format(
            chat_id=chat_id,
            chat_type=chat.get("type"),
            title=chat.get("title") or chat.get("username") or chat.get("first_name"),
            thread_id=thread_id,
            from_id=sender.get("id"),
            username=sender.get("username"),
            text=(message.get("text") or "")[:80],
        )
    )
PY
