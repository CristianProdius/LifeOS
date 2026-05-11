# Sport Personalization Design

## Goal

Personalize the existing LifeOS Sport Program Engine around Cristian's real schedule, training history, food strategy, and failure triggers.

The current engine stores a coherent 39-week fat-loss program. This personalization layer should make daily recommendations less generic by teaching LifeOS the constraints that actually determine whether a workout, swim, food plan, or workday succeeds.

## User Profile

- Age: 23.
- Sex: male.
- Current weight: about 117 kg.
- Long-term target: 90 kg as fast as healthy.
- Stretch milestone: 95 kg by 2026-08-31.
- Training history: trained seriously from about age 14 to 16, had strong fitness and visible abs, then no consistent training for about 5-6 years.
- Current classification: beginner-returning, not true novice.
- Motivation: health, confidence, energy, business productivity, and relationship/proposal readiness.

## Location And Schedule

Grandparents/home is the default productivity base:

- Proper office setup with keyboard, mouse, and monitor.
- More productive than city work by roughly 10-20%.
- Home training happens during the midday break.

City/Chisinau is the training and relationship anchor:

- Gym and Olympic swimming pool are available.
- Travel costs about 2 hours round trip.
- City work happens from a laptop in a cafe or library and is less productive.
- City days are acceptable when they combine morning training, work deliverable, and girlfriend time.

Default weekly rhythm:

- Monday: if waking in city, train in the morning, then return to grandparents and work. If already at grandparents, do midday home training.
- Tuesday: grandparents, deep work, midday home/bodyweight/walking.
- Wednesday: city day, morning gym or swim, work deliverable from cafe/library, girlfriend time, possibly overnight at parents.
- Thursday: grandparents, deep work, midday recovery/bodyweight/walking.
- Friday: city day, morning gym or swim, work deliverable, girlfriend/date time.
- Saturday: city, longer swim or gym plus cardio.
- Sunday: city/rest, long walk, weekly review, food planning, next week planning.

City days still require one meaningful business deliverable. Because the environment is weaker, OpenClue should force the deliverable to be defined before the work block starts.

## Training Availability

Cristian is willing to train 6 days per week if the plan is goal-aligned. LifeOS must not treat this as 6 hard days.

Weekly training structure:

- 3 real training days: gym or swim with progression.
- 2 easy/moderate days: walking, mobility, calisthenics, or technique swim.
- 1 longer low-impact day: swim or long walk.
- 1 true rest/review day, or very light walking only.

Default session length:

- City gym/pool: 45-60 minutes.
- Grandparents/home: 30-45 minutes.
- Weekend long swim/walk: up to 75 minutes if recovery is good.

## Cardio And Swimming Baseline

Walking:

- Can walk 30-45 minutes comfortably.
- Jogging is hard due to current body weight.
- Running should not be part of the first phase except as a later progression after walking tolerance and body weight improve.

Swimming:

- Can swim for about 1 hour with rests.
- Comfortable pattern: 50 m swim, about 20 seconds rest, repeat.
- Can swim 100 m continuously.
- Can sometimes swim 200 m continuously, but it is hard.

Swimming is a primary fat-loss tool because it provides low-impact cardio, confidence, and a good psychological state.

## Strength And Calisthenics Baseline

Cristian prefers free weights because they feel more athletic and engaging, but the program must respect detraining and current body weight.

Baseline:

- Pull-ups: 1-2 likely possible.
- Dead hang: 10-15 seconds; hand/grip discomfort is limiting.
- Push-ups: about 20-30.
- Bodyweight squats: high capacity, likely 50+.

Gym style:

- Use full-body/simple strength circuit in the first phase.
- Use dumbbells, cables, machines, and bodyweight.
- Avoid maximal barbell work early.
- Use RPE 6-7 by default, with 2-4 reps in reserve.
- Increase intensity only when adherence, soreness, and sleep support it.

Home equipment:

- Improvised pull-up bar available.
- Improvised dumbbells possible with water bottles, including 9 L bottles.
- Walking pad planned in the next 2-4 weeks, not available yet.
- Follow-along HIIT videos may be used only as modified low-impact conditioning early.

## Exercise Safety

There is no broad injury limitation, but shoulder isolation has a specific caution.

Avoid for now:

- Lateral raises.
- High-rep shoulder isolation.
- Exercises that cause traps to over-contract and trigger neck/head pain or dizziness.

Allowed with caution:

- Controlled pressing if symptom-free.
- Rows.
- Pulldowns.
- Machine chest press.
- Light dumbbell/cable work that does not trigger neck/head symptoms.

Rule:

- If neck pain, head pain, or dizziness appears during an exercise, stop that exercise immediately.
- If dizziness/headache repeats with lifting, OpenClue should recommend a doctor or physiotherapist check.

## Daily Workout Decision Logic

OpenClue should decide the day's workout using location, recovery, schedule, and program state.

Default rules:

- If city and good energy: choose gym full-body or swim cardio based on weekly balance.
- If city and tired, sore, or mentally drained: choose swim technique/easy cardio.
- If grandparents: choose walking, calisthenics, mobility, or low-impact follow-along conditioning.
- If poor sleep: reduce intensity.
- If yesterday was missed: do not punish or double intensity; use a recovery or easy restart session.
- If user asks for gym while at grandparents: either provide a home alternative or ask whether they are actually going to the city.

Primary training objective:

- Burn calories with the lowest injury risk.
- Tie-breaker: swimming when motivation/recovery is low; gym when focus is high enough to train properly.

## Food Strategy

Fat loss is primarily driven by food, not by punishing workouts.

Chosen strategy:

- Aggressive calorie deficit at the start.
- Strict daily calorie tracking.
- Strict daily protein tracking.
- Food photos sent to the Food Telegram topic.
- OpenClue may estimate from photos only when exact data is unavailable and must label those as estimates.
- Weekly average weight is used for adjustments, not single weigh-ins.
- If hunger, dizziness, bingeing, sleep collapse, or training collapse happens, the system should reduce aggressiveness instead of recommending compensatory workouts.

Meal structure:

- Use meal templates with strict calorie/protein targets.
- Default to 3 meals plus optional planned snack.
- No unplanned late eating.
- Mostly home-cooked food at grandparents.
- Explicit meal prep is acceptable.
- City days need a safe default cafe/restaurant rule.

Food restrictions:

- No allergies or religious restrictions.
- No refused foods.
- Calorie-dense foods should be controlled tightly: sweets, bread, pasta, rice, oil, nuts, fried foods.

Kitchen scale:

- Add "buy kitchen scale" as a task.
- Until then, use photos and visual portions with higher uncertainty.
- Once the scale is available, require weighing calorie-dense foods.

## Sleep And Recovery

Default sleep target:

- Bed target: 23:30.
- Wake target: 07:00.
- Main behavioral rule: get out of bed immediately; no snooze loop.

Sleep is the first protection priority because it affects food discipline, training readiness, scrolling, business output, and mood.

If sleep is poor:

- Reduce workout intensity.
- Prefer swim, walking, mobility, or easy technique.
- Keep the food plan strict but simple.
- Protect the business deliverable by narrowing scope.

## Business And Productivity Integration

The business metric is output-based:

- One meaningful business deliverable per workday.
- Grandparents days are high-output days.
- City days still require a deliverable, but the plan must be tighter because laptop/cafe/library work is less productive.

OpenClue should require:

- What is today's deliverable?
- What does done mean?
- When is the first focused block?

On city days, OpenClue should prevent the pattern of travel plus coffee plus scrolling by forcing the work block to be named before the day fragments.

## Coaching Style

Cristian wants OpenClue to be strict and data-based.

Behavior:

- Directly call out missed training, overeating, sleep failure, or scrolling.
- Show the data consequence where available.
- Give the next corrective action.
- Do not shame.
- Do not recommend punishment workouts.
- Do not invent progress, calories, workouts, weights, or adherence.

Top failure triggers to defend against:

1. Staying in bed or sleep schedule breaking.
2. Instagram/scrolling wasting the day.
3. Sweets/chocolate/compulsive eating.

## LifeOS Product Changes

This personalization should become structured data, not only prompt text.

Add or extend profile storage so LifeOS knows:

- City training days preference.
- Grandparents/home as productivity base.
- City as gym/pool/relationship anchor.
- Default city training time: morning.
- Default home training time: midday.
- Gym/pool availability.
- Swimming baseline.
- Walking baseline.
- Calisthenics baseline.
- Exercise restrictions, including lateral raise/neck/head/dizziness caution.
- Food tracking mode.
- Calorie target aggressiveness.
- Sleep target.
- Coaching style.
- Top failure triggers.

Sport workout generation should use these fields when selecting:

- gym vs swim vs home training.
- intensity.
- duration.
- exercises.
- whether to ask a clarification question.

Food and Daily contexts should also expose the relevant personalization fields.

## API Direction

The implementation can use one of these approaches:

1. Extend `LifeProfile` JSON fields with sport, food, sleep, productivity, and coaching preferences.
2. Add dedicated tables such as `sport_profiles`, `food_profiles`, and `coaching_preferences`.
3. Hybrid: add a `profile_settings` table keyed by domain and JSON payload.

Recommended approach: hybrid or dedicated profile tables. The data is important enough to be structured, but not all fields need first-class columns immediately.

The API should expose:

- `GET /profile` with personalization settings included.
- `PATCH /profile` or a dedicated personalization endpoint to update these settings.
- Sport contexts should include the sport personalization block.
- Food contexts should include food tracking and calorie strategy.
- Daily contexts should include sleep, productivity, and failure-trigger rules.

## Success Criteria

- OpenClue stops treating workouts as generic.
- "What workout today?" reflects whether Cristian is at grandparents, city, gym, or pool.
- Home plans never include gym-only equipment.
- Swim is used as a first-class training option, not an afterthought.
- City days combine morning training, girlfriend time, and a defined work deliverable.
- Food tracking becomes strict enough to support aggressive fat loss.
- Poor sleep automatically reduces workout intensity and narrows the work plan.
- Lateral raises and symptom-triggering shoulder work are avoided.
- OpenClue can explain why it chose swim, gym, home calisthenics, walking, or recovery.

## Out Of Scope

- Full meal-plan generator with recipes.
- Medical diagnosis for dizziness/headache.
- Apple Health raw workout ingestion.
- Automatic calendar-based city detection.
- Native iOS app.
- Running program before walking tolerance and weight trend support it.
