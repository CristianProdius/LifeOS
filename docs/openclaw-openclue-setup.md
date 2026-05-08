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

Topic ownership:

- Daily: morning, midday, evening, readiness, blockers, and daily scorecards.
- Sport: training, readiness, workout logs, skipped sessions, soreness, and recovery.
- Business: inbox, triage, focus blocks, blocked work, due dates, shipped work, and outreach.
- Finance: balances, budgets, imports, transaction review, categories, and reconciliation.
- Food: meals, sweets, late eating, weight trend, and nutrition notes.
- Review: weekly planning, daily reviews, goals, projects, commitments, and strategy.
- Admin: setup, config, API errors, deployment, logs, credentials, and coding.

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

## First Morning Flow

At 06:35, OpenClue posts in Daily after reading LifeOS plans, tasks, habits, and workouts. The message should ask for readiness, sleep quality, blockers, and the main constraint for the day.

At 07:00, OpenClue reads LifeOS again, then proposes the daily plan. The plan should include the smallest useful set of commitments:

- One primary focus.
- One fallback action.
- Habit and workout checks grounded in LifeOS state.
- Buttons for accept, revise, snooze, and mark blocked.

When the user presses a button, OpenClue updates LifeOS first, re-queries the changed state, then acknowledges the result in Daily or the owning topic.

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

Recommended shape:

1. Create a dedicated Linux user, for example `openclaw`.
2. Install the OpenClaw runtime and its dependencies.
3. Place this repository at `/opt/lifeos`.
4. Store secrets in an environment file readable only by the runtime user:

```bash
sudo install -o openclaw -g openclaw -m 600 /dev/null /etc/openclaw-lifeos.env
```

5. Put the exported variables from this document into `/etc/openclaw-lifeos.env`.
6. Run the bot in long polling mode unless a Telegram webhook is required.
7. If using webhook mode, terminate HTTPS at a reverse proxy and set `TELEGRAM_WEBHOOK_URL`.
8. Run OpenClaw under systemd.

Example systemd unit:

```ini
[Unit]
Description=OpenClaw OpenClue LifeOS bot
After=network-online.target
Wants=network-online.target

[Service]
User=openclaw
Group=openclaw
WorkingDirectory=/opt/lifeos/openclaw
EnvironmentFile=/etc/openclaw-lifeos.env
ExecStart=/usr/local/bin/openclaw run --config /opt/lifeos/openclaw/config/openclaw.template.json --workspace /opt/lifeos/openclaw/workspace
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Operational checks:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now openclaw-lifeos
sudo systemctl status openclaw-lifeos
journalctl -u openclaw-lifeos -f
```

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
- A Telegram button updates LifeOS before OpenClue acknowledges success.
- Finance import dry run creates review items without inventing balances.
- Cron dry run sends 06:35, 07:00, 12:30, 21:30, and Sunday 20:00 reminders to the configured topics.
- Admin receives diagnostics for a forced LifeOS API failure without secrets in the log output.
