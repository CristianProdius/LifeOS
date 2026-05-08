#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ENV_FILE:-.env}"
TEMPLATE="${OPENCLAW_TEMPLATE:-openclaw/config/openclaw.template.json}"
OUTPUT="${OPENCLAW_CONFIG_OUTPUT:-openclaw/config/openclaw.json}"

if [[ ! -f "$ENV_FILE" ]]; then
  printf 'error: missing %s; copy .env.example to .env and fill real values\n' "$ENV_FILE" >&2
  exit 1
fi

if [[ ! -f "$TEMPLATE" ]]; then
  printf 'error: missing template %s\n' "$TEMPLATE" >&2
  exit 1
fi

python3 - "$ENV_FILE" "$TEMPLATE" "$OUTPUT" <<'PY'
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
template_path = Path(sys.argv[2])
output_path = Path(sys.argv[3])
text = template_path.read_text(encoding="utf-8")

def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        values[key] = value
    return values

env_values = parse_env(env_path)
missing: set[str] = set()

def replace(match: re.Match[str]) -> str:
    key = match.group(1)
    value = os.getenv(key) or env_values.get(key)
    if value is None or value == "":
        missing.add(key)
        return match.group(0)
    return value

rendered = re.sub(r"\$\{([A-Z0-9_]+)\}", replace, text)
if missing:
    print("error: missing env values: " + ", ".join(sorted(missing)), file=sys.stderr)
    raise SystemExit(1)

json.loads(rendered)
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(rendered + "\n", encoding="utf-8")
print(f"Rendered {output_path}")
PY
