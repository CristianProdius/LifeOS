# Apple Health Shortcut Ingestion

LifeOS exposes a narrow public endpoint for iOS Shortcuts:

```text
POST https://lifeos.prodiusenterprise.com/integrations/shortcuts/health-daily-summary
Authorization: Bearer <LIFEOS_SHORTCUT_TOKEN>
Content-Type: application/json
```

Only this endpoint should be exposed publicly. The normal LifeOS API remains protected by `LIFEOS_API_TOKEN` and should stay bound to `127.0.0.1` behind Nginx.

## JSON Payload

Send one daily summary per source. Apple Health can aggregate Apple Watch activity, Xiaomi scale data, and Sleep Cycle data if those apps sync into Apple Health.

```json
{
  "summary_date": "2026-05-11",
  "source": "apple_health",
  "sleep_duration_minutes": 420,
  "sleep_quality": 80,
  "weight_kg": 117.0,
  "body_fat_percent": 34.5,
  "bmi": 38.2,
  "steps": 6000,
  "active_energy_kcal": 530,
  "workouts_count": 1,
  "resting_heart_rate": 63,
  "average_heart_rate": 92,
  "notes": "Imported by iOS Shortcut"
}
```

`summary_date` and `source` are required. The endpoint upserts by date and source, so sending the same day twice updates the same row instead of creating duplicates.

## Shortcut Automation

Create an iOS Shortcut that:

1. Gets today's date formatted as `yyyy-MM-dd`.
2. Reads daily Apple Health totals and averages with Shortcuts health actions.
3. Builds the JSON payload above.
4. Sends it with `Get Contents of URL` using method `POST`.
5. Adds the `Authorization` header with `Bearer <LIFEOS_SHORTCUT_TOKEN>`.

Recommended automations:

- `06:45` for sleep/weight data after wake-up.
- `21:45` for steps, active energy, and workout count.
- Optional Apple Watch workout-finished automation if available on the phone.

Use Apple Health as the first aggregator. Sleep Cycle and Xiaomi scale should sync to Apple Health when possible; direct CSV imports can be added later for records that do not sync.
