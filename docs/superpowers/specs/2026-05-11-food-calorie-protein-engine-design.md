# Food Calorie Protein Engine Design

## Goal

Add a strict but practical Food Engine to LifeOS so OpenClue can log meals, calculate daily calorie/protein adherence, and adjust nutrition advice from real stored data instead of guessing from memory.

## Research Notes

- wger uses a self-hosted fitness/nutrition model built around plans, meals, ingredients, and logs. LifeOS should copy the shape, not the whole app.
- kcal and Waistline use food diaries, reusable foods, nutrition goals, and optional product databases. LifeOS V1 should implement the diary and goals first.
- Open Food Facts and USDA FoodData Central are useful later for barcode/product lookup, but V1 should not depend on external food databases.
- The target engine uses Mifflin-St Jeor for BMR, a conservative activity factor, and weekly trend adjustment. Targets must be labeled as coaching estimates, not medical prescriptions.

## Scope

V1 implements:

- Active calorie/protein target.
- Food log and item storage.
- Daily food summary with calories/protein remaining.
- Seven-day progress summary and cautious adjustment recommendation.
- Food context enrichment for OpenClue.
- Prompt/docs changes that require OpenClue to use LifeOS before food advice.

V1 does not implement:

- Barcode scanning.
- Food database lookup.
- Automatic image recognition inside the API.
- Full meal plans or recipe management.

## Target Policy

Cristian's starting target is `1900 kcal/day` and `150 g protein/day`, with a hard automatic floor of `1800 kcal/day`. The calculation uses:

- sex: male
- age: 23
- height: 175 cm
- latest synced weight, falling back to 117 kg
- activity factor: 1.25
- protein basis: target body weight and resistance-training support

The engine never auto-adjusts without enough data. It requires at least five logged food days and three weight entries in the recent window.

## Data Model

New tables:

- `food_targets`: active target, calculation payload, calories, protein, carbs, fat, status, start/end dates.
- `food_logs`: meal-level log row with source, confidence, calories, protein, carbs, fat, status, Telegram metadata, and notes.
- `food_log_items`: item-level rows under a meal log.
- `food_daily_reviews`: daily hunger/energy/adherence notes and recommendations.

The summary is computed from logs instead of stored as a separate source of truth.

## API

- `GET /food/target`
- `POST /food/target/recalculate`
- `POST /food/logs`
- `PATCH /food/logs/{id}`
- `GET /food/daily-summary`
- `GET /food/progress`
- `POST /food/reviews/daily`

`GET /context/food` also returns `food_target`, `today_food_summary`, and `food_progress`.

## OpenClue Behavior

In the Food topic, OpenClue must:

- Query LifeOS before giving nutrition advice.
- Use `/food/daily-summary` before saying whether a meal fits today.
- Use `/food/progress` before making trend claims.
- Log meals with `POST /food/logs` before claiming they are tracked.
- Mark photo/visual estimates as estimates.
- Never treat missing logs as zero calories.

## Testing

Tests cover:

- Target creation from latest health weight.
- Meal logging with items.
- Daily totals and remaining calories/protein.
- Patch/delete behavior.
- Progress data quality and adjustment recommendation.
- Food context enrichment.
- Prompt/docs contract.
