# 분리된 사이트 허브와 개별분석, 완료이력 페이지의 기능 계약을 검증한다.
import re
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "investment_office"
TEMPLATES = PACKAGE_ROOT / "templates"
STATIC = PACKAGE_ROOT / "static"
BASE = (TEMPLATES / "base.html").read_text(encoding="utf-8")
HUB = (TEMPLATES / "index.html").read_text(encoding="utf-8")
ANALYSIS = (TEMPLATES / "analysis.html").read_text(encoding="utf-8")
MARKETS = (TEMPLATES / "markets.html").read_text(encoding="utf-8")
HISTORY = (TEMPLATES / "history.html").read_text(encoding="utf-8")
ANALYSIS_SCRIPT = (STATIC / "analysis.js").read_text(encoding="utf-8")
MARKETS_SCRIPT = (STATIC / "markets.js").read_text(encoding="utf-8")
HISTORY_SCRIPT = (STATIC / "history.js").read_text(encoding="utf-8")
COMMON_SCRIPT = (STATIC / "site-common.js").read_text(encoding="utf-8")
STYLES = (STATIC / "site.css").read_text(encoding="utf-8")


def test_site_uses_summary_hub_and_four_clear_pages() -> None:
    for href in ("/markets", "/analysis", "/discovery", "/history"):
        assert f'href="{href}"' in BASE
    assert 'href="/office"' not in BASE
    for field_id in (
        "hub-total",
        "hub-active",
        "hub-review",
        "hub-scheduled",
        "hub-manual-runs",
        "hub-discovery-runs",
        "hub-recent-runs",
    ):
        assert f'id="{field_id}"' in HUB
    assert 'src="/static/hub.js?v=1"' in HUB


def test_individual_page_exposes_all_site_operations() -> None:
    required_ids = (
        "individual-analysis-form",
        "individual-market",
        "schedule-form",
        "schedule-market",
        "schedule-list",
        "analysis-run-list",
        "agent-strip",
        "agent-reports",
        "task-form",
        "task-list",
        "committee-start-form",
        "committee-command-form",
        "committee-timeline",
        "committee-ledger",
        "committee-minutes",
        "decision-card",
        "review-form",
    )
    for field_id in required_ids:
        assert f'id="{field_id}"' in ANALYSIS
    for tab in ("agents", "tasks", "committee", "decision"):
        assert f'data-workbench-tab="{tab}"' in ANALYSIS
    assert 'document.querySelectorAll("[role=\'tabpanel\'][id^=\'workbench-\']")' in ANALYSIS_SCRIPT
    assert 'addEventListener("keydown", handleTabKeydown)' in ANALYSIS_SCRIPT
    assert 'setAttribute("aria-valuenow"' in ANALYSIS_SCRIPT
    assert 'type="submit" data-review-decision=' not in ANALYSIS
    assert ANALYSIS.count('type="button" data-review-decision=') == 3
    assert 'src="/static/analysis.js?v=1"' in ANALYSIS
    assert "{ market, ticker, thesis }" in ANALYSIS_SCRIPT
    assert "{ market, ticker, scheduled_for:" in ANALYSIS_SCRIPT


def test_individual_page_connects_every_existing_operation_api() -> None:
    for contract in (
        "API.analyze",
        "API.schedules",
        "API.cancelSchedule",
        "API.tasks",
        "API.taskReport",
        "API.taskResume",
        "API.taskCancel",
        "API.startCommittee",
        "API.committeeCommands",
        "API.committeeMinutes",
        "API.review",
    ):
        assert contract in ANALYSIS_SCRIPT
    assert "저장된 최신 업무 상태" in ANALYSIS_SCRIPT
    assert "Object.keys(result).length ? result : progress" in ANALYSIS_SCRIPT
    assert "preventScroll: true" in ANALYSIS_SCRIPT
    assert '.catch(() => ({ tasks: [] }))' not in ANALYSIS_SCRIPT
    assert 'eventType === "schedule"' in ANALYSIS_SCRIPT
    assert "state.committee?.session_id !== sessionId" in ANALYSIS_SCRIPT


def test_history_page_filters_and_lazily_loads_saved_detail() -> None:
    for field_id in (
        "history-filter-form",
        "history-workflow",
        "history-status",
        "history-ticker",
        "history-period",
        "history-list",
        "history-detail",
    ):
        assert f'id="{field_id}"' in HISTORY
    assert 'src="/static/history.js?v=1"' in HISTORY
    assert "`${API.runs}?limit=200`" in HISTORY_SCRIPT
    for contract in (
        "API.run(runId)",
        "API.tasks(runId)",
        "API.runCommittee(runId)",
        "API.decision(runId)",
    ):
        assert contract in HISTORY_SCRIPT
    assert "API.committeeMinutes" in HISTORY_SCRIPT
    assert 'query.get("workflow")' in HISTORY_SCRIPT
    assert 'title.id = "history-detail-title"' in HISTORY_SCRIPT
    assert '.catch(() => ({ tasks: [] }))' not in HISTORY_SCRIPT
    assert "preventScroll: true" in HISTORY_SCRIPT
    assert "payload.run_id === state.selectedRunId" in HISTORY_SCRIPT
    hub_script = (STATIC / "hub.js").read_text(encoding="utf-8")
    assert 'summary?.by_status' in hub_script
    assert "preventScroll: true" in hub_script


def test_site_templates_have_unique_ids_and_accessible_responsive_styles() -> None:
    for template in (BASE, HUB, MARKETS, ANALYSIS, HISTORY):
        ids = re.findall(r'\bid="([^"]+)"', template)
        assert len(ids) == len(set(ids))
    assert ":focus-visible" in STYLES
    assert "prefers-reduced-motion" in STYLES
    assert "forced-colors" in STYLES
    assert "@media (max-width: 1020px)" in STYLES
    assert "@media (max-width: 500px)" in STYLES
    assert 'site-live-region' in BASE
    assert 'aria-live="polite"' in MARKETS
    assert "prefers-reduced-motion" in (STATIC / "markets.css").read_text(encoding="utf-8")


def test_new_site_source_files_start_with_korean_role_headers() -> None:
    source_files = (
        "site-common.js",
        "hub.js",
        "markets.js",
        "analysis.js",
        "discovery.js",
        "history.js",
    )
    for name in source_files:
        first_line = (STATIC / name).read_text(encoding="utf-8").splitlines()[0]
        assert first_line.startswith("// ")
        assert re.search(r"[가-힣]", first_line)
    assert re.search(r"[가-힣]", (STATIC / "site.css").read_text(encoding="utf-8").splitlines()[0])
    assert 'runs: "/api/runs"' in COMMON_SCRIPT
    assert 'marketOverview: "/api/markets/overview"' in COMMON_SCRIPT
    assert 'dataSources: "/api/data-sources"' in COMMON_SCRIPT


def test_market_control_room_exposes_cross_market_quality_contract() -> None:
    for field_id in (
        "markets-refresh",
        "common-macro-list",
        "market-panel-us",
        "market-panel-kr",
        "market-us-regime",
        "market-kr-regime",
        "market-us-quality",
        "market-kr-quality",
        "source-table-body",
    ):
        assert f'id="{field_id}"' in MARKETS
    assert "requestJson(API.marketOverview)" in MARKETS_SCRIPT
    assert "requestJson(API.dataSources)" in MARKETS_SCRIPT
    assert 'Promise.allSettled' in MARKETS_SCRIPT
    assert 'quality?.macro_eligible === true' in MARKETS_SCRIPT
    assert 'src="/static/markets.js?v=1"' in MARKETS
    assert 'href="/static/markets.css?v=3"' in MARKETS
