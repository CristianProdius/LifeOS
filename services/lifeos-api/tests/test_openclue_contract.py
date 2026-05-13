from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


def load_renderer(repo_root: Path):
    renderer_path = repo_root / "scripts/render-openclue-contract.py"
    spec = importlib.util.spec_from_file_location("render_openclue_contract", renderer_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    original_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = original_dont_write_bytecode
    return module


def test_openclue_contract_generated_outputs_are_fresh():
    repo_root = Path(__file__).resolve().parents[3]

    result = subprocess.run(
        ["python3", "scripts/render-openclue-contract.py", "--check"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_openclue_contract_renderer_tracks_expected_outputs():
    repo_root = Path(__file__).resolve().parents[3]
    renderer = load_renderer(repo_root)
    outputs = renderer.desired_outputs(renderer.load_contract())

    assert set(outputs) == {
        repo_root / "openclaw/workspace/AGENTS.md",
        repo_root / "openclaw/workspace/skills/lifeos/SKILL.md",
        repo_root / "openclaw/config/openclaw.template.json",
    }


def test_openclue_contract_renderer_preserves_markdown_outside_markers(tmp_path):
    repo_root = Path(__file__).resolve().parents[3]
    renderer = load_renderer(repo_root)
    target = tmp_path / "contract.md"
    before = "# Handwritten\n\nKeep trailing spaces.  \n"
    after = "\n\nKeep footer spacing.  \n"
    generated = f"{renderer.BEGIN}\nnew generated content\n{renderer.END}"
    target.write_text(f"{before}{renderer.BEGIN}\nstale\n{renderer.END}{after}", encoding="utf-8")

    replaced = renderer.replace_marked_section(target, generated)

    assert replaced == f"{before}{generated}{after}"


def test_openclue_contract_renderer_rejects_duplicate_markers(tmp_path):
    repo_root = Path(__file__).resolve().parents[3]
    renderer = load_renderer(repo_root)
    target = tmp_path / "contract.md"
    target.write_text(
        f"{renderer.BEGIN}\nstale\n{renderer.END}\n{renderer.BEGIN}\nstale\n{renderer.END}",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="exactly one generated contract marker pair"):
        renderer.replace_marked_section(target, "generated")


def test_openclue_prompts_and_docs_reference_health_progress_contract():
    repo_root = Path(__file__).resolve().parents[3]
    agents = (repo_root / "openclaw/workspace/AGENTS.md").read_text()
    skill = (repo_root / "openclaw/workspace/skills/lifeos/SKILL.md").read_text()
    config = (repo_root / "openclaw/config/openclaw.template.json").read_text()
    shortcut_docs = (repo_root / "docs/shortcut-health-ingestion.md").read_text()

    for text in [agents, skill, config]:
        assert "health_progress" in text
        assert "/context/health" in text
        assert "Do not overreact to one bad day" in text
    assert '"thinkingDefault": "low"' in config
    assert '"fastModeDefault": true' in config
    assert "sleep_duration_minutes" not in shortcut_docs
    assert "workouts_count" not in shortcut_docs
    assert "Xiaomi scale" in shortcut_docs


def test_openclue_uses_sport_program_engine_for_sport_workouts():
    repo_root = Path(__file__).resolve().parents[3]
    agents = (repo_root / "openclaw/workspace/AGENTS.md").read_text()
    skill = (repo_root / "openclaw/workspace/skills/lifeos/SKILL.md").read_text()
    config = (repo_root / "openclaw/config/openclaw.template.json").read_text()
    setup_docs = (repo_root / "docs/openclaw-openclue-setup.md").read_text()

    for text in [agents, skill, config, setup_docs]:
        assert "/sport/today" in text
        assert "/sport/progress" in text
        assert "/sport/missed-day" in text
        assert "personalization" in text
        assert "lateral raises" in text
        assert "strict calorie" in text
        assert "city days" in text
    assert "Do not call /workouts/recommend for Telegram Sport" in skill
    assert "mutating endpoints are not generic reads" in config
    assert "do not call it for general Sport questions" in config
    assert "query /context/sport first, use health_progress plus recent workouts" not in config


def test_openclue_prompts_reference_food_calorie_protein_engine():
    repo_root = Path(__file__).resolve().parents[3]
    agents = (repo_root / "openclaw/workspace/AGENTS.md").read_text()
    skill = (repo_root / "openclaw/workspace/skills/lifeos/SKILL.md").read_text()
    config = (repo_root / "openclaw/config/openclaw.template.json").read_text()
    setup_docs = (repo_root / "docs/openclaw-openclue-setup.md").read_text()

    for text in [agents, skill, config, setup_docs]:
        assert "/food/target" in text
        assert "/food/daily-summary" in text
        assert "/food/progress" in text
        assert "POST /food/logs" in text
        assert "Never treat missing food logs as zero calories" in text
        assert "1900 kcal" in text
        assert "150 g protein" in text
    assert "Looks right" in config
    assert "Edit calories" in config
    assert "Add protein" in config
    assert "Delete" in config


def test_openclue_prompts_reference_deterministic_actions_and_command_center():
    repo_root = Path(__file__).resolve().parents[3]
    agents = (repo_root / "openclaw/workspace/AGENTS.md").read_text()
    skill = (repo_root / "openclaw/workspace/skills/lifeos/SKILL.md").read_text()
    config = (repo_root / "openclaw/config/openclaw.template.json").read_text()
    setup_docs = (repo_root / "docs/openclaw-openclue-setup.md").read_text()

    for text in [agents, skill, config, setup_docs]:
        assert "/telegram/actions" in text
        assert "/daily/command-center" in text
    for text in [agents, skill, config]:
        assert "submit Telegram callback values unchanged" in text
