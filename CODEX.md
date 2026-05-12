# Codex Project Notes

## OpenClaw Runtime State Must Survive Deploys

Do not delete or overwrite OpenClaw runtime state on the VPS.

The production OpenClaw config directory is mounted from:

```text
/opt/lifeos/openclaw/config
```

It contains generated/runtime files that are not safe to recreate from git alone, including:

```text
openclaw/config/
openclaw/workspace/
openclaw/config/agents/main/agent/auth-profiles.json
openclaw/config/agents/
openclaw/config/identity/
openclaw/config/telegram/
openclaw/config/tasks/
openclaw/config/cron/
openclaw/config/openclaw.json.last-good
```

If these files are deleted, Telegram fails with:

```text
Missing API key for provider "openai-codex"
```

If `openclaw/config/cron/` is deleted, morning/daily Telegram reminders stop because the OpenClaw cron job list is empty.

Always deploy with:

```bash
./scripts/deploy-vps.sh
```

Do not copy old one-off `rsync` snippets from implementation plans. When syncing code to the VPS manually, never run broad `rsync --delete` against `/opt/lifeos` unless runtime state is explicitly excluded. Safe deployment sync must exclude at least:

```text
.env
backups/
openclaw/config/
openclaw/workspace/
openclaw/config/agents/
openclaw/config/identity/
openclaw/config/logs/
openclaw/config/telegram/
openclaw/config/tasks/
openclaw/config/cron/
openclaw/config/canvas/
openclaw/config/plugin-skills/
openclaw/config/openclaw.json
openclaw/config/openclaw.json.*
services/lifeos-api/.venv/
**/__pycache__/
```

After any deploy that touches `openclaw/config`, verify auth before asking Cristian to test Telegram:

```bash
cd /opt/lifeos
docker compose --env-file .env run --rm openclaw-cli models status --probe
```

Expected result:

```text
Providers w/ OAuth/tokens (1): openai-codex
openai-codex/gpt-5.5 ... ok
```

Also verify reminder jobs after deploy:

```bash
cd /opt/lifeos
gateway_token="$(grep '^OPENCLAW_GATEWAY_TOKEN=' .env | cut -d= -f2-)"
docker compose --env-file .env run --rm --no-deps \
  -e OPENCLAW_STATE_DIR=/tmp/openclaw-admin-state \
  -e OPENCLAW_CONFIG_PATH=/home/node/.openclaw/openclaw.json \
  openclaw-cli cron status --token "$gateway_token"
```

Expected result: `jobs` is `5`. If it is `0`, run:

```bash
cd /opt/lifeos
./scripts/openclaw-cron-setup.sh
```

If auth is missing, re-authenticate:

```bash
cd /opt/lifeos
docker compose --env-file .env run --rm openclaw-cli models auth login --provider openai-codex --method device-code
docker compose --env-file .env restart openclue-gateway
docker compose --env-file .env run --rm openclaw-cli models status --probe
```

Then check gateway logs:

```bash
docker compose --env-file .env logs --since=3m openclue-gateway | grep -E "No API key|Missing API key|Embedded agent failed|lane task error" || true
```
