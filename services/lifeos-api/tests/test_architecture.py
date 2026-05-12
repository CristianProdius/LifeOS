from __future__ import annotations

import subprocess
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
MAIN_PATH = API_ROOT / "src" / "lifeos_api" / "main.py"
APP_PATH = API_ROOT / "src" / "lifeos_api" / "app.py"
ROUTES_DIR = API_ROOT / "src" / "lifeos_api" / "api" / "routes"
DOMAIN_DIR = API_ROOT / "src" / "lifeos_api" / "domain"
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify.sh"
MAIN_COMPATIBILITY_SHIM_LINE_CAP = 20
APP_COMPOSITION_LINE_CAP = 120
ROUTE_MODULE_LINE_CAP = 220
ROUTES_WITH_DOMAIN_BOUNDARY = {"context.py", "daily.py", "finance.py"}
DISALLOWED_ROUTE_BOUNDARY_SNIPPETS = (
    "from lifeos_api.models",
    "import lifeos_api.models",
    "from sqlalchemy import ",
    "session.add(",
    ".commit(",
    ".flush(",
)
DISALLOWED_DOMAIN_SNIPPETS = ("from fastapi", "import fastapi", "fastapi.")
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


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_main_module_stays_a_compatibility_shim():
    line_count = len(MAIN_PATH.read_text(encoding="utf-8").splitlines())

    assert line_count <= MAIN_COMPATIBILITY_SHIM_LINE_CAP
    assert MAIN_PATH.read_text(encoding="utf-8").strip() == (
        'from lifeos_api.app import create_app\n\n__all__ = ["create_app"]'
    )


def test_app_module_stays_composition_sized():
    assert line_count(APP_PATH) <= APP_COMPOSITION_LINE_CAP


def test_route_modules_stay_thin():
    route_lengths = {
        path.relative_to(API_ROOT).as_posix(): line_count(path)
        for path in ROUTES_DIR.glob("*.py")
    }

    assert route_lengths
    assert {
        route: lines
        for route, lines in route_lengths.items()
        if lines > ROUTE_MODULE_LINE_CAP
    } == {}


def test_cleaned_routes_do_not_reintroduce_database_logic():
    violations = {}
    for path in sorted(ROUTES_DIR.glob("*.py")):
        if path.name not in ROUTES_WITH_DOMAIN_BOUNDARY:
            continue
        text = path.read_text(encoding="utf-8")
        matches = [snippet for snippet in DISALLOWED_ROUTE_BOUNDARY_SNIPPETS if snippet in text]
        if matches:
            violations[path.name] = matches

    assert violations == {}


def test_domain_modules_do_not_depend_on_fastapi():
    violations = {}
    for path in sorted(DOMAIN_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        matches = [snippet for snippet in DISALLOWED_DOMAIN_SNIPPETS if snippet in text]
        if matches:
            violations[path.name] = matches

    assert violations == {}


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
