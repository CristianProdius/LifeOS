#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BEGIN = "<!-- BEGIN GENERATED LIFEOS CONTRACT -->"
END = "<!-- END GENERATED LIFEOS CONTRACT -->"
ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "openclaw/contracts/lifeos_contract.json"
MARKDOWN_TARGETS = [
    ROOT / "openclaw/workspace/AGENTS.md",
    ROOT / "openclaw/workspace/skills/lifeos/SKILL.md",
]
CONFIG_TARGET = ROOT / "openclaw/config/openclaw.template.json"


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def action_label(action: str) -> str:
    return action.replace("_", " ").capitalize()


def route_list(routes: list[str]) -> str:
    return ", ".join(f"`{route}`" for route in routes)


def route_with_notes(route: str, notes: dict[str, str]) -> str:
    if route in notes:
        return f"`{route}` ({notes[route]})"
    return f"`{route}`"


def route_list_with_notes(routes: list[str], notes: dict[str, str]) -> str:
    return ", ".join(route_with_notes(route, notes) for route in routes)


def plain_route_with_notes(route: str, notes: dict[str, str]) -> str:
    if route in notes:
        return f"{route} ({notes[route]})"
    return route


def plain_route_list(routes: list[str], notes: dict[str, str]) -> str:
    return ", ".join(plain_route_with_notes(route, notes) for route in routes)


def render_markdown(contract: dict) -> str:
    required_reads = contract["required_context_reads"]
    callbacks = contract["button_callbacks"]
    endpoint_notes = contract.get("endpoint_notes", {})
    lines = [
        BEGIN,
        "## Generated LifeOS Contract",
        "",
        f"- Assistant name: {contract['assistant_name']}",
        f"- Source of truth: {contract['source_of_truth']}",
        "- Forbidden tools: " + ", ".join(f"`{tool}`" for tool in contract["forbidden_tools"]),
        f"- Telegram action endpoint: `{contract['telegram_action_endpoint']}`",
        f"- Daily command center endpoint: `{contract['daily_command_center_endpoint']}`",
        "",
        "### Required Contract Endpoints",
    ]
    for domain, routes in required_reads.items():
        lines.append(f"- {domain}: {route_list_with_notes(routes, endpoint_notes)}")

    lines.extend(["", "### Write Before Claiming"])
    for item in contract["write_before_claiming"]:
        lines.append(f"- {item}")

    lines.extend(["", "### Button Callback Actions"])
    for kind, actions in callbacks.items():
        lines.append(f"- {kind}: " + ", ".join(f"`{action}`" for action in actions))

    lines.extend(
        [
            "",
            "### Deterministic Runtime Actions",
            f"- For Telegram button callbacks, submit Telegram callback values unchanged to `{contract['telegram_action_endpoint']}` with available Telegram metadata.",
            f"- For morning planning, call `{contract['daily_command_center_endpoint']}` and render the returned four mandatory commitments.",
        ]
    )

    lines.append(END)
    return "\n".join(lines)


def replace_marked_section(path: Path, generated: str) -> str:
    text = path.read_text(encoding="utf-8")
    begin_count = text.count(BEGIN)
    end_count = text.count(END)
    if begin_count != 1 or end_count != 1:
        raise ValueError(
            f"{display_path(path)} must contain exactly one generated contract marker pair "
            f"(found begin={begin_count}, end={end_count})"
        )

    begin_index = text.index(BEGIN)
    end_index = text.index(END)
    if end_index < begin_index:
        raise ValueError(f"{display_path(path)} has generated contract end marker before begin marker")

    before = text[:begin_index]
    after = text[end_index + len(END) :]
    return before + generated + after


def render_system_prompt(contract: dict) -> str:
    reads = contract["required_context_reads"]
    callbacks = contract["button_callbacks"]
    endpoint_notes = contract.get("endpoint_notes", {})
    write_items = ", ".join(contract["write_before_claiming"])
    forbidden = ", ".join(contract["forbidden_tools"])
    action_endpoint = contract["telegram_action_endpoint"]
    command_center_endpoint = contract["daily_command_center_endpoint"]
    read_summary = "; ".join(
        f"{domain}: {plain_route_list(routes, endpoint_notes)}" for domain, routes in reads.items()
    )
    callback_summary = "; ".join(
        f"{kind}: {', '.join(actions)}" for kind, actions in callbacks.items()
    )
    workout_buttons = ", ".join(action_label(action) for action in callbacks["workout"])
    food_buttons = ", ".join(action_label(action) for action in callbacks["food"])

    sentences = [
        f"You are {contract['assistant_name']}, a LifeOS coach running on OpenClaw.",
        f"{contract['source_of_truth']} is the source of truth.",
        "For task, habit, workout, finance, food, health, daily-plan, and review advice, query the LifeOS API with exec before responding.",
        f"Forbidden tools for LifeOS state: {forbidden}.",
        f"Required LifeOS contract endpoints by domain: {read_summary}. Match each endpoint to the user intent; mutating endpoints are not generic reads.",
        f"Write to LifeOS before claiming these durable actions exist: {write_items}.",
        f"Supported button callback actions: {callback_summary}.",
        f"For Telegram button callbacks, submit Telegram callback values unchanged to POST {action_endpoint} with available Telegram metadata; render the returned acknowledgement instead of hand-routing callback actions.",
        f"For morning planning and daily four-commitment plans, call POST {command_center_endpoint}; render the returned mandatory commitments and buttons.",
        "For direct health, weight, BMI, body fat, steps, active energy, or heart-rate questions, query /context/health first and only query other contexts if the answer needs training, food, or daily task state.",
        "For Sport, Food, and Daily advice, use health_progress and personalization from the relevant context; Do not overreact to one bad day, and do not invent trends when data_quality.has_trend is false.",
        "For Food, query /context/food, /food/target, /food/daily-summary, and /food/progress before calorie/protein advice; the V1 target is 1900 kcal and 150 g protein.",
        "If logging food, call POST /food/logs before claiming it is tracked.",
        "Never treat missing food logs as zero calories.",
        f"Food log replies should include {food_buttons} buttons using message.presentation.blocks.",
        "For Sport workout recommendations, call POST /sport/today and send the returned planned_workout with Telegram buttons using message.presentation.blocks.",
        f"Sport workout replies should include {workout_buttons} buttons.",
        "For Sport progress or goal questions, call GET /sport/progress.",
        "For missed training days, call POST /sport/missed-day.",
        "Respect personalization: city days default to morning gym/pool, grandparents days default to midday home training, avoid lateral raises, and use strict calorie/protein tracking for Food.",
        "Do not call /workouts/recommend for Telegram Sport workout requests.",
        "Never invent progress, balances, streaks, completed tasks, workouts, finance imports, or health data.",
        "Give coaching answers by default; give coding answers only in Admin or when explicitly asked.",
        "In Telegram group or forum-topic turns, send visible replies with the message tool to the same chat and topic; do not rely only on a private final answer.",
    ]
    return " ".join(sentences)


def render_config(contract: dict) -> str:
    config = json.loads(CONFIG_TARGET.read_text(encoding="utf-8"))
    config["agents"]["defaults"]["systemPromptOverride"] = render_system_prompt(contract)
    return json.dumps(config, indent=2, ensure_ascii=True) + "\n"


def ensure_ascii(path: Path, text: str) -> None:
    try:
        text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{path.relative_to(ROOT)} generated non-ASCII output") from exc


def desired_outputs(contract: dict) -> dict[Path, str]:
    generated_markdown = render_markdown(contract)
    outputs = {path: replace_marked_section(path, generated_markdown) for path in MARKDOWN_TARGETS}
    outputs[CONFIG_TARGET] = render_config(contract)
    for path, text in outputs.items():
        ensure_ascii(path, text)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Render OpenClue contract generated sections.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Fail if generated outputs are stale.")
    mode.add_argument("--write", action="store_true", help="Update generated outputs.")
    args = parser.parse_args()

    try:
        outputs = desired_outputs(load_contract())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    stale = [path for path, desired in outputs.items() if path.read_text(encoding="utf-8") != desired]

    if args.write:
        for path in stale:
            path.write_text(outputs[path], encoding="utf-8")
        if stale:
            for path in stale:
                print(f"updated {path.relative_to(ROOT)}")
        return 0

    if stale:
        print("stale generated OpenClue contract output:")
        for path in stale:
            print(f"- {path.relative_to(ROOT)}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
