# 2D 투자 사무실의 정적 계약과 안전 경계를 검증한다.
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "investment_office"
SCRIPT = (PACKAGE_ROOT / "static" / "office.js").read_text(encoding="utf-8")
TEMPLATE = (PACKAGE_ROOT / "templates" / "office.html").read_text(encoding="utf-8")


def test_office_game_exposes_required_world_contract() -> None:
    assert 'id="office-canvas"' in TEMPLATE
    assert 'id="interaction-dialog"' in TEMPLATE
    assert 'data-control="interact"' in TEMPLATE
    assert 'src="/static/office.js?v=8"' in TEMPLATE
    assert 'Object.defineProperty(window, "__OFFICE_DEBUG__"' in SCRIPT
    for zone in ("intake", "fundamental", "technical", "news", "bull", "bear", "chair"):
        assert f'id: "{zone}"' in SCRIPT


def test_office_game_uses_existing_human_gate_apis() -> None:
    for endpoint in ("/api/state", "/api/analyze", "/api/events", "/api/runs/"):
        assert endpoint in SCRIPT
    assert 'approve: "approved"' in SCRIPT
    assert 'hold: "deferred"' in SCRIPT
    assert 'reject: "rejected"' in SCRIPT
    assert "broker" not in SCRIPT.casefold()
    assert "auto_trade" not in SCRIPT.casefold()


def test_office_game_supports_keyboard_mobile_and_reduced_motion() -> None:
    for key in ("arrowleft", "arrowright", "arrowup", "arrowdown", '"w"', '"a"', '"s"', '"d"'):
        assert key in SCRIPT
    assert 'document.querySelectorAll("[data-control]")' in SCRIPT
    assert "prefers-reduced-motion: reduce" in SCRIPT
    assert 'window.localStorage.setItem(\n        "pixel-office-player"' in SCRIPT


def test_office_game_exposes_kst_one_time_analysis_schedules() -> None:
    for field_id in (
        "schedule-analysis-form",
        "schedule-ticker",
        "schedule-time",
        "schedule-thesis",
        "schedule-list",
    ):
        assert f'id="{field_id}"' in TEMPLATE
    assert 'type="datetime-local"' in TEMPLATE
    assert 'schedules: "/api/schedules"' in SCRIPT
    assert "/api/schedules/${encodeURIComponent(scheduleId)}/cancel" in SCRIPT
    assert "scheduled_for: scheduledFor" in SCRIPT
    assert "+09:00" in SCRIPT
    assert "자동 주문 없음" in TEMPLATE


def test_office_game_exposes_prior_decision_card_archive() -> None:
    assert 'id="decision-archive-list"' in TEMPLATE
    assert 'id="decision-archive-refresh"' in TEMPLATE
    assert 'decisions: "/api/decisions?limit=50"' in SCRIPT
    assert "/api/decisions/${encodeURIComponent(runId)}" in SCRIPT
    for field in ("STATUS", "CONFIDENCE", "HUMAN REVIEW", "SCHEDULE"):
        assert field in SCRIPT
    assert "review.rationale" in SCRIPT
    assert "실패 원인 · ${error}" in SCRIPT
    assert "카드 최신 상태 새로고침" in SCRIPT


def test_office_game_exposes_human_selected_stock_discovery() -> None:
    for field_id in (
        "discovery-screen-form",
        "discovery-strategy",
        "discovery-candidate-list",
        "discovery-analyze-form",
        "discovery-run-list",
    ):
        assert f'id="{field_id}"' in TEMPLATE
    for strategy in ("balanced", "momentum", "defensive"):
        assert f'value="{strategy}"' in TEMPLATE
    assert 'discoveryScreen: "/api/discoveries/screen"' in SCRIPT
    assert 'discoveryAnalyze: "/api/discoveries/analyze"' in SCRIPT
    assert "JSON.stringify({ strategy, limit: 8 })" in SCRIPT
    assert "JSON.stringify({ tickers })" in SCRIPT
    assert "selected.length === 0" in SCRIPT
    assert "excludedItem.reasons.filter(Boolean).join" in SCRIPT
    assert "scheduleDiscoveryPolling" in SCRIPT
    assert "pixel-office-discovery-runs" in SCRIPT
    assert "120_000" in SCRIPT
    assert "자동 주문 없음" in TEMPLATE
    assert "매수 추천이나 수익 보장이 아닙니다" in TEMPLATE
