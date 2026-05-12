from __future__ import annotations

import subprocess
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
MAIN_PATH = API_ROOT / "src" / "lifeos_api" / "main.py"
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify.sh"
CURRENT_MAIN_MONOLITH_LINE_CAP = 2489
ALLOWED_IGNORED_TRACKED_FILES: set[str] = set()


def ignored_tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-ci", "--exclude-standard"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.splitlines()


def test_main_module_stays_within_current_monolith_limit():
    line_count = len(MAIN_PATH.read_text(encoding="utf-8").splitlines())

    # Extraction work should move code out of main.py before adding replacement structure.
    assert line_count <= CURRENT_MAIN_MONOLITH_LINE_CAP


def test_create_app_remains_importable_during_refactor():
    from lifeos_api.main import create_app

    assert callable(create_app)


def test_runtime_artifacts_are_not_tracked():
    tracked_artifacts = sorted(
        set(ignored_tracked_files()) - ALLOWED_IGNORED_TRACKED_FILES
    )

    assert tracked_artifacts == []


def test_verify_script_runs_architecture_guard_tests():
    verify_contents = VERIFY_SCRIPT.read_text(encoding="utf-8")

    assert "uv run pytest tests/test_architecture.py" in verify_contents
