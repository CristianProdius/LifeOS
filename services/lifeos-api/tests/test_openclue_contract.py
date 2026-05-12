from __future__ import annotations

from pathlib import Path

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

