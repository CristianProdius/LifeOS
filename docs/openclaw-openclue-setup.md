# OpenClaw OpenClue Setup

This document covers the OpenClaw runtime workspace for OpenClue, the LifeOS coach. The scope is the OpenClaw side only: workspace skill, runtime configuration, Telegram forum setup, cron reminders, and deployment notes.

## Files

- `openclaw/workspace/skills/lifeos/SKILL.md`: OpenClue behavior contract.
- `openclaw/config/openclaw.template.json`: runtime config template with env var references and Telegram topic placeholders.
- `docs/openclaw-openclue-setup.md`: setup, deployment, and smoke test notes.

## Local Setup

1. Start the LifeOS API locally.
2. Export the OpenClaw environment variables listed below.
3. Point OpenClaw at the config template:

```bash
export OPENCLAW_CONFIG=/Users/cristian/Development/LifeOS/openclaw/config/openclaw.template.json
export OPENCLAW_WORKSPACE_DIR=/Users/cristian/Development/LifeOS/openclaw/workspace
```

4. Start the OpenClaw runtime with the workspace and config. Expected invocation shape:

```bash
openclaw run --config "$OPENCLAW_CONFIG" --workspace "$OPENCLAW_WORKSPACE_DIR"
```

If the runtime entrypoint differs, keep the same config and workspace paths.

## Environment Variables

OpenClaw runtime:

```bash
export OPENCLAW_ENV=development
export OPENCLAW_TIMEZONE=Europe/Chisinau
export OPENCLAW_LOG_LEVEL=info
export OPENCLAW_STATE_PATH=/Users/cristian/Development/LifeOS/openclaw/var/openclaw-state.json
export OPENCLAW_WORKSPACE_DIR=/Users/cristian/Development/LifeOS/openclaw/workspace
```

LifeOS API:

```bash
export LIFEOS_API_BASE_URL=http://127.0.0.1:8080
export LIFEOS_API_TOKEN=replace-with-local-token
export LIFEOS_API_TIMEOUT_MS=10000
```

Telegram:

```bash
export TELEGRAM_BOT_TOKEN=replace-with-bot-token
export TELEGRAM_BOT_MODE=long_polling
export TELEGRAM_WEBHOOK_URL=
export TELEGRAM_ALLOWED_USER_ID=replace-with-owner-user-id
export TELEGRAM_ALLOWED_GROUP_ID=replace-with-group-chat-id
export TELEGRAM_ALLOWED_GROUP_TITLE=LifeOS
export TELEGRAM_TOPIC_DAILY_ID=replace-with-daily-topic-id
export TELEGRAM_TOPIC_SPORT_ID=replace-with-sport-topic-id
export TELEGRAM_TOPIC_BUSINESS_ID=replace-with-business-topic-id
export TELEGRAM_TOPIC_FINANCE_ID=replace-with-finance-topic-id
export TELEGRAM_TOPIC_FOOD_ID=replace-with-food-topic-id
export TELEGRAM_TOPIC_REVIEW_ID=replace-with-review-topic-id
export TELEGRAM_TOPIC_ADMIN_ID=replace-with-admin-topic-id
```

Do not put secrets into `openclaw.template.json`. It is safe to commit because it stores env var names and placeholders only.

## Telegram Group And Forum Setup

1. Create a Telegram bot with BotFather and save `TELEGRAM_BOT_TOKEN`.
2. Create or choose a private Telegram group for LifeOS.
3. Enable Topics for the group so it becomes a forum.
4. Add the bot to the group.
5. Grant the bot permission to read messages, send messages, edit messages, and use topics.
6. Create these forum topics:

```text
Daily
Sport
Business
Finance
Food
Review
Admin
```

7. Capture the group chat id and each topic `message_thread_id`.
8. Set `TELEGRAM_ALLOWED_GROUP_ID` and the `TELEGRAM_TOPIC_*_ID` variables.
9. Test with an allowed user and one disallowed user before relying on the bot.

To discover IDs after the bot is added, send one message in each LifeOS forum topic, then run:

```bash
cd /opt/lifeos
./scripts/telegram-discover.sh
```

The script prints `chat_id`, `from_id`, and `message_thread_id` values without printing the bot token.

Topic ownership:

- Daily: morning, midday, evening, readiness, blockers, and daily scorecards.
- Sport: training, readiness, workout logs, skipped sessions, soreness, and recovery.
- Business: inbox, triage, focus blocks, blocked work, due dates, shipped work, and outreach.
- Finance: balances, budgets, imports, transaction review, categories, and reconciliation.
- Food: meals, sweets, late eating, weight trend, and nutrition notes.
- Review: weekly planning, daily reviews, goals, projects, commitments, and strategy.
- Admin: setup, config, API errors, deployment, logs, credentials, and coding.

OpenClue is configured with `messages.groupChat.visibleReplies: "message_tool"` so Telegram forum output is sent only through explicit `message` tool calls. This prevents raw assistant progress or tool traces from being posted as visible chat replies.

## Cron Reminders

The template defines reminders in local `OPENCLAW_TIMEZONE` time:

| Reminder | Cron | Topic | Purpose |
| --- | --- | --- | --- |
| `daily_wake_checkin` | `35 6 * * *` | Daily | 06:35 readiness, sleep, blockers, and top constraint |
| `daily_plan_lock` | `0 7 * * *` | Daily | 07:00 plan proposal or confirmation |
| `midday_review` | `30 12 * * *` | Daily | 12:30 progress check and afternoon adjustment |
| `evening_shutdown` | `30 21 * * *` | Daily | 21:30 completion capture and next-day prep |
| `sunday_weekly_plan` | `0 20 * * SUN` | Review | Sunday 20:00 weekly review and next-week plan |

Every cron reminder must query LifeOS before composing the message. If LifeOS is unavailable, the reminder should say that current state could not be loaded and avoid state-specific claims.

On the VPS, keep both `OPENCLAW_TZ` and `OPENCLAW_TIMEZONE` set to `Europe/Chisinau` in `.env`. The server host can stay on UTC; the gateway container and OpenClue cron jobs use Moldova time through these environment variables and the explicit `--tz Europe/Chisinau` cron setting.

## First Morning Flow

At 06:35, OpenClue posts in Daily after reading LifeOS plans, tasks, habits, and workouts. The message should ask for readiness, sleep quality, blockers, and the main constraint for the day.

At 07:00, OpenClue calls `POST /daily/command-center`, then renders the returned Daily Command Center. The command center returns exactly four mandatory commitments:

- One health action.
- One business deliverable.
- One anti-distraction guardrail.
- One admin/review action.

When the user presses a button, OpenClue submits Telegram callback values unchanged to `POST /telegram/actions` with the available Telegram metadata. LifeOS updates durable state first and returns the acknowledgement OpenClue should render in Daily or the owning topic. If the response has `suppress_visible_reply: true`, OpenClue should not post another visible chat message because the callback was already applied or replayed.

## Sport Workout Flow

Sport recommendations must be stored before OpenClue presents them as today's plan.

1. User asks for a workout in Sport.
2. OpenClue calls `POST /sport/today`.
3. LifeOS creates or reuses a program-linked `planned_workout`.
4. OpenClue sends the returned workout visibly in Sport with inline buttons.
5. Button callbacks are submitted unchanged to `POST /telegram/actions`; LifeOS updates state first, then OpenClue renders the returned acknowledgement in Sport.

For progress questions, OpenClue calls `GET /sport/progress`. For missed training days, OpenClue calls `POST /sport/missed-day`. `POST /workouts/plan` remains available for low-level/manual workout planning, but normal Telegram Sport workout generation should use the Sport Program Engine.

If no schedule/date signal is available, default context is `grandparents_home`. When personalization marks the date as a city day, OpenClue can use the city morning gym/pool default unless Cristian says he is at grandparents/home. At home, recommendations should use walking, mobility, gentle bodyweight, and recovery; avoid gym-equipment work such as Romanian deadlifts.

The Sport Program Engine now reads `personalization` settings from LifeOS. Those settings encode city days, city morning gym/pool defaults, grandparents midday training, the 50 m swim-repeat baseline with about 20 seconds rest, strict calorie/protein tracking, and coaching style. OpenClue must respect exercise restrictions from personalization: avoid lateral raises and high-rep shoulder isolation because those can trigger trap, neck, head, or dizziness symptoms. City days still need a defined work deliverable before the city work block starts.

Workout button callback values:

```text
lifeos:workout:{plan_id}:start
lifeos:workout:{plan_id}:done
lifeos:workout:{plan_id}:too_hard
lifeos:workout:{plan_id}:change
lifeos:workout:{plan_id}:skip
```

Daily task buttons should use the same LifeOS-first rule with deterministic values such as `lifeos:task:{task_id}:done`, `lifeos:task:{task_id}:block`, and `lifeos:task:{task_id}:snooze_tomorrow`. Submit those values unchanged to `POST /telegram/actions`.

## Food Calorie And Protein Flow

Food advice must be grounded in the LifeOS Food Engine, not generic estimates. OpenClue should call `GET /context/food`, `GET /food/target`, `GET /food/daily-summary`, and `GET /food/progress` before answering meal-fit, hunger, sweets, calorie, protein, or diet-progress questions.

The V1 starting target is 1900 kcal and 150 g protein. LifeOS enforces a hard automatic floor of 1800 kcal. Never treat missing food logs as zero calories; missing logs mean the day is incomplete.

When Cristian sends a meal, daily total, nutrition label, or photo estimate in the Food topic:

1. OpenClue calls `POST /food/logs` with `source`, `description`, `calories`, `protein_g`, and honest `confidence`.
2. LifeOS stores the log and item rows when item details exist.
3. OpenClue re-queries `/food/daily-summary`.
4. OpenClue replies in Food with remaining calories/protein and inline buttons.

Food confirmation buttons:

```text
Looks right
Edit calories
Add protein
Delete
```

## Health Summary Extension Point

V1.1 stores daily health summaries, not raw health samples. Use `POST /health/daily-summaries` for future Apple Health, Apple Watch, Sleep Cycle, Xiaomi scale, or iOS Shortcuts input. The summary can include sleep duration and quality, weight, body fat, BMI, steps, active energy, workout count, resting heart rate, average heart rate, and notes.

The VPS cannot directly pull Apple Health data. A later iOS app or Shortcut must push data into LifeOS after the user grants permission on the phone/watch.

## Finance Import Flow

Use the Finance topic for imports and reconciliation.

1. User sends a supported bank export or import command in Finance.
2. OpenClue sends the file or import metadata to the LifeOS finance import endpoint.
3. LifeOS returns parsed transactions, mapping confidence, duplicates, and review items.
4. OpenClue shows a compact review summary with approve, reject, recategorize, split, and mark reviewed buttons.
5. Button actions update LifeOS first. OpenClue then re-queries finance state before reporting balances, budgets, or reconciliation status.

Rules:

- Never infer a balance from partial imports.
- Keep imported transactions in review until approved or reconciled by LifeOS.
- Distinguish posted transactions, pending transactions, budgets, forecasts, and assumptions.
- Send parser errors and diagnostics to Admin without exposing raw tokens or headers.

## VPS Deployment

Docker Compose deployment:

1. Place this repository at `/opt/lifeos`.
2. Copy `.env.example` to `.env`.
3. Fill real values for `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID`, `TELEGRAM_ALLOWED_GROUP_ID`, all `TELEGRAM_TOPIC_*_ID` values, `OPENCLAW_GATEWAY_TOKEN`, `LIFEOS_API_TOKEN`, and `POSTGRES_PASSWORD`.
4. Keep `DATABASE_URL` in sync with the Postgres password.
5. Start the stack:

```bash
cd /opt/lifeos
./scripts/bootstrap.sh
```

The bootstrap script validates secrets, renders `openclaw/config/openclaw.json`, fixes OpenClaw bind-mount ownership on Linux root deployments, starts the gateway, starts LifeOS API/Postgres, and starts the backup worker.

### Deployment Sync Safety

Use the deploy script for normal VPS deploys:

```bash
./scripts/deploy-vps.sh
```

The script backs up Postgres, syncs code with protected runtime exclusions, rebuilds/restarts the stack, verifies model auth, verifies OpenClaw cron has `5` jobs, and reruns `scripts/openclaw-cron-setup.sh` automatically if the jobs are missing.

Do not delete OpenClaw runtime state during deploys. The VPS directory `openclaw/config` is not only generated config; it also contains runtime auth, identity, Telegram offsets, task state, cron reminder jobs, and model auth profiles. In particular, this file must survive deploys:

```text
openclaw/config/agents/main/agent/auth-profiles.json
```

If it is deleted, Telegram replies fail with:

```text
Missing API key for provider "openai-codex"
```

If `openclaw/config/cron/` is deleted, the OpenClaw cron job list becomes empty and the morning/daily Telegram reminders do not fire.

When using `rsync --delete` manually, exclude runtime state and sync OpenClaw source-controlled files separately:

```bash
rsync -az --delete \
  --exclude '.env' \
  --exclude 'backups/' \
  --exclude 'openclaw/config/' \
  --exclude 'openclaw/workspace/' \
  --exclude 'openclaw/config/agents/' \
  --exclude 'openclaw/config/identity/' \
  --exclude 'openclaw/config/logs/' \
  --exclude 'openclaw/config/telegram/' \
  --exclude 'openclaw/config/tasks/' \
  --exclude 'openclaw/config/cron/' \
  --exclude 'openclaw/config/canvas/' \
  --exclude 'openclaw/config/plugin-skills/' \
  --exclude 'openclaw/config/openclaw.json' \
  --exclude 'openclaw/config/openclaw.json.*' \
  --exclude 'services/lifeos-api/.venv/' \
  --exclude '**/__pycache__/' \
  ./ jira-microlab-automation:/opt/lifeos/

rsync -az openclaw/config/openclaw.template.json \
  jira-microlab-automation:/opt/lifeos/openclaw/config/openclaw.template.json
rsync -az openclaw/workspace/AGENTS.md \
  jira-microlab-automation:/opt/lifeos/openclaw/workspace/AGENTS.md
rsync -az --delete openclaw/workspace/skills/ \
  jira-microlab-automation:/opt/lifeos/openclaw/workspace/skills/
```

After every deploy, verify model auth:

```bash
cd /opt/lifeos
docker compose --env-file .env run --rm openclaw-cli models status --probe
```

Expected: `openai-codex/gpt-5.5` reports `ok`.

Also verify reminder jobs:

```bash
cd /opt/lifeos
gateway_token="$(grep '^OPENCLAW_GATEWAY_TOKEN=' .env | cut -d= -f2-)"
docker compose --env-file .env run --rm --no-deps \
  -e OPENCLAW_STATE_DIR=/tmp/openclaw-admin-state \
  -e OPENCLAW_CONFIG_PATH=/home/node/.openclaw/openclaw.json \
  openclaw-cli cron status --token "$gateway_token"
```

Expected: `jobs` is `5`. If `jobs` is `0`, reinstall the reminder jobs:

```bash
cd /opt/lifeos
./scripts/openclaw-cron-setup.sh
```

OpenClaw also needs model/provider authentication. OpenClue is configured to use the ChatGPT/Codex subscription route, not an OpenAI API key:

```bash
cd /opt/lifeos
docker compose run --rm openclaw-cli models auth login --provider openai-codex --method device-code
docker compose run --rm openclaw-cli models status --probe
```

The active model route is `openai-codex/gpt-5.5`, which is the Codex subscription model verified by a live agent turn for this stack. If OpenClue reports a missing API key for provider `openai`, check that `openclaw/config/openclaw.json` still has `agents.defaults.model.primary` set to `openai-codex/gpt-5.5`, then rerender and restart the gateway.

Health checks:

```bash
TOKEN="$(grep '^LIFEOS_API_TOKEN=' /opt/lifeos/.env | cut -d= -f2-)"
curl -fsS -H "X-API-Key: $TOKEN" http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:18789/healthz
docker compose ps
```

Telegram channel setup after the gateway is running:

```bash
cd /opt/lifeos
TELEGRAM_BOT_TOKEN="$(grep '^TELEGRAM_BOT_TOKEN=' .env | cut -d= -f2-)"
docker compose run --rm openclaw-cli channels add --channel telegram --token "$TELEGRAM_BOT_TOKEN"
```

Cron setup after Telegram topics are configured:

```bash
cd /opt/lifeos
./scripts/openclaw-cron-setup.sh
```

The cron setup script uses a temporary OpenClaw CLI state directory when calling gateway admin cron commands. This avoids stale paired-device scope limits while still authenticating with `OPENCLAW_GATEWAY_TOKEN`.

If the Control UI is needed from your laptop, use an SSH tunnel instead of exposing the port publicly: `ssh -L 18789:127.0.0.1:18789 root@server`.

## Security Notes

- Restrict Telegram access with both allowed user id and allowed group id.
- Keep the Admin topic private to trusted operators.
- Rotate `TELEGRAM_BOT_TOKEN` and `LIFEOS_API_TOKEN` after accidental exposure.
- Do not log secrets, raw authorization headers, bank credentials, or full bank exports.
- Prefer long polling for small private deployments to avoid exposing an inbound webhook.
- If webhook mode is used, require HTTPS and restrict the reverse proxy to the Telegram route.
- Back up LifeOS data separately from OpenClaw runtime state.
- Treat finance attachments as sensitive data and delete local temp files after import.
- Use least-privilege API tokens when LifeOS supports scoped tokens.

## Future Extension Points

Google Calendar:

- Add calendar read access to the planning read path before daily and weekly plans.
- Use LifeOS as the merge point for calendar events, tasks, and commitments.
- Add conflict detection before OpenClue proposes a time block.
- Route calendar setup and OAuth diagnostics to Admin.

iPhone automation:

- Use Shortcuts to send sleep, focus mode, workout, medication, location, and reminder events to LifeOS.
- Keep iPhone events as inputs; LifeOS remains the system of record.
- Add a signed webhook or token-protected endpoint for Shortcuts.
- Route automation failures to Admin and user-facing summaries to the owning topic.

## Manual Smoke Test Checklist

- JSON template parses successfully.
- All files are ASCII-only.
- `OPENCLAW_CONFIG` and `OPENCLAW_WORKSPACE_DIR` point to the expected paths.
- LifeOS health check succeeds with the configured token.
- Telegram allowed user can send `/start` in Admin.
- Disallowed user or group is rejected.
- Message in each forum topic routes to the same topic when intent matches.
- Task, habit, workout, finance, and plan advice each triggers a LifeOS read before the answer.
- Sport workout advice creates a `planned_workout` row before OpenClue sends the Telegram workout.
- A Telegram button updates LifeOS before OpenClue acknowledges success.
- Repeated workout `Done` clicks do not create duplicate completed workouts.
- Finance import dry run creates review items without inventing balances.
- Cron dry run sends 06:35, 07:00, 12:30, 21:30, and Sunday 20:00 reminders to the configured topics.
- Admin receives diagnostics for a forced LifeOS API failure without secrets in the log output.
