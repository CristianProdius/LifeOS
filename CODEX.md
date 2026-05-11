# Codex Project Notes

## OpenClaw Runtime Auth Must Survive Deploys

Do not delete or overwrite OpenClaw runtime state on the VPS.

The production OpenClaw config directory is mounted from:

```text
/opt/lifeos/openclaw/config
```

It contains generated/runtime files that are not safe to recreate from git alone, including:

```text
openclaw/config/agents/main/agent/auth-profiles.json
openclaw/config/agents/
openclaw/config/identity/
openclaw/config/telegram/
openclaw/config/tasks/
openclaw/config/openclaw.json.last-good
```

If these files are deleted, Telegram fails with:

```text
Missing API key for provider "openai-codex"
```

When syncing code to the VPS, never run broad `rsync --delete` against `/opt/lifeos` unless runtime state is explicitly excluded. Safe deployment sync must exclude at least:

```text
.env
backups/
openclaw/config/agents/
openclaw/config/identity/
openclaw/config/logs/
openclaw/config/telegram/
openclaw/config/tasks/
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

