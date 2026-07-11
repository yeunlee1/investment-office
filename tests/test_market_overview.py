# 미국과 한국 시장 개요의 병렬 조회와 실패 격리를 시험한다
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from investment_office.services.ecos_context import ECOS_SECTION_ID
from investment_office.services.macro_context import SECTION_TITLES, MacroContextResult
from investment_office.services.market_overview import MarketOverviewService
from investment_office.services.research_contracts import (
    Fact,
    MarketId,
    ResearchSection,
    SectionStatus,
)

OBSERVED_AT = datetime(2026, 7, 10, tzinfo=UTC)
PUBLISHED_AT = OBSERVED_AT + timedelta(hours=1)
COLLECTED_AT = PUBLISHED_AT + timedelta(minutes=1)

SIGNALS = {
    "treasury_2y": ("미국 국채 2년물 금리", "percent", 4.0, "macro.rates"),
    "treasury_3y": ("미국 국채 3년물 금리", "percent", 4.1, "macro.rates"),
    "treasury_10y": ("미국 국채 10년물 금리", "percent", 4.8, "macro.rates"),
    "treasury_10y_change": (
        "미국 국채 10년물 금리 30일 변화",
        "percentage_point",
        -0.1,
        "macro.rates",
    ),
    "curve_10y2y": (
        "미국 국채 10년물과 2년물 금리차",
        "percentage_point",
        0.8,
        "macro.rates",
    ),
    "broad_dollar_level": (
        "미 연준 광의 달러지수",
        "index_point",
        115.0,
        "macro.currency",
    ),
    "broad_dollar_change": (
        "미 연준 광의 달러지수 30일 변화",
        "percent",
        -2.0,
        "macro.currency",
    ),
    "usdkrw_level": ("원·달러 환율", "krw_per_usd", 1300.0, "macro.currency"),
    "usdkrw_change": (
        "원·달러 환율 30일 변화",
        "percent",
        -2.0,
        "macro.currency",
    ),
    "vix_level": ("VIX 종가", "index_point", 15.0, "macro.volatility"),
    "vix_change": ("VIX 종가 30일 변화", "percent", -10.0, "macro.volatility"),
    "wti_level": ("WTI 현물 가격", "usd_per_barrel", 70.0, "macro.commodities"),
    "wti_change": (
        "WTI 현물 가격 30일 변화",
        "percent",
        2.0,
        "macro.commodities",
    ),
    "brent_level": (
        "브렌트유 현물 가격",
        "usd_per_barrel",
        75.0,
        "macro.commodities",
    ),
    "brent_change": (
        "브렌트유 현물 가격 30일 변화",
        "percent",
        2.0,
        "macro.commodities",
    ),
    "bitcoin_level": (
        "비트코인 미국 달러 가격",
        "usd_per_bitcoin",
        60_000.0,
        "macro.liquidity",
    ),
    "bitcoin_change": (
        "비트코인 미국 달러 가격 30일 변화",
        "percent",
        15.0,
        "macro.liquidity",
    ),
    "cpi": (
        "미국 소비자물가지수",
        "index_1982_1984_100",
        320.0,
        "macro.growth_inflation",
    ),
}


class _Pipeline:
    def __init__(
        self,
        us: MacroContextResult | Exception,
        kr: MacroContextResult | Exception,
    ) -> None:
        self.results = {MarketId.US: us, MarketId.KR: kr}
        self.calls: list[MarketId] = []
        self.active = 0
        self.max_active = 0

    async def get_macro_context(
        self,
        market: MarketId | None = None,
    ) -> MacroContextResult:
        assert market is not None
        self.calls.append(market)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.01)
            result = self.results[market]
            if isinstance(result, Exception):
                raise result
            return result
        finally:
            self.active -= 1


def _fred_result(
    *,
    partial_section_id: str | None = None,
    stale_fact_ids: tuple[str, ...] = (),
) -> MacroContextResult:
    facts = tuple(
        Fact(
            fact_id=f"test:macro:{slug}",
            source_id="official:test:fred",
            metric=metric,
            value=value,
            unit=unit,
            observed_at=OBSERVED_AT,
            published_at=PUBLISHED_AT,
            collected_at=COLLECTED_AT,
        )
        for slug, (metric, unit, value, _) in SIGNALS.items()
    )
    fact_ids_by_section = {
        section_id: tuple(
            f"test:macro:{slug}"
            for slug, (_, _, _, fact_section_id) in SIGNALS.items()
            if fact_section_id == section_id
        )
        for section_id in SECTION_TITLES
    }
    sections = tuple(
        ResearchSection(
            section_id=section_id,
            title=title,
            status=(
                SectionStatus.PARTIAL
                if section_id == partial_section_id
                else SectionStatus.COMPLETE
            ),
            fact_ids=fact_ids_by_section[section_id],
            data_gaps=("일부 공통 거시 계열이 비어 있습니다.",)
            if section_id == partial_section_id
            else (),
        )
        for section_id, title in SECTION_TITLES.items()
    )
    return MacroContextResult(
        sources=(),
        facts=facts,
        sections=sections,
        stale_fact_ids=stale_fact_ids,
    )


def _korean_result(fred: MacroContextResult) -> MacroContextResult:
    ecos_fact = Fact(
        fact_id="test:macro:kr-base-rate",
        source_id="official:test:ecos",
        metric="한국은행 기준금리",
        value=2.5,
        unit="percent",
        observed_at=OBSERVED_AT,
        published_at=PUBLISHED_AT,
        collected_at=COLLECTED_AT,
    )
    ecos_section = ResearchSection(
        section_id=ECOS_SECTION_ID,
        title="한국 고유 거시 지표",
        status=SectionStatus.COMPLETE,
        fact_ids=(ecos_fact.fact_id,),
    )
    return MacroContextResult(
        sources=fred.sources,
        facts=(*fred.facts, ecos_fact),
        sections=(*fred.sections, ecos_section),
        stale_fact_ids=fred.stale_fact_ids,
        future_section_ids=fred.future_section_ids,
    )


@pytest.mark.asyncio
async def test_build_fetches_both_markets_in_parallel_and_keeps_common_fred_only() -> None:
    fred = _fred_result()
    pipeline = _Pipeline(fred, _korean_result(fred))
    service = MarketOverviewService(
        pipeline,
        now_factory=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    )

    overview = await service.build()
    payload = overview.model_dump(mode="json")

    assert pipeline.max_active == 2
    assert set(pipeline.calls) == {MarketId.US, MarketId.KR}
    assert overview.common.status == "ready"
    assert all(section.section_id != ECOS_SECTION_ID for section in overview.common.sections)
    assert all(fact.fact_id != "test:macro:kr-base-rate" for fact in overview.common.facts)
    assert overview.markets.us.market is MarketId.US
    assert overview.markets.kr.market is MarketId.KR
    assert overview.markets.us.confidence == 1
    assert overview.markets.kr.confidence == 1
    assert overview.markets.us.data_quality.analysis_eligible is True
    assert overview.markets.kr.data_quality.analysis_eligible is True
    assert set(payload) == {"generated_at", "common", "markets"}
    assert set(payload["markets"]) == {"us", "kr"}
    json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_incomplete_required_section_and_stale_fact_block_analysis() -> None:
    stale_id = "test:macro:vix_level"
    fred = _fred_result(
        partial_section_id="macro.currency",
        stale_fact_ids=(stale_id,),
    )
    service = MarketOverviewService(
        _Pipeline(fred, _korean_result(fred)),
        now_factory=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    )

    overview = await service.build()
    us_quality = overview.markets.us.data_quality

    assert overview.common.status == "degraded"
    assert us_quality.analysis_eligible is False
    assert us_quality.stale_fact_ids == (stale_id,)
    assert us_quality.blocked_section_ids == ("macro.currency",)
    assert any("완전하지 않습니다" in reason for reason in us_quality.blocking_reasons)
    assert any("허용 수명" in reason for reason in us_quality.blocking_reasons)
    assert "일부 공통 거시 계열이 비어 있습니다." in us_quality.warnings


@pytest.mark.asyncio
async def test_one_market_failure_is_isolated_and_does_not_expose_error_detail() -> None:
    fred = _fred_result()
    pipeline = _Pipeline(RuntimeError("secret-key-123"), _korean_result(fred))
    service = MarketOverviewService(
        pipeline,
        now_factory=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    )

    overview = await service.build()

    assert overview.common.status == "ready"
    assert overview.markets.us.data_quality.analysis_eligible is False
    assert set(overview.markets.us.data_quality.blocked_section_ids) == set(SECTION_TITLES)
    assert overview.markets.kr.data_quality.analysis_eligible is True
    assert any("RuntimeError" in warning for warning in overview.markets.us.warnings)
    assert all("secret-key-123" not in warning for warning in overview.markets.us.warnings)


@pytest.mark.asyncio
async def test_both_market_failures_return_degraded_overview_instead_of_raising() -> None:
    service = MarketOverviewService(
        _Pipeline(RuntimeError("미국 실패"), ValueError("한국 실패")),
        now_factory=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    )

    overview = await service.build()

    assert overview.common.status == "degraded"
    assert overview.common.facts == ()
    assert overview.markets.us.data_quality.analysis_eligible is False
    assert overview.markets.kr.data_quality.analysis_eligible is False
    assert ECOS_SECTION_ID in overview.markets.kr.data_quality.blocked_section_ids
    assert overview.markets.us.regime.rates.value == "unknown"
    assert overview.markets.kr.regime.rates.value == "unknown"
