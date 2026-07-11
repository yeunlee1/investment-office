# 연구 파이프라인의 병렬 수집, 품질 차단, 시장별 공백과 캐시를 검증한다
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest
from pydantic import AnyHttpUrl

from investment_office.services.company_research import CompanyResearchResult
from investment_office.services.ecos_context import EcosContextResult
from investment_office.services.macro_context import MacroContextResult
from investment_office.services.market_data import EODSnapshot
from investment_office.services.market_regime import MarketRegimeEvaluator, RegimeState
from investment_office.services.research_contracts import (
    Fact,
    InstrumentRef,
    MarketId,
    ResearchSection,
    SectionStatus,
    SourceRef,
    SourceTier,
)
from investment_office.services.research_pipeline import (
    INDEPENDENT_NEWS_SECTION_ID,
    PRICE_CORE_SECTION_ID,
    PRICE_TECHNICAL_SECTION_ID,
    VALUATION_SECTION_ID,
    ResearchPipeline,
)

COLLECTED_AT = datetime(2026, 7, 12, 9, 30, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 7, 10, tzinfo=UTC)
PUBLISHED_AT = datetime(2026, 7, 10, 1, tzinfo=UTC)


class _MacroClient:
    def __init__(self, result: MacroContextResult, probe: _ParallelProbe | None = None) -> None:
        self.result = result
        self.probe = probe
        self.calls = 0

    async def fetch(self) -> MacroContextResult:
        self.calls += 1
        if self.probe is not None:
            await self.probe.arrive()
        return self.result


class _FailingMacroClient:
    def __init__(self, probe: _ParallelProbe) -> None:
        self.probe = probe
        self.calls = 0

    async def fetch(self) -> MacroContextResult:
        self.calls += 1
        await self.probe.arrive()
        raise RuntimeError("고정 대역 실패")


class _CompanyClient:
    def __init__(
        self,
        result: CompanyResearchResult,
        probe: _ParallelProbe | None = None,
    ) -> None:
        self.result = result
        self.probe = probe
        self.cutoffs: list[datetime] = []

    async def fetch(
        self,
        instrument: InstrumentRef,
        *,
        cutoff: datetime,
        business_year: int | None = None,
        report_code: str = "11011",
    ) -> CompanyResearchResult:
        del instrument, business_year, report_code
        self.cutoffs.append(cutoff)
        if self.probe is not None:
            await self.probe.arrive()
        return self.result


class _FailingCompanyClient:
    async def fetch(
        self,
        instrument: InstrumentRef,
        *,
        cutoff: datetime,
        business_year: int | None = None,
        report_code: str = "11011",
    ) -> CompanyResearchResult:
        del instrument, cutoff, business_year, report_code
        raise RuntimeError("고정 회사 자료 실패")


class _EcosClient:
    def __init__(self, result: EcosContextResult) -> None:
        self.result = result
        self.calls = 0

    async def fetch(self) -> EcosContextResult:
        self.calls += 1
        return self.result


class _ParallelProbe:
    def __init__(self) -> None:
        self.count = 0
        self.ready = asyncio.Event()

    async def arrive(self) -> None:
        self.count += 1
        if self.count == 2:
            self.ready.set()
        await asyncio.wait_for(self.ready.wait(), timeout=1)


def _instrument(market: MarketId = MarketId.US) -> InstrumentRef:
    if market is MarketId.KR:
        return InstrumentRef(
            market=market,
            symbol="005930",
            name="삼성전자",
            exchange="KRX",
            currency="KRW",
        )
    return InstrumentRef(
        market=market,
        symbol="AAPL",
        name="Apple",
        exchange="NASDAQ",
        currency="USD",
    )


def _snapshot(
    market: MarketId = MarketId.US,
    *,
    as_of_date: date = date(2026, 7, 10),
    gaps: list[str] | None = None,
    sma_200: float | None = 184,
) -> EODSnapshot:
    is_kr = market is MarketId.KR
    return EODSnapshot(
        ticker="005930" if is_kr else "AAPL",
        exchange="KRX" if is_kr else "NMS",
        currency="KRW" if is_kr else "USD",
        timezone="Asia/Seoul" if is_kr else "America/New_York",
        as_of_date=as_of_date,
        source_url=(
            "https://apis.data.go.kr/1160100/service/GetStockSecuritiesInfoService/getStockPriceInfo"
            if is_kr
            else "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"
        ),
        fetched_at=COLLECTED_AT,
        observations=260,
        current_close=190,
        previous_close=188,
        return_1d_pct=1.0638,
        return_5d_pct=2.5,
        return_20d_pct=4.0,
        return_60d_pct=10.0,
        sma_20=187,
        sma_50=180,
        sma_200=sma_200,
        rsi_14=58,
        atr_14=3.2,
        volatility_20d_pct=24,
        high_52_week=205,
        low_52_week=145,
        average_volume_20d=52_000_000,
        data_gaps=gaps or [],
    )


def _source(source_id: str, name: str, url: str) -> SourceRef:
    return SourceRef(
        source_id=source_id,
        name=name,
        tier=SourceTier.OFFICIAL,
        url=AnyHttpUrl(url),
        retrieved_at=COLLECTED_AT,
    )


def _fact(
    fact_id: str,
    source_id: str,
    metric: str,
    value: float | str,
    unit: str,
    instrument: InstrumentRef | None = None,
) -> Fact:
    return Fact(
        fact_id=fact_id,
        source_id=source_id,
        metric=metric,
        value=value,
        unit=unit,
        observed_at=OBSERVED_AT,
        published_at=PUBLISHED_AT,
        collected_at=COLLECTED_AT,
        instrument=instrument,
    )


def _macro_result(
    *,
    future_sections: tuple[str, ...] = (),
    stale_fact_ids: tuple[str, ...] = (),
) -> MacroContextResult:
    source = _source(
        "official:test:macro",
        "공식 거시 대역",
        "https://example.com/official-macro",
    )
    specifications = (
        ("dgs2", "미국 국채 2년물 금리", 4.2, "percent", "macro.rates"),
        ("dgs3", "미국 국채 3년물 금리", 4.1, "percent", "macro.rates"),
        ("dgs10", "미국 국채 10년물 금리", 4.5, "percent", "macro.rates"),
        (
            "dgs10_change",
            "미국 국채 10년물 금리 30일 변화",
            0.1,
            "percentage_point",
            "macro.rates",
        ),
        (
            "curve",
            "미국 국채 10년물과 2년물 금리차",
            0.3,
            "percentage_point",
            "macro.rates",
        ),
        ("dollar", "미 연준 광의 달러지수", 120, "index_point", "macro.currency"),
        (
            "dollar_change",
            "미 연준 광의 달러지수 30일 변화",
            0.2,
            "percent",
            "macro.currency",
        ),
        ("usdkrw", "원·달러 환율", 1350, "krw_per_usd", "macro.currency"),
        ("usdkrw_change", "원·달러 환율 30일 변화", 0.2, "percent", "macro.currency"),
        ("vix", "VIX 종가", 17, "index_point", "macro.volatility"),
        ("vix_change", "VIX 종가 30일 변화", -5, "percent", "macro.volatility"),
        ("wti", "WTI 현물 가격", 75, "usd_per_barrel", "macro.commodities"),
        ("wti_change", "WTI 현물 가격 30일 변화", 1, "percent", "macro.commodities"),
        ("brent", "브렌트유 현물 가격", 78, "usd_per_barrel", "macro.commodities"),
        ("brent_change", "브렌트유 현물 가격 30일 변화", 2, "percent", "macro.commodities"),
        ("bitcoin", "비트코인 미국 달러 가격", 70_000, "usd_per_bitcoin", "macro.liquidity"),
        ("bitcoin_change", "비트코인 미국 달러 가격 30일 변화", 12, "percent", "macro.liquidity"),
        (
            "cpi",
            "미국 소비자물가지수",
            320,
            "index_1982_1984_100",
            "macro.growth_inflation",
        ),
    )
    facts = tuple(
        _fact(f"macro:{key}", source.source_id, metric, value, unit)
        for key, metric, value, unit, _ in specifications
    )
    sections = tuple(
        ResearchSection(
            section_id=section_id,
            title=section_id,
            status=SectionStatus.COMPLETE,
            fact_ids=tuple(
                f"macro:{key}"
                for key, _, _, _, assigned_section in specifications
                if assigned_section == section_id
            ),
        )
        for section_id in (
            "macro.rates",
            "macro.currency",
            "macro.volatility",
            "macro.commodities",
            "macro.liquidity",
            "macro.growth_inflation",
        )
    )
    return MacroContextResult(
        sources=(source,),
        facts=facts,
        sections=sections,
        stale_fact_ids=stale_fact_ids,
        future_section_ids=future_sections,
    )


def _company_result(instrument: InstrumentRef) -> CompanyResearchResult:
    source = _source(
        "official:company",
        "공식 회사 자료",
        "https://data.sec.gov/api/xbrl/companyfacts/example.json",
    )
    fundamental = _fact(
        "company:revenue",
        source.source_id,
        "최근 공시 기준 매출",
        100_000_000,
        "currency",
        instrument,
    )
    filing = _fact(
        "company:filing",
        source.source_id,
        "공시 양식",
        "10-Q",
        "form",
        instrument,
    )
    return CompanyResearchResult(
        sources=(source,),
        facts=(fundamental, filing),
        sections=(
            ResearchSection(
                section_id="company.fundamental",
                title="공식 재무제표",
                status=SectionStatus.COMPLETE,
                fact_ids=(fundamental.fact_id,),
            ),
            ResearchSection(
                section_id="company.official_news",
                title="공식 공시 이벤트",
                status=SectionStatus.COMPLETE,
                fact_ids=(filing.fact_id,),
            ),
        ),
    )


def _ecos_result() -> EcosContextResult:
    source = _source(
        "official:bok-ecos:macro:kr",
        "한국은행 경제통계시스템 ECOS",
        "https://ecos.bok.or.kr/api/",
    )
    fact = _fact(
        "macro:bok-ecos:kr:base_rate",
        source.source_id,
        "한국은행 기준금리",
        2.5,
        "percent",
    )
    return EcosContextResult(
        sources=(source,),
        facts=(fact,),
        sections=(
            ResearchSection(
                section_id="macro.kr.ecos",
                title="한국 고유 거시 지표",
                status=SectionStatus.COMPLETE,
                fact_ids=(fact.fact_id,),
            ),
        ),
    )


@pytest.mark.asyncio
async def test_collect_blocks_metadata_only_and_missing_independent_news() -> None:
    instrument = _instrument()
    macro_client = _MacroClient(_macro_result())
    pipeline = ResearchPipeline(
        macro_client=macro_client,
        company_client=_CompanyClient(_company_result(instrument)),
        regime_evaluator=MarketRegimeEvaluator(),
        now_factory=lambda: COLLECTED_AT,
    )

    result = await pipeline.collect(instrument, _snapshot(), as_of=COLLECTED_AT)

    assert result.bundle.quality.analysis_eligible is False
    assert set(result.bundle.quality.blocked_section_ids) >= {
        "company.official_news",
        INDEPENDENT_NEWS_SECTION_ID,
    }
    assert len({source.source_id for source in result.bundle.sources}) == len(result.bundle.sources)
    assert len({fact.fact_id for fact in result.bundle.facts}) == len(result.bundle.facts)
    assert result.fundamentals and result.news == [] and result.macro
    assert all("source_url" in item for item in result.fundamentals + result.macro)
    sections = {section.section_id: section for section in result.bundle.sections}
    assert sections[VALUATION_SECTION_ID].required is False
    assert sections[VALUATION_SECTION_ID].status is SectionStatus.UNAVAILABLE
    assert sections["company.official_news"].status is SectionStatus.PARTIAL
    assert sections[INDEPENDENT_NEWS_SECTION_ID].required is True
    assert sections[INDEPENDENT_NEWS_SECTION_ID].status is SectionStatus.UNAVAILABLE
    assert any("독립 언론" in reason for reason in result.bundle.quality.blocking_reasons)
    assert result.regime.confidence == 1
    assert result.regime.regime.volatility is RegimeState.FAVORABLE


@pytest.mark.asyncio
async def test_tiingo_price_source_is_recorded_as_licensed() -> None:
    instrument = _instrument()
    pipeline = ResearchPipeline(
        macro_client=_MacroClient(_macro_result()),
        company_client=_CompanyClient(_company_result(instrument)),
        now_factory=lambda: COLLECTED_AT,
    )
    snapshot = _snapshot().model_copy(
        update={"source_url": "https://api.tiingo.com/tiingo/daily/AAPL/prices"}
    )

    result = await pipeline.collect(instrument, snapshot)

    price_source = next(
        source for source in result.bundle.sources if source.source_id.startswith("market.price")
    )
    assert price_source.tier is SourceTier.LICENSED


@pytest.mark.asyncio
async def test_partial_provider_failure_is_parallel_and_becomes_explicit_sections() -> None:
    instrument = _instrument()
    probe = _ParallelProbe()
    pipeline = ResearchPipeline(
        macro_client=_FailingMacroClient(probe),
        company_client=_CompanyClient(_company_result(instrument), probe),
        now_factory=lambda: COLLECTED_AT,
    )

    result = await pipeline.collect(instrument, _snapshot())

    assert probe.count == 2
    sections = {section.section_id: section for section in result.bundle.sections}
    assert sections["macro.rates"].status is SectionStatus.UNAVAILABLE
    assert "macro.rates" in result.bundle.quality.blocked_section_ids
    assert result.bundle.quality.analysis_eligible is False
    assert result.fundamentals and result.news == []
    assert result.macro == []
    assert result.regime.confidence == 0


@pytest.mark.asyncio
async def test_stale_macro_facts_are_not_used_for_regime_signals() -> None:
    instrument = _instrument()
    pipeline = ResearchPipeline(
        macro_client=_MacroClient(
            _macro_result(stale_fact_ids=("macro:vix", "macro:vix_change"))
        ),
        company_client=_CompanyClient(_company_result(instrument)),
        now_factory=lambda: COLLECTED_AT,
    )

    result = await pipeline.collect(instrument, _snapshot())

    assert result.regime.regime.volatility is RegimeState.UNKNOWN
    assert result.regime.confidence == 0.8
    assert "macro:vix" not in result.regime.evidence_fact_ids
    assert set(result.bundle.quality.stale_fact_ids) >= {
        "macro:vix",
        "macro:vix_change",
    }


@pytest.mark.asyncio
async def test_missing_required_macro_section_is_not_allowed_to_fail_open() -> None:
    instrument = _instrument()
    macro = _macro_result()
    macro_without_liquidity = MacroContextResult(
        sources=macro.sources,
        facts=macro.facts,
        sections=tuple(
            section
            for section in macro.sections
            if section.section_id != "macro.liquidity"
        ),
    )
    pipeline = ResearchPipeline(
        macro_client=_MacroClient(macro_without_liquidity),
        company_client=_CompanyClient(_company_result(instrument)),
        now_factory=lambda: COLLECTED_AT,
    )

    result = await pipeline.collect(instrument, _snapshot())

    assert result.bundle.quality.analysis_eligible is False
    assert "macro.liquidity" in result.bundle.quality.missing_required_sections
    assert any(
        "macro.liquidity" in reason
        for reason in result.bundle.quality.blocking_reasons
    )


@pytest.mark.asyncio
async def test_company_failure_keeps_macro_and_converts_company_sections() -> None:
    instrument = _instrument()
    pipeline = ResearchPipeline(
        macro_client=_MacroClient(_macro_result()),
        company_client=_FailingCompanyClient(),
        now_factory=lambda: COLLECTED_AT,
    )

    result = await pipeline.collect(instrument, _snapshot())

    sections = {section.section_id: section for section in result.bundle.sections}
    assert sections["company.fundamental"].status is SectionStatus.UNAVAILABLE
    assert sections["company.official_news"].status is SectionStatus.UNAVAILABLE
    assert result.fundamentals == []
    assert result.news == []
    assert result.macro
    assert result.bundle.quality.analysis_eligible is False


@pytest.mark.asyncio
async def test_single_source_roe_and_roa_are_derived_without_inventing_per_or_pbr() -> None:
    instrument = _instrument()
    company = _company_result(instrument)
    source_id = company.sources[0].source_id
    inputs = (
        _fact("company:ttm_income", source_id, "TTM 순이익", 10, "currency", instrument),
        _fact("company:average_equity", source_id, "평균자본", 100, "currency", instrument),
        _fact("company:average_assets", source_id, "평균자산", 200, "currency", instrument),
    )
    fundamental = company.sections[0].model_copy(
        update={"fact_ids": (*company.sections[0].fact_ids, *(fact.fact_id for fact in inputs))}
    )
    company = CompanyResearchResult(
        sources=company.sources,
        facts=(*company.facts, *inputs),
        sections=(fundamental, company.sections[1]),
    )
    pipeline = ResearchPipeline(
        macro_client=_MacroClient(_macro_result()),
        company_client=_CompanyClient(company),
        now_factory=lambda: COLLECTED_AT,
    )

    result = await pipeline.collect(instrument, _snapshot())

    valuation = next(
        section for section in result.bundle.sections if section.section_id == VALUATION_SECTION_ID
    )
    valuation_facts = [fact for fact in result.bundle.facts if fact.fact_id in valuation.fact_ids]
    assert valuation.status is SectionStatus.PARTIAL
    assert {(fact.metric, fact.value) for fact in valuation_facts} == {("ROE", 10.0), ("ROA", 5.0)}
    assert all(fact.source_id == source_id for fact in valuation_facts)
    assert all(fact.metric not in {"PER", "PBR"} for fact in valuation_facts)


@pytest.mark.asyncio
async def test_actual_company_metric_names_produce_labeled_roe_roa_proxies() -> None:
    instrument = _instrument()
    company = _company_result(instrument)
    source_id = company.sources[0].source_id
    inputs = (
        _fact(
            "company:reported_income",
            source_id,
            "최근 공시 기준 순이익",
            150,
            "currency",
            instrument,
        ),
        _fact(
            "company:reported_equity",
            source_id,
            "최근 공시 기준 자본",
            800,
            "currency",
            instrument,
        ),
        _fact(
            "company:reported_assets",
            source_id,
            "최근 공시 기준 자산",
            2_000,
            "currency",
            instrument,
        ),
    )
    fundamental = company.sections[0].model_copy(
        update={"fact_ids": (*company.sections[0].fact_ids, *(fact.fact_id for fact in inputs))}
    )
    company = CompanyResearchResult(
        sources=company.sources,
        facts=(*company.facts, *inputs),
        sections=(fundamental, company.sections[1]),
    )
    pipeline = ResearchPipeline(
        macro_client=_MacroClient(_macro_result()),
        company_client=_CompanyClient(company),
        now_factory=lambda: COLLECTED_AT,
    )

    result = await pipeline.collect(instrument, _snapshot())

    valuation = next(
        section for section in result.bundle.sections if section.section_id == VALUATION_SECTION_ID
    )
    valuation_facts = [fact for fact in result.bundle.facts if fact.fact_id in valuation.fact_ids]
    assert {(fact.metric, fact.value) for fact in valuation_facts} == {
        ("ROE", 18.75),
        ("ROA", 7.5),
    }
    assert valuation.status is SectionStatus.PARTIAL
    assert any("참고 비율" in gap for gap in valuation.data_gaps)


@pytest.mark.asyncio
async def test_stale_required_company_facts_are_blocked_and_reported() -> None:
    instrument = _instrument()
    company = _company_result(instrument)
    stale_observed = datetime(2024, 12, 31, tzinfo=UTC)
    stale_published = datetime(2025, 1, 31, tzinfo=UTC)
    stale_facts = tuple(
        fact.model_copy(update={"observed_at": stale_observed, "published_at": stale_published})
        for fact in company.facts
    )
    company = CompanyResearchResult(
        sources=company.sources,
        facts=stale_facts,
        sections=company.sections,
    )
    pipeline = ResearchPipeline(
        macro_client=_MacroClient(_macro_result()),
        company_client=_CompanyClient(company),
        now_factory=lambda: COLLECTED_AT,
    )

    result = await pipeline.collect(instrument, _snapshot())

    sections = {section.section_id: section for section in result.bundle.sections}
    stale_ids = {fact.fact_id for fact in stale_facts}
    assert set(result.bundle.quality.stale_fact_ids) >= stale_ids
    assert sections["company.fundamental"].status is SectionStatus.BLOCKED
    assert sections["company.official_news"].status is SectionStatus.BLOCKED
    assert result.bundle.quality.analysis_eligible is False


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_section_id", ["company.fundamental", "company.official_news"])
async def test_missing_required_company_section_never_fails_open(
    missing_section_id: str,
) -> None:
    instrument = _instrument()
    company = _company_result(instrument)
    company = CompanyResearchResult(
        sources=company.sources,
        facts=company.facts,
        sections=tuple(
            section for section in company.sections if section.section_id != missing_section_id
        ),
    )
    pipeline = ResearchPipeline(
        macro_client=_MacroClient(_macro_result()),
        company_client=_CompanyClient(company),
        now_factory=lambda: COLLECTED_AT,
    )

    result = await pipeline.collect(instrument, _snapshot())

    assert missing_section_id in result.bundle.quality.missing_required_sections
    assert result.bundle.quality.analysis_eligible is False


@pytest.mark.asyncio
async def test_provider_cannot_downgrade_required_company_section_to_optional() -> None:
    instrument = _instrument()
    company = _company_result(instrument)
    optional_fundamental = company.sections[0].model_copy(update={"required": False})
    company = CompanyResearchResult(
        sources=company.sources,
        facts=company.facts,
        sections=(optional_fundamental, company.sections[1]),
    )
    pipeline = ResearchPipeline(
        macro_client=_MacroClient(_macro_result()),
        company_client=_CompanyClient(company),
        now_factory=lambda: COLLECTED_AT,
    )

    result = await pipeline.collect(instrument, _snapshot())

    fundamental = next(
        section for section in result.bundle.sections if section.section_id == "company.fundamental"
    )
    assert fundamental.required is True


@pytest.mark.asyncio
async def test_company_fact_published_after_observation_cutoff_is_excluded() -> None:
    instrument = _instrument()
    company = _company_result(instrument)
    future_time = datetime(2026, 7, 13, tzinfo=UTC)
    future_fundamental = company.facts[0].model_copy(
        update={
            "observed_at": future_time,
            "published_at": future_time,
            "collected_at": future_time,
        }
    )
    company = CompanyResearchResult(
        sources=company.sources,
        facts=(future_fundamental, company.facts[1]),
        sections=company.sections,
    )
    pipeline = ResearchPipeline(
        macro_client=_MacroClient(_macro_result()),
        company_client=_CompanyClient(company),
        now_factory=lambda: COLLECTED_AT,
    )

    result = await pipeline.collect(instrument, _snapshot(), cutoff=COLLECTED_AT)

    fact_ids = {fact.fact_id for fact in result.bundle.facts}
    fundamental = next(
        section for section in result.bundle.sections if section.section_id == "company.fundamental"
    )
    assert future_fundamental.fact_id not in fact_ids
    assert fundamental.status is SectionStatus.BLOCKED
    assert result.bundle.quality.analysis_eligible is False


@pytest.mark.asyncio
async def test_korean_missing_ecos_and_optional_price_limits_do_not_block_core_price() -> None:
    instrument = _instrument(MarketId.KR)
    historical_cutoff = datetime(2026, 7, 10, 23, 59, tzinfo=UTC)
    company_client = _CompanyClient(_company_result(instrument))
    pipeline = ResearchPipeline(
        macro_client=_MacroClient(_macro_result()),
        company_client=company_client,
        ecos_api_key=None,
        now_factory=lambda: COLLECTED_AT,
    )
    snapshot = _snapshot(
        MarketId.KR,
        gaps=(
            "한국 공공데이터 일봉은 조정주가가 아니어서 기업행사 전후 비교에 한계가 있습니다.",
            "SMA200 계산에 필요한 이력이 부족합니다.",
        ),
        sma_200=None,
    )

    result = await pipeline.collect(instrument, snapshot, cutoff=historical_cutoff)

    assert result.observation_cutoff == historical_cutoff
    assert company_client.cutoffs == [historical_cutoff]
    assert result.bundle.cutoff >= max(source.retrieved_at for source in result.bundle.sources)
    sections = {section.section_id: section for section in result.bundle.sections}
    assert sections[PRICE_CORE_SECTION_ID].status is SectionStatus.COMPLETE
    assert sections[PRICE_TECHNICAL_SECTION_ID].status is SectionStatus.PARTIAL
    assert sections[PRICE_TECHNICAL_SECTION_ID].required is False
    assert sections["macro.kr.ecos"].status is SectionStatus.UNAVAILABLE
    assert set(result.bundle.quality.blocked_section_ids) == {
        "macro.kr.ecos",
        "company.official_news",
        INDEPENDENT_NEWS_SECTION_ID,
    }
    assert any("조정주가" in warning for warning in result.bundle.quality.warnings)
    price_source = next(
        source for source in result.bundle.sources if source.source_id.startswith("market.price")
    )
    assert price_source.tier is SourceTier.OFFICIAL


@pytest.mark.asyncio
async def test_stale_price_facts_are_reported_and_blocked() -> None:
    instrument = _instrument()
    pipeline = ResearchPipeline(
        macro_client=_MacroClient(_macro_result()),
        company_client=_CompanyClient(_company_result(instrument)),
        now_factory=lambda: COLLECTED_AT,
    )

    result = await pipeline.collect(
        instrument,
        _snapshot(as_of_date=date(2026, 6, 30)),
    )

    core = next(
        section for section in result.bundle.sections if section.section_id == PRICE_CORE_SECTION_ID
    )
    all_price_fact_ids = tuple(
        fact.fact_id for fact in result.bundle.facts if fact.fact_id.startswith("market.price:")
    )
    assert core.status is SectionStatus.BLOCKED
    assert set(core.fact_ids) < set(all_price_fact_ids)
    assert result.bundle.quality.stale_fact_ids == all_price_fact_ids
    assert result.bundle.quality.blocked_fact_ids == all_price_fact_ids
    assert result.bundle.quality.analysis_eligible is False


@pytest.mark.asyncio
async def test_historical_observation_cutoff_excludes_future_macro_observation_only() -> None:
    instrument = _instrument()
    macro = _macro_result()
    future_fact = macro.facts[0].model_copy(
        update={
            "observed_at": datetime(2026, 7, 11, tzinfo=UTC),
            "published_at": datetime(2026, 7, 11, 1, tzinfo=UTC),
        }
    )
    macro = MacroContextResult(
        sources=macro.sources,
        facts=(future_fact, *macro.facts[1:]),
        sections=macro.sections,
        future_section_ids=(),
    )
    historical_cutoff = datetime(2026, 7, 10, 23, 59, tzinfo=UTC)
    pipeline = ResearchPipeline(
        macro_client=_MacroClient(macro),
        company_client=_CompanyClient(_company_result(instrument)),
        now_factory=lambda: COLLECTED_AT,
    )

    result = await pipeline.collect(
        instrument,
        _snapshot(),
        cutoff=historical_cutoff,
    )

    assert result.observation_cutoff == historical_cutoff
    assert result.bundle.cutoff == COLLECTED_AT
    assert all(fact.fact_id != future_fact.fact_id for fact in result.bundle.facts)
    rates = next(
        section for section in result.bundle.sections if section.section_id == "macro.rates"
    )
    assert rates.status is SectionStatus.PARTIAL
    assert any("미래 정보" in gap for gap in rates.data_gaps)


@pytest.mark.asyncio
async def test_historical_cutoff_excludes_fact_published_after_cutoff() -> None:
    instrument = _instrument()
    macro = _macro_result()
    future_publication = macro.facts[0].model_copy(
        update={"published_at": datetime(2026, 7, 11, 1, tzinfo=UTC)}
    )
    macro = MacroContextResult(
        sources=macro.sources,
        facts=(future_publication, *macro.facts[1:]),
        sections=macro.sections,
    )
    pipeline = ResearchPipeline(
        macro_client=_MacroClient(macro),
        company_client=_CompanyClient(_company_result(instrument)),
        now_factory=lambda: COLLECTED_AT,
    )

    result = await pipeline.collect(
        instrument,
        _snapshot(),
        cutoff=datetime(2026, 7, 10, 23, 59, tzinfo=UTC),
    )

    assert all(fact.fact_id != future_publication.fact_id for fact in result.bundle.facts)


@pytest.mark.asyncio
async def test_macro_cache_singleflights_concurrent_requests() -> None:
    macro_client = _MacroClient(_macro_result())
    instrument = _instrument()
    pipeline = ResearchPipeline(
        macro_client=macro_client,
        company_client=_CompanyClient(_company_result(instrument)),
        now_factory=lambda: COLLECTED_AT,
    )

    first, second = await asyncio.gather(
        pipeline.get_macro_context(MarketId.US),
        pipeline.get_macro_context(MarketId.KR),
    )

    assert macro_client.calls == 1
    assert all(section.section_id != "macro.kr.ecos" for section in first.sections)
    assert any(section.section_id == "macro.kr.ecos" for section in second.sections)


@pytest.mark.asyncio
async def test_configured_ecos_client_is_merged_and_singleflight_cached() -> None:
    macro_client = _MacroClient(_macro_result())
    ecos_client = _EcosClient(_ecos_result())
    instrument = _instrument(MarketId.KR)
    pipeline = ResearchPipeline(
        macro_client=macro_client,
        company_client=_CompanyClient(_company_result(instrument)),
        ecos_api_key="fixed-test-key",
        ecos_client=ecos_client,
        now_factory=lambda: COLLECTED_AT,
    )

    first, second = await asyncio.gather(
        pipeline.get_macro_context(MarketId.KR),
        pipeline.get_macro_context(MarketId.KR),
    )

    assert macro_client.calls == 1
    assert ecos_client.calls == 1
    assert first == second
    assert any(source.source_id == "official:bok-ecos:macro:kr" for source in first.sources)
    ecos_section = next(
        section for section in first.sections if section.section_id == "macro.kr.ecos"
    )
    assert ecos_section.status is SectionStatus.COMPLETE
    assert ecos_section.fact_ids == ("macro:bok-ecos:kr:base_rate",)
