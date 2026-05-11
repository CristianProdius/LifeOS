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
  "weight_kg": 117.0,
  "body_fat_percent": 34.5,
  "bmi": 38.2,
  "steps": 6000,
  "active_energy_kcal": 530,
  "resting_heart_rate": 63,
  "average_heart_rate": 92,
  "notes": "iOS automatic health sync"
}
```

`summary_date` and `source` are required. The endpoint upserts by date and source, so sending the same day twice updates the same row instead of creating duplicates.

Recommended evening automation fields:

- `steps`
- `active_energy_kcal`
- `weight_kg`
- `body_fat_percent`
- `bmi`
- `resting_heart_rate`
- `average_heart_rate`
- `notes`

Xiaomi scale values should reach LifeOS through Xiaomi scale app sync into Apple Health, then through this Shortcut. Keep the Shortcut focused on stable daily summary values; do not send raw Health samples, sleep stage dictionaries, or unavailable fields.

## Shortcut Automation

Create an iOS Shortcut that:

1. Gets today's date formatted as `yyyy-MM-dd`.
2. Reads daily Apple Health totals and averages with Shortcuts health actions.
3. Builds the JSON payload above.
4. Sends it with `Get Contents of URL` using method `POST`.
5. Adds the `Authorization` header with `Bearer <LIFEOS_SHORTCUT_TOKEN>`.

Recommended automations:

- `21:45` for steps, active energy, heart rate, and latest Xiaomi scale body metrics.

Use Apple Health as the first aggregator. Direct CSV imports can be added later for records that do not sync.
