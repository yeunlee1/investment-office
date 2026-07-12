# 전역 작업 피드백의 자바스크립트 실행과 정적 자산 버전을 검증한다.
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
STATIC = ROOT / "src" / "investment_office" / "static"
TEMPLATES = ROOT / "src" / "investment_office" / "templates"


def test_site_feedback_javascript_runs_state_transitions() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("자바스크립트 실행 검증에 Node.js가 필요합니다.")
    completed = subprocess.run(
        [node, str(ROOT / "tests" / "site_feedback_runtime.mjs")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "전역 작업 피드백 자바스크립트 실행 검증 통과" in completed.stdout


def test_site_static_asset_versions_are_synchronized() -> None:
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    css_version = re.search(r'/static/site\.css\?v=(\d+)', base)
    assert css_version is not None
    assert css_version.group(1) == "4"

    for name in ("hub", "markets", "analysis", "discovery", "history"):
        template = (TEMPLATES / f"{name if name != 'hub' else 'index'}.html").read_text(
            encoding="utf-8"
        )
        script = (STATIC / f"{name}.js").read_text(encoding="utf-8")
        template_version = re.search(rf'/static/{name}\.js\?v=(\d+)', template)
        import_version = re.search(r'\./site-common\.js\?v=(\d+)', script)
        assert template_version is not None
        assert import_version is not None
        assert template_version.group(1) == import_version.group(1) == "4"
