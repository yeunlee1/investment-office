# 독립 종목추천 페이지의 선별과 서버 기반 완료 이력 계약을 검증한다.
import re
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "investment_office"
SCRIPT = (PACKAGE_ROOT / "static" / "discovery.js").read_text(encoding="utf-8")
STYLES = (PACKAGE_ROOT / "static" / "site.css").read_text(encoding="utf-8")
TEMPLATE = (PACKAGE_ROOT / "templates" / "discovery.html").read_text(encoding="utf-8")


def test_discovery_page_exposes_stock_recommendation_pipeline() -> None:
    for field_id in (
        "discovery-screen-form",
        "discovery-market",
        "discovery-strategy",
        "discovery-feedback",
        "discovery-candidate-list",
        "discovery-analyze-form",
        "discovery-analyze",
        "discovery-run-list",
        "discovery-run-feedback",
    ):
        assert f'id="{field_id}"' in TEMPLATE
    for stage in ("scan", "shortlist", "agents", "review"):
        assert f'data-discovery-stage="{stage}"' in TEMPLATE
    assert 'src="/static/discovery.js?v=1"' in TEMPLATE


def test_discovery_page_uses_server_history_instead_of_browser_only_state() -> None:
    assert 'discoveryScreen: "/api/discoveries/screen"' in (
        PACKAGE_ROOT / "static" / "site-common.js"
    ).read_text(encoding="utf-8")
    assert 'discoveryAnalyze: "/api/discoveries/analyze"' in (
        PACKAGE_ROOT / "static" / "site-common.js"
    ).read_text(encoding="utf-8")
    assert "JSON.stringify({ market, strategy, limit: 8 })" in SCRIPT
    assert "JSON.stringify({ market, tickers })" in SCRIPT
    assert "?workflow=discovery&limit=200" in SCRIPT
    assert "discovery_batch_id" in SCRIPT
    assert "localStorage" not in SCRIPT
    assert 'includes(eventType)) scheduleEventRefresh()' in SCRIPT
    assert "preventScroll: true" in SCRIPT
    assert '심층 분석 진행률`' in SCRIPT


def test_discovery_page_limits_selection_and_links_to_full_workbench() -> None:
    assert "selected.length > 3" in SCRIPT
    assert 'name = "discovery-ticker"' in SCRIPT
    assert 'href = `/analysis?run=${encodeURIComponent(run.run_id)}`' in SCRIPT
    assert 'href = `/history?run=${encodeURIComponent(run.run_id)}`' in SCRIPT
    assert "자동 주문은 생성되지 않습니다" in SCRIPT
    assert "사람 검토" in TEMPLATE
    assert "자동 주문 없음" in TEMPLATE


def test_discovery_markup_is_unique_and_responsive() -> None:
    ids = re.findall(r'\bid="([^"]+)"', TEMPLATE)
    assert len(ids) == len(set(ids))
    assert ".discovery-run-list" in STYLES
    assert ".candidate-card" in STYLES
    assert "@media (max-width: 1020px)" in STYLES
    assert "@media (max-width: 760px)" in STYLES
