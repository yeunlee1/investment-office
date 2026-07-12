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
CHART_DESK_SCRIPT = (STATIC / "chart-desk.js").read_text(encoding="utf-8")
DISCOVERY_SCRIPT = (STATIC / "discovery.js").read_text(encoding="utf-8")
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
    assert 'src="/static/hub.js?v=5"' in HUB


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
    assert 'src="/static/analysis.js?v=5"' in ANALYSIS
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
    assert '["schedule", "scheduled_analysis"].includes(eventType)' in ANALYSIS_SCRIPT
    assert "state.committee?.session_id !== sessionId" in ANALYSIS_SCRIPT


def test_chart_desk_is_accessible_and_responsive() -> None:
    assert 'id="decision-chart-analysis"' in ANALYSIS
    assert "차트 분석팀" in ANALYSIS
    assert 'from "./chart-desk.js?v=5"' in ANALYSIS_SCRIPT
    assert "export function renderChartDesk" in CHART_DESK_SCRIPT
    assert 'target.setAttribute("role", "region")' in CHART_DESK_SCRIPT
    assert 'target.setAttribute("aria-label", title)' in CHART_DESK_SCRIPT
    assert "chart.support_levels" in CHART_DESK_SCRIPT
    assert "chart.resistance_levels" in CHART_DESK_SCRIPT
    assert "chart.invalidation_levels" in CHART_DESK_SCRIPT
    assert "chart.as_of_date" in CHART_DESK_SCRIPT
    assert "chart.observations" in CHART_DESK_SCRIPT
    assert "chart.weekly_observations" in CHART_DESK_SCRIPT
    assert "lens.adaptation_notice" in CHART_DESK_SCRIPT
    assert "lens.metrics" in CHART_DESK_SCRIPT
    assert ".chart-desk__lens-grid" in STYLES
    assert ".chart-desk__metrics," in STYLES
    assert "grid-template-columns: minmax(0, 1fr);" in STYLES


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
    assert 'src="/static/history.js?v=5"' in HISTORY
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
    assert 'from "./chart-desk.js?v=5"' in HISTORY_SCRIPT
    assert "decision.chart_analysis" in HISTORY_SCRIPT
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
        "chart-desk.js",
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
    assert 'src="/static/markets.js?v=5"' in MARKETS
    assert 'href="/static/markets.css?v=3"' in MARKETS


def test_all_site_actions_publish_visible_operation_feedback() -> None:
    for field_id in (
        "site-operation-monitor",
        "site-operation-title",
        "site-operation-detail",
        "site-operation-event",
        "site-operation-status",
        "site-operation-elapsed",
        "site-operation-toggle",
        "site-operation-history",
        "site-operation-list",
    ):
        assert f'id="{field_id}"' in BASE
    assert 'aria-busy="false"' in BASE
    assert 'aria-live="polite"' in BASE
    assert 'export function startSiteOperation' in COMMON_SCRIPT
    assert 'export function setButtonBusy' in COMMON_SCRIPT
    assert 'Field required$/i.test(message)' in COMMON_SCRIPT
    assert '서버 내부 오류가 발생했습니다. 서버 로그를 확인하세요.' in COMMON_SCRIPT
    assert 'handleOperationEvent(payload, event.type)' in COMMON_SCRIPT
    assert '"scheduled_analysis"' in COMMON_SCRIPT
    assert 'source.addEventListener("open"' in COMMON_SCRIPT
    assert "restoreActiveScheduledOperations(attempt + 1)" in COMMON_SCRIPT
    assert (
        'trackTasks(tasks, detail = "담당 에이전트가 업무를 실행하고 있습니다.")'
        in COMMON_SCRIPT
    )
    assert 'window.sessionStorage.setItem(OPERATION_STORAGE_KEY' in COMMON_SCRIPT
    assert ANALYSIS_SCRIPT.count("startSiteOperation({") >= 9
    assert DISCOVERY_SCRIPT.count("startSiteOperation({") >= 2
    assert MARKETS_SCRIPT.count("startSiteOperation({") >= 1
    assert HISTORY_SCRIPT.count("startSiteOperation({") >= 2
    assert 'classifyDiscoveryOutcome' in DISCOVERY_SCRIPT
    assert 'evaluatedCount === 0' in COMMON_SCRIPT
    assert '실제 평가는 0건입니다' in COMMON_SCRIPT
    assert '.operation-monitor[data-state="running"]' in STYLES
