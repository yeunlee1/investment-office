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
        "discovery-risk-profile",
        "discovery-feedback",
        "discovery-universe",
        "discovery-fundamentals",
        "discovery-liquidity",
        "discovery-shortlist",
        "discovery-candidate-list",
        "discovery-analyze-form",
        "discovery-analyze",
        "discovery-run-list",
        "discovery-run-feedback",
    ):
        assert f'id="{field_id}"' in TEMPLATE
    for stage in (
        "universe",
        "fundamentals",
        "liquidity",
        "sector",
        "ranking",
        "agents",
        "review",
    ):
        assert f'data-discovery-stage="{stage}"' in TEMPLATE
    assert TEMPLATE.count('data-stage-field="processed"') == 5
    assert TEMPLATE.count('data-stage-field="passed"') == 5
    assert TEMPLATE.count('data-stage-field="failed"') == 5
    assert TEMPLATE.count('data-stage-field="cached"') == 5
    assert 'name="risk_profile"' in TEMPLATE
    for risk_profile in ("defensive", "balanced", "aggressive"):
        assert f'value="{risk_profile}"' in TEMPLATE
    assert 'src="/static/discovery.js?v=7"' in TEMPLATE
    assert 'from "./site-common.js?v=7"' in SCRIPT


def test_discovery_page_starts_from_each_market_full_common_stock_ledger() -> None:
    assert "미국은 전체 상장 보통주" in TEMPLATE
    assert "KOSPI·KOSDAQ 전체 보통주" in TEMPLATE
    assert "재무 우선 다단계 필터" in TEMPLATE
    for stale_copy in ("30종목", "대표주", "대형주"):
        assert stale_copy not in TEMPLATE
        assert stale_copy not in SCRIPT


def test_discovery_page_uses_server_history_instead_of_browser_only_state() -> None:
    assert 'discoveryAnalyze: "/api/discoveries/analyze"' in (
        PACKAGE_ROOT / "static" / "site-common.js"
    ).read_text(encoding="utf-8")
    assert 'const DISCOVERY_SCAN_ENDPOINT = "/api/discoveries/scans"' in SCRIPT
    assert "const SCAN_POLL_INTERVAL = 900" in SCRIPT
    assert "JSON.stringify({ market, strategy, risk_profile: riskProfile, limit: 8 })" in SCRIPT
    assert "`${DISCOVERY_SCAN_ENDPOINT}/${encodeURIComponent(jobId)}`" in SCRIPT
    assert "window.setTimeout(pollScanJob, delay)" in SCRIPT
    assert "job?.result" in SCRIPT
    assert 'status === "failed"' in SCRIPT
    assert 'status === "partial"' in SCRIPT
    assert "const firstIncompleteStage = BACKEND_STAGES.find" in SCRIPT
    assert "const failedStage = currentStage || firstIncompleteStage" in SCRIPT
    assert "job?.error || job?.message || stage?.message" in SCRIPT
    assert "renderBackendStages(job)" in SCRIPT
    assert "stage?.message" in SCRIPT
    assert "JSON.stringify({ market, tickers })" in SCRIPT
    assert "?workflow=discovery&limit=200" in SCRIPT
    assert "discovery_batch_id" in SCRIPT
    assert "localStorage" not in SCRIPT
    assert 'includes(eventType)) scheduleEventRefresh()' in SCRIPT
    assert "preventScroll: true" in SCRIPT
    assert '심층 분석 진행률`' in SCRIPT


def test_discovery_page_distinguishes_failed_and_partial_zero_results() -> None:
    assert "전체시장 스캔을 완료하지 못했습니다." in SCRIPT
    assert "자료 공백으로 후보를 확정하지 못했습니다." in SCRIPT
    assert "현재 표시값을 정상 완료 결과로 해석하지 마세요." in SCRIPT
    assert "정상 완료로 처리하지 않았습니다." in SCRIPT
    assert 'setFeedback(elements.feedback, `후보 스캔 실패.' in SCRIPT
    assert 'setFeedback(elements.feedback, `후보 스캔 일부 완료.' in SCRIPT


def test_discovery_page_limits_selection_and_links_to_full_workbench() -> None:
    assert "selected.length > 3" in SCRIPT
    assert 'name = "discovery-ticker"' in SCRIPT
    assert 'href = `/analysis?run=${encodeURIComponent(run.run_id)}`' in SCRIPT
    assert 'href = `/history?run=${encodeURIComponent(run.run_id)}`' in SCRIPT
    assert "자동 주문은 생성되지 않습니다" in SCRIPT
    assert "candidate.company_name" in SCRIPT
    assert '"candidate-card__name"' in SCRIPT
    assert '"candidate-card__symbol"' in SCRIPT
    assert "candidate.breakdown" in SCRIPT
    assert '"candidate-card__breakdown"' in SCRIPT
    for score_label in ("재무", "성장", "업종", "업종전망", "차트"):
        assert f'["{score_label}",' in SCRIPT
    assert "checkbox.setAttribute(\"aria-label\"" in SCRIPT
    assert "run.company_name" in SCRIPT
    assert (
        "storedCompanyName && ticker && storedCompanyName.toUpperCase() !== ticker.toUpperCase()"
        in SCRIPT
    )
    assert "사람 검토" in TEMPLATE
    assert "자동 주문 없음" in TEMPLATE


def test_discovery_markup_is_unique_and_responsive() -> None:
    ids = re.findall(r'\bid="([^"]+)"', TEMPLATE)
    assert len(ids) == len(set(ids))
    assert ".discovery-run-list" in STYLES
    assert ".candidate-card" in STYLES
    assert ".candidate-card__name" in STYLES
    assert ".candidate-card__symbol" in STYLES
    assert ".candidate-card__breakdown" in STYLES
    assert ".stage-card__telemetry" in STYLES
    assert ".stage-card__message" in STYLES
    assert "@media (max-width: 1020px)" in STYLES
    assert "@media (max-width: 760px)" in STYLES
    tablet_styles = STYLES.split("@media (max-width: 1020px)", 1)[1].split(
        "@media (max-width: 760px)", 1
    )[0]
    assert ".discovery-run-list" in tablet_styles
    assert ".stage-list" in tablet_styles
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in tablet_styles
    header_rule = re.search(r"\.discovery-run-card__header\s*\{([^}]*)\}", STYLES)
    assert header_rule is not None
    assert "flex-wrap: wrap;" in header_rule.group(1)
