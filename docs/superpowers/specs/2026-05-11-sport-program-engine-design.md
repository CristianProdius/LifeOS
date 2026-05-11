# Sport Program Engine Design

## Goal

Create a coherent Sport Program Engine for LifeOS so OpenClue stops producing isolated workout suggestions and instead generates daily training from a stored, adaptive fat-loss program.

Cristian's main target is to move from roughly 117 kg to 90 kg as fast as possible while staying healthy. The first explicit milestone is 95 kg by 2026-08-31, marked as a stretch milestone rather than the default safety target.

## Safety Frame

LifeOS should support ambition without hiding risk. The system will store both the user's stretch milestone and a computed healthy track.

The CDC describes gradual weight loss of about 1 to 2 pounds per week as more sustainable than faster loss. The CDC also recommends adults accumulate at least 150 minutes of moderate-intensity activity weekly and 2 days of muscle-strengthening activity weekly.

For this program:

- `90 kg` remains the long-term goal.
- `95 kg by 2026-08-31` is a stretch milestone.
- The program must flag when the required rate is more aggressive than the healthy baseline.
- The system must not prescribe extreme workouts to compensate for missed fat loss.
- Food consistency will be called out as the main driver of fat loss, even though this PR focuses on Sport.

## Current Problem

LifeOS currently has:

- `planned_workouts`, which stores one recommended workout.
- `/workouts/plan`, which creates a stored workout proposal.
- `/context/sport`, which exposes health summaries and recent workout state.
- OpenClue instructions to create planned workouts before replying in Telegram.

This is enough for single workouts, but not enough for a program. A workout generated today does not know the weekly target, phase, missed sessions, target weight pace, or whether the user is ahead or behind.

## Product Behavior

When Cristian asks in Sport:

- "What workout today?"
- "What should I do today?"
- "Am I on track?"
- "I missed yesterday, what now?"

OpenClue should use the Sport Program Engine, not invent a new workout. The answer should be grounded in:

- Active sport goal.
- Active training program.
- Current program week and phase.
- Completed and skipped planned workouts.
- Health daily summaries from Apple Health/Xiaomi.
- Weight trend and data quality.
- Current location/equipment context.

## Architecture

The program engine belongs in the LifeOS API and database. OpenClaw/OpenClue is the conversation layer.

LifeOS responsibilities:

- Store the goal, milestone, training program, program weeks, and adaptation history.
- Generate today's workout from program state.
- Compute progress and on-track score from stored data.
- Store every proposed workout and link it to the program week.
- Log advice decisions and data used.

OpenClue responsibilities:

- Call LifeOS before answering Sport questions.
- Send the stored workout to Telegram with buttons.
- Update LifeOS when buttons are clicked.
- Explain the recommendation briefly.
- Never invent target progress, adherence, or completion state.

## Data Model

Add `sport_goals`:

- `id`
- `user_id`
- `name`
- `status`: `active`, `paused`, `completed`, `archived`
- `start_date`
- `start_weight_kg`
- `target_weight_kg`
- `target_date`
- `stretch_weight_kg`
- `stretch_date`
- `healthy_weekly_loss_min_kg`
- `healthy_weekly_loss_max_kg`
- `notes`

Seed one active goal:

- name: `Cut to 90 kg`
- start weight: latest synced weight if present, otherwise `117`
- target weight: `90`
- target date: `2027-02-08`, based on a 39-week track from 2026-05-11 at about `0.69 kg/week`
- stretch weight: `95`
- stretch date: `2026-08-31`
- healthy weekly loss range: `0.45` to `0.9`

Add `training_programs`:

- `id`
- `user_id`
- `sport_goal_id`
- `name`
- `status`: `active`, `paused`, `completed`, `archived`
- `start_date`
- `duration_weeks`
- `current_week_number`
- `default_location_context`
- `notes`

Seed one active 39-week program, from 2026-05-11 to 2027-02-08, because that gives a concrete healthy-track target for 117 kg to 90 kg while still allowing the stretch milestone to be tracked separately.

Add `training_program_weeks`:

- `id`
- `program_id`
- `week_number`
- `phase`
- `week_start`
- `week_end`
- `target_weight_kg`
- `target_steps_avg`
- `target_active_minutes`
- `target_strength_sessions`
- `target_cardio_sessions`
- `target_recovery_sessions`
- `plan_json`

The phase map:

- Weeks 1-4: consistency base.
- Weeks 5-12: build weekly rhythm.
- Weeks 13-24: fat-loss engine.
- Weeks 25-32: run/walk introduction if joints are fine.
- Weeks 33-39: consolidation and maintenance preparation.

Add `program_adjustments`:

- `id`
- `program_id`
- `adjustment_date`
- `reason`: `missed_workout`, `fatigue`, `soreness`, `ahead`, `behind`, `manual`
- `input_payload`
- `output_payload`
- `notes`

Extend `planned_workouts`:

- `program_id`, nullable.
- `program_week_id`, nullable.
- `program_day`, nullable.
- `source`: `program`, `manual`, `legacy`.
- `adaptation_reason`, nullable.

## API

Add `GET /sport/program/active`.

Returns active goal, active program, current week, latest health progress, weekly adherence, and next planned workout if one exists.

Add `POST /sport/program/seed`.

Idempotently creates the default Sport goal and program for the current user. It is safe to run during deployment and local development.

Add `POST /sport/today`.

Request fields:

- `request_date`, optional, defaults to Europe/Chisinau today.
- `location_context`, optional.
- `available_minutes`, optional.
- `equipment`, optional.
- `notes`, optional.

Behavior:

- Reads the active program.
- Uses current week target and recent adherence.
- Reads health progress.
- Checks whether a proposed/started workout already exists for the date.
- Creates or returns one stored `planned_workout`.
- Logs an `advice_log`.

Add `GET /sport/progress`.

Returns:

- latest weight.
- required weight pace for stretch milestone.
- healthy pace status.
- current target weight for the week.
- weight delta from target.
- workout adherence.
- movement adherence.
- `on_track_score` from `0` to `100`.
- `confidence`: `low`, `medium`, `high`.
- `reasons`.
- `next_actions`.

Add `POST /sport/missed-day`.

Records that the user missed or could not perform a day and creates a safe adjustment. It must not increase intensity aggressively. It can shift the week's workout mix, recommend an easy walking/recovery day, or reduce the next workout.

## On-Track Score

The score should be transparent, not a magical probability.

Initial formula:

- 40% weight trend vs target track.
- 30% workout adherence.
- 20% movement adherence from steps/active energy.
- 10% recovery/consistency signal from skipped or missed days.

Data quality rules:

- If fewer than 7 days of weight data exist, weight trend confidence is low.
- If fewer than 2 completed workouts exist, workout adherence confidence is low.
- If no Apple Health sync exists in the last 2 days, movement confidence is low.
- Low confidence must be shown in the response instead of pretending the score is precise.

## Workout Generation Rules

Default home/grandparents context:

- Walking.
- Mobility.
- Chair squats or sit-to-stand.
- Wall or incline push-ups.
- Dead hangs only after pull-up bar is available.
- Gentle core and breathing.

Gym/Chisinau context:

- Machine or beginner strength work.
- Swimming or pool cardio if pool context is explicit.
- No complex heavy lifts by default.

Progression:

- Increase volume slowly.
- Prefer more walking frequency before high-impact running.
- Do not add running until the program reaches the run/walk phase and joints are fine.
- If a day is missed, do not double the next workout.
- If fatigue, soreness, high average heart rate, or poor adherence appears, bias easier.

## OpenClue Behavior

Update `AGENTS.md`, the `lifeos` skill, and OpenClaw config:

- For "what workout today?", call `POST /sport/today`.
- For "am I on track?", call `GET /sport/progress`.
- For missed days, call `POST /sport/missed-day`.
- Keep workout buttons wired to planned workout endpoints.
- Explain the program reason briefly: phase, weekly target, and adjustment reason.
- Do not call `/workouts/recommend` for Telegram Sport flows.

## Cleanup Scope

This implementation should reduce duplicate behavior.

- Keep `/workouts/plan` as a low-level/manual route for explicit manual workout creation and for internal use.
- Stop using `/workouts/recommend` in OpenClue prompts.
- Mark `/workouts/recommend` as legacy in docs and tests.
- If `/sport/today` fully covers Telegram workout generation, remove references that instruct OpenClue to call `/workouts/plan` directly for normal Sport questions.
- Do not delete existing database tables or old workouts.
- Do not remove `/workouts/plan`, because existing Telegram button flows and planned workout completion still depend on it.

## Testing

API tests must cover:

- Seeded active sport program is idempotent.
- `/sport/program/active` returns goal, program, current week, and health context.
- `/sport/today` creates a stored planned workout linked to the program.
- Repeating `/sport/today` on the same date returns/reuses the active planned workout instead of duplicating.
- Home context avoids gym exercises.
- Gym context differs from home context.
- Missed day creates an adjustment and does not create an extreme workout.
- `/sport/progress` returns low confidence when data is insufficient.
- `/sport/progress` improves confidence when enough weight/workout/movement data exists.
- Existing workout button completion remains idempotent.
- Existing health progress tests still pass.

OpenClue prompt/config tests must cover:

- Sport prompt references `/sport/today`.
- Sport progress prompt references `/sport/progress`.
- Missed day prompt references `/sport/missed-day`.
- Normal Telegram Sport workout requests no longer route through `/workouts/recommend`.

Deployment checks:

- Run full API tests.
- Run Alembic migration from current database.
- Back up Postgres before migration.
- Deploy to `/opt/lifeos`.
- Restart `lifeos-api` and `openclue-gateway`.
- Verify `/sport/program/active`, `/sport/today`, and `/sport/progress` on VPS.
- Ask Telegram Sport "what workout today?" and confirm the planned workout is linked to the active program.

## Out Of Scope

- Full nutrition/calorie engine.
- Apple Health raw workout ingestion.
- Sleep score integration.
- Public dashboard UI.
- Medical diagnosis or clinical weight-loss treatment.

## Sources

- CDC, "Steps for Losing Weight": https://www.cdc.gov/healthy-weight-growth/losing-weight/index.html
- CDC, "Adult Activity: An Overview": https://www.cdc.gov/physical-activity-basics/guidelines/adults.html
