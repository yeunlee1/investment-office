# 전체 상장종목을 재무·유동성·업종·차트 순서로 줄여 심층검토 후보를 만든다.
from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime
from statistics import median

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from investment_office.services.bulk_fundamentals import BulkFundamentalsProvider
from investment_office.services.candidate_discovery import (
    SAFETY_NOTICE,
    CandidateDiscoveryService,
    DiscoveryEODMetrics,
    DiscoveryStrategy,
    DiscoveryVerdict,
    EODMarketDataClient,
    find_universe_company_name,
)
from investment_office.services.discovery_jobs import (
    DiscoveryJobOutcome,
    DiscoveryJobStatus,
    DiscoveryProgressCallback,
    DiscoveryProgressUpdate,
    DiscoveryRunner,
    DiscoveryStage,
)
from investment_office.services.fundamental_screening import (
    FundamentalGate,
    FundamentalGateProfile,
    FundamentalGateResult,
    FundamentalGateStatus,
    ScreeningFundamentals,
)
from investment_office.services.instrument_identity import normalize_instrument
from investment_office.services.research_contracts import MarketId
from investment_office.services.universe_catalog import (
    UniverseCatalogMember,
    UniverseCatalogProvider,
)


class FullMarketScoreBreakdown(BaseModel):
    """후보 총점을 구성하는 재무·성장·업종·선행전망·차트 점수다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    financial: float = Field(ge=0, le=100)
    growth: float = Field(ge=0, le=100)
    sector: float = Field(ge=0, le=100)
    outlook: float = Field(ge=0, le=100)
    chart: float = Field(ge=0, le=100)
    valuation: float | None = Field(default=None, ge=0, le=100)


class FullMarketCandidate(BaseModel):
    """전체시장 다단계 필터를 통과한 심층검토 후보다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    market: MarketId
    rank: int = Field(ge=1)
    score: float = Field(ge=0, le=100)
    ticker: str
    company_name: str
    official_company_name: str
    sector: str
    verdict: DiscoveryVerdict
    reasons: tuple[str, ...] = Field(min_length=1)
    risks: tuple[str, ...] = Field(min_length=1)
    breakdown: FullMarketScoreBreakdown
    eod: DiscoveryEODMetrics
    source_url: AnyHttpUrl


class FullMarketDiscoveryResult(BaseModel):
    """전체시장 시작점과 단계별 통과 수를 포함한 최종 후보 결과다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    market: MarketId
    strategy: DiscoveryStrategy
    risk_profile: FundamentalGateProfile
    safety_notice: str = SAFETY_NOTICE
    universe_size: int = Field(ge=1)
    fundamentals_available_count: int = Field(ge=0)
    fundamentals_passed_count: int = Field(ge=0)
    fundamentals_special_review_count: int = Field(default=0, ge=0)
    fundamentals_insufficient_count: int = Field(default=0, ge=0)
    fundamentals_excluded_count: int = Field(default=0, ge=0)
    liquidity_passed_count: int = Field(ge=0)
    liquidity_excluded_count: int = Field(default=0, ge=0)
    price_data_failure_count: int = Field(default=0, ge=0)
    evaluated_count: int = Field(ge=0)
    qualified_count: int = Field(ge=0)
    omitted_count: int = Field(ge=0)
    candidates: tuple[FullMarketCandidate, ...]
    warnings: tuple[str, ...] = ()
    source_urls: tuple[AnyHttpUrl, ...] = Field(min_length=1)
    completed_at: datetime


class _PriceScreened(BaseModel):
    """재무 통과 종목과 완료 일봉을 최종 점수 전에 묶는다."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    member: UniverseCatalogMember
    fundamentals: ScreeningFundamentals
    gate: FundamentalGateResult
    eod: DiscoveryEODMetrics
    chart_score: float = Field(ge=0, le=100)


class _SectorEvidence(BaseModel):
    """업종 점수와 선행전망, 재무·가격 표본 수를 함께 보존한다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    score: float = Field(ge=0, le=100)
    outlook_score: float = Field(ge=0, le=100)
    financial_sample_size: int = Field(ge=0)
    price_sample_size: int = Field(ge=0)


class FullMarketDiscoveryService:
    """전체 원장부터 후보 순위까지 다섯 단계를 조정한다."""

    _PRICE_CANDIDATE_LIMIT = {
        FundamentalGateProfile.DEFENSIVE: 250,
        FundamentalGateProfile.BALANCED: 400,
        FundamentalGateProfile.AGGRESSIVE: 650,
    }
    _MIN_AVERAGE_VALUE = {
        MarketId.US: {
            FundamentalGateProfile.DEFENSIVE: 10_000_000,
            FundamentalGateProfile.BALANCED: 5_000_000,
            FundamentalGateProfile.AGGRESSIVE: 2_000_000,
        },
        MarketId.KR: {
            FundamentalGateProfile.DEFENSIVE: 10_000_000_000,
            FundamentalGateProfile.BALANCED: 5_000_000_000,
            FundamentalGateProfile.AGGRESSIVE: 1_000_000_000,
        },
    }

    def __init__(
        self,
        *,
        universe_catalog: UniverseCatalogProvider,
        fundamentals: BulkFundamentalsProvider,
        market_data: EODMarketDataClient,
        max_price_concurrency: int = 6,
        gate: FundamentalGate | None = None,
    ) -> None:
        if max_price_concurrency < 1:
            raise ValueError("가격 조회 동시성은 1 이상이어야 합니다.")
        self.universe_catalog = universe_catalog
        self.fundamentals = fundamentals
        self.market_data = market_data
        self.max_price_concurrency = max_price_concurrency
        self.gate = gate or FundamentalGate()

    def runner(
        self,
        *,
        market: MarketId,
        strategy: DiscoveryStrategy,
        risk_profile: FundamentalGateProfile,
        limit: int,
        force_refresh: bool = False,
    ) -> DiscoveryRunner:
        """작업 서비스가 실행할 진행 콜백 기반 코루틴을 만든다."""

        async def run(progress: DiscoveryProgressCallback) -> DiscoveryJobOutcome:
            return await self.screen(
                market=market,
                strategy=strategy,
                risk_profile=risk_profile,
                limit=limit,
                progress=progress,
                force_refresh=force_refresh,
            )

        return run

    async def screen(
        self,
        *,
        market: MarketId | str,
        strategy: DiscoveryStrategy | str,
        risk_profile: FundamentalGateProfile | str,
        limit: int,
        progress: DiscoveryProgressCallback,
        force_refresh: bool = False,
    ) -> DiscoveryJobOutcome:
        """전체시장 원장을 다섯 단계로 줄이고 최종 후보를 반환한다."""

        selected_market = MarketId(market)
        selected_strategy = DiscoveryStrategy(strategy)
        selected_profile = FundamentalGateProfile(risk_profile)
        if limit < 1 or limit > 30:
            raise ValueError("최종 후보 수는 1개 이상 30개 이하여야 합니다.")

        snapshot = await self.universe_catalog.load_snapshot(
            selected_market,
            force_refresh=force_refresh,
        )
        await progress(
            DiscoveryProgressUpdate(
                stage=DiscoveryStage.UNIVERSE,
                total=snapshot.raw_count,
                processed=snapshot.raw_count,
                passed=len(snapshot.members),
                failed=snapshot.excluded_count + snapshot.duplicate_count,
                cached=len(snapshot.members) if snapshot.cache_hit else 0,
                message=(
                    f"전체 상장 원장 {snapshot.raw_count:,}개에서 "
                    f"보통주 후보 {len(snapshot.members):,}개를 구성했습니다."
                ),
                completed=True,
            )
        )

        async def report_fundamentals(total: int, processed: int, cached: int) -> None:
            await progress(
                DiscoveryProgressUpdate(
                    stage=DiscoveryStage.FUNDAMENTALS,
                    total=max(total, len(snapshot.members)),
                    processed=min(processed, max(total, len(snapshot.members))),
                    passed=0,
                    failed=0,
                    cached=min(cached, processed),
                    message=f"공식 재무자료 {processed:,}개를 수집하고 있습니다.",
                )
            )

        await progress(
            DiscoveryProgressUpdate(
                stage=DiscoveryStage.FUNDAMENTALS,
                total=len(snapshot.members),
                processed=0,
                passed=0,
                failed=0,
                cached=0,
                message=(
                    "미국 전체 재무 파일을 내려받아 상장 원장과 연결하고 있습니다."
                    if selected_market is MarketId.US
                    else "한국 연간 재무상태표·손익계산서·현금흐름표를 연결하고 있습니다."
                ),
            )
        )
        batch = await self.fundamentals.fetch_many(
            snapshot,
            progress=report_fundamentals,
            force_refresh=force_refresh,
        )
        as_of_date = date.today()
        gate_by_ticker: dict[str, FundamentalGateResult] = {}
        for item in batch.items:
            gate_by_ticker[item.ticker] = self.gate.evaluate(
                item,
                selected_profile,
                as_of_date=as_of_date,
            )
        passed_fundamentals = [
            item
            for item in batch.items
            if gate_by_ticker[item.ticker].status is FundamentalGateStatus.PASSED
        ]
        special_review_count = sum(
            result.status is FundamentalGateStatus.SPECIAL_REVIEW
            for result in gate_by_ticker.values()
        )
        insufficient_count = sum(
            result.status is FundamentalGateStatus.INSUFFICIENT_DATA
            for result in gate_by_ticker.values()
        ) + len(snapshot.members) - len(batch.items)
        excluded_count = sum(
            result.status is FundamentalGateStatus.EXCLUDED
            for result in gate_by_ticker.values()
        )
        await progress(
            DiscoveryProgressUpdate(
                stage=DiscoveryStage.FUNDAMENTALS,
                total=len(snapshot.members),
                processed=len(snapshot.members),
                passed=len(passed_fundamentals),
                failed=len(snapshot.members) - len(passed_fundamentals),
                cached=len(batch.items) if batch.cache_hit else 0,
                message=(
                    f"재무자료 {len(batch.items):,}개를 확인해 통과 "
                    f"{len(passed_fundamentals):,}개, 전용지표 검토 "
                    f"{special_review_count:,}개, 자료 부족 {insufficient_count:,}개, "
                    f"기준 제외 {excluded_count:,}개로 분류했습니다."
                ),
                completed=True,
            )
        )
        if not passed_fundamentals:
            raise RuntimeError(
                "재무 하드게이트를 통과한 종목이 없습니다. "
                f"전용지표 검토 {special_review_count:,}개, 자료 부족 "
                f"{insufficient_count:,}개, 기준 제외 {excluded_count:,}개입니다. "
                "재무자료 기준일과 공급원 상태를 확인하세요."
            )

        member_by_ticker = {member.ticker: member for member in snapshot.members}
        def fundamental_sort_key(item: ScreeningFundamentals) -> tuple[float, str]:
            scores = gate_by_ticker[item.ticker].scores
            return (-(scores.total if scores is not None else 0), item.ticker)

        passed_fundamentals.sort(key=fundamental_sort_key)
        price_limit = self._PRICE_CANDIDATE_LIMIT[selected_profile]
        price_inputs = passed_fundamentals[:price_limit]
        price_screened, price_data_failures, liquidity_excluded = await self._screen_prices(
            selected_market,
            selected_strategy,
            selected_profile,
            price_inputs,
            member_by_ticker,
            gate_by_ticker,
            progress,
        )
        if not price_screened:
            raise RuntimeError(
                "재무 통과 종목에서 완료 일봉과 거래대금 기준을 통과한 후보를 찾지 못했습니다."
            )

        sector_scores = self._sector_scores(
            price_screened,
            passed_fundamentals,
            gate_by_ticker,
        )
        unknown_sector_count = sum(
            item.fundamentals.sector.endswith("미분류") for item in price_screened
        )
        await progress(
            DiscoveryProgressUpdate(
                stage=DiscoveryStage.SECTOR,
                total=len(price_screened),
                processed=len(price_screened),
                passed=len(price_screened),
                failed=0,
                message=(
                    f"{len(sector_scores):,}개 업종의 60일 상대강도와 매출 가속도·"
                    "마진·현금창출력을 비교했습니다."
                ),
                completed=True,
            )
        )

        ranked = self._rank(price_screened, sector_scores)
        candidates = tuple(
            self._candidate(item, rank, sector_scores[item.fundamentals.sector])
            for rank, item in enumerate(ranked[:limit], 1)
        )
        await progress(
            DiscoveryProgressUpdate(
                stage=DiscoveryStage.RANKING,
                total=len(ranked),
                processed=len(ranked),
                passed=len(candidates),
                failed=0,
                message=f"최종 심층검토 후보 {len(candidates)}개를 순위화했습니다.",
                completed=True,
            )
        )

        warnings = [*snapshot.warnings, *batch.warnings]
        if special_review_count:
            warnings.append(
                f"금융·보험·리츠 {special_review_count:,}개는 일반 기업 기준으로 추천하지 않고 "
                "업종 전용 건전성 지표 검토 대상으로 분리했습니다."
            )
        if price_data_failures:
            warnings.append(
                f"완료 일봉 자료를 확인하지 못한 종목 {price_data_failures:,}개는 "
                "유동성 탈락과 구분해 자료 실패로 기록했습니다."
            )
        if unknown_sector_count:
            warnings.append(
                f"업종 미분류 {unknown_sector_count}개는 업종 점수를 중립값으로 처리했습니다."
            )
        coverage = len(batch.items) / len(snapshot.members)
        price_failure_ratio = (
            price_data_failures / len(price_inputs) if price_inputs else 1
        )
        partial = coverage < 0.8 or price_failure_ratio > 0.2 or unknown_sector_count > 0
        result = FullMarketDiscoveryResult(
            market=selected_market,
            strategy=selected_strategy,
            risk_profile=selected_profile,
            universe_size=len(snapshot.members),
            fundamentals_available_count=len(batch.items),
            fundamentals_passed_count=len(passed_fundamentals),
            fundamentals_special_review_count=special_review_count,
            fundamentals_insufficient_count=insufficient_count,
            fundamentals_excluded_count=excluded_count,
            liquidity_passed_count=len(price_screened),
            liquidity_excluded_count=liquidity_excluded,
            price_data_failure_count=price_data_failures,
            evaluated_count=len(ranked),
            qualified_count=len(ranked),
            omitted_count=max(0, len(ranked) - len(candidates)),
            candidates=candidates,
            warnings=tuple(dict.fromkeys(warnings)),
            source_urls=tuple(dict.fromkeys([*snapshot.source_urls, *batch.source_urls])),
            completed_at=datetime.now(UTC),
        )
        message = (
            f"전체 {len(snapshot.members):,}개에서 재무 {len(passed_fundamentals):,}개, "
            f"유동성 {len(price_screened):,}개, 최종 {len(candidates)}개를 선별했습니다."
        )
        return DiscoveryJobOutcome(
            status=DiscoveryJobStatus.PARTIAL if partial else DiscoveryJobStatus.COMPLETE,
            result=result.model_dump(mode="json"),
            message=(
                f"{message} 일부 자료 공백은 경고에 기록했습니다."
                if partial
                else message
            ),
        )

    async def _screen_prices(
        self,
        market: MarketId,
        strategy: DiscoveryStrategy,
        profile: FundamentalGateProfile,
        inputs: Sequence[ScreeningFundamentals],
        members: dict[str, UniverseCatalogMember],
        gates: dict[str, FundamentalGateResult],
        progress: DiscoveryProgressCallback,
    ) -> tuple[list[_PriceScreened], int, int]:
        semaphore = asyncio.Semaphore(self.max_price_concurrency)

        async def fetch(
            item: ScreeningFundamentals,
        ) -> tuple[_PriceScreened | None, bool]:
            member = members.get(item.ticker)
            gate = gates[item.ticker]
            if member is None or gate.scores is None:
                return None, True
            async with semaphore:
                storage_ticker = normalize_instrument(market, item.ticker).storage_ticker
                snapshot = await self.market_data.fetch_eod_snapshot(storage_ticker)
            if CandidateDiscoveryService._missing_scoring_data(snapshot):
                return None, True
            metrics = CandidateDiscoveryService._metrics(snapshot)
            average_value = metrics.current_close * metrics.average_volume_20d
            if average_value < self._MIN_AVERAGE_VALUE[market][profile]:
                return None, False
            return (
                _PriceScreened(
                    member=member,
                    fundamentals=item,
                    gate=gate,
                    eod=metrics,
                    chart_score=CandidateDiscoveryService._score(metrics, strategy),
                ),
                False,
            )

        tasks = [asyncio.create_task(fetch(item)) for item in inputs]
        passed: list[_PriceScreened] = []
        data_failures = 0
        liquidity_excluded = 0
        for processed, task in enumerate(asyncio.as_completed(tasks), 1):
            try:
                item, data_failed = await task
            except Exception:
                item = None
                data_failed = True
            if item is None:
                if data_failed:
                    data_failures += 1
                else:
                    liquidity_excluded += 1
            else:
                passed.append(item)
            await progress(
                DiscoveryProgressUpdate(
                    stage=DiscoveryStage.LIQUIDITY,
                    total=len(tasks),
                    processed=processed,
                    passed=len(passed),
                    failed=data_failures,
                    message=(
                        f"재무 상위 종목의 완료 일봉과 20일 평균 거래대금을 비교 중입니다. "
                        f"{processed:,}/{len(tasks):,}, 통과 {len(passed):,}개, "
                        f"유동성 제외 {liquidity_excluded:,}개, 자료 실패 {data_failures:,}개"
                    ),
                    completed=processed == len(tasks),
                )
            )
        return passed, data_failures, liquidity_excluded

    @staticmethod
    def _sector_scores(
        items: Sequence[_PriceScreened],
        fundamentals: Sequence[ScreeningFundamentals],
        gates: dict[str, FundamentalGateResult],
    ) -> dict[str, _SectorEvidence]:
        price_grouped: dict[str, list[_PriceScreened]] = defaultdict(list)
        for item in items:
            price_grouped[item.fundamentals.sector].append(item)
        financial_grouped: dict[
            str,
            list[tuple[ScreeningFundamentals, FundamentalGateResult]],
        ] = defaultdict(list)
        for fundamental in fundamentals:
            gate = gates.get(fundamental.ticker)
            if gate is not None and gate.scores is not None:
                financial_grouped[fundamental.sector].append((fundamental, gate))
        scores: dict[str, _SectorEvidence] = {}
        for sector, sector_items in price_grouped.items():
            financial_items = financial_grouped.get(sector, [])
            if sector.endswith("미분류"):
                scores[sector] = _SectorEvidence(
                    score=50.0,
                    outlook_score=50.0,
                    financial_sample_size=len(financial_items),
                    price_sample_size=len(sector_items),
                )
                continue
            if len(financial_items) >= 3:
                outlook_score = median(
                    _company_outlook_score(fundamental)
                    for fundamental, _gate in financial_items
                )
                financial_quality = median(
                    gate.scores.quality
                    for _fundamental, gate in financial_items
                    if gate.scores is not None
                )
                financial_evidence = (
                    outlook_score * 0.40 + financial_quality * 0.20
                )
            else:
                outlook_score = 50.0
                financial_evidence = 50.0 * 0.60
            if len(sector_items) >= 3:
                momentum = median(item.eod.return_60d_pct for item in sector_items)
                breadth = sum(
                    item.eod.return_60d_pct > 0 for item in sector_items
                ) / len(sector_items)
                price_evidence = (
                    _scale(momentum, -20, 35) * 0.25 + breadth * 100 * 0.15
                )
            else:
                price_evidence = 50.0 * 0.40
            scores[sector] = _SectorEvidence(
                score=round(
                    _clamp(
                        price_evidence
                        + financial_evidence
                    ),
                    2,
                ),
                outlook_score=round(outlook_score, 2),
                financial_sample_size=len(financial_items),
                price_sample_size=len(sector_items),
            )
        return scores

    @staticmethod
    def _rank(
        items: Sequence[_PriceScreened],
        sector_scores: dict[str, _SectorEvidence],
    ) -> list[_PriceScreened]:
        def total(item: _PriceScreened) -> float:
            scores = item.gate.scores
            if scores is None:
                return 0
            parts = [
                (scores.quality, 0.35),
                (scores.growth, 0.20),
                (sector_scores[item.fundamentals.sector].score, 0.20),
                (item.chart_score, 0.15),
            ]
            if scores.valuation is not None:
                parts.append((scores.valuation, 0.10))
            weight = sum(part_weight for _, part_weight in parts)
            return sum(score * part_weight for score, part_weight in parts) / weight

        return sorted(items, key=lambda item: (-total(item), item.member.ticker))

    @staticmethod
    def _candidate(
        item: _PriceScreened,
        rank: int,
        sector_evidence: _SectorEvidence,
    ) -> FullMarketCandidate:
        scores = item.gate.scores
        if scores is None:
            raise ValueError("재무 점수가 없는 종목은 후보가 될 수 없습니다.")
        parts = [
            (scores.quality, 0.35),
            (scores.growth, 0.20),
            (sector_evidence.score, 0.20),
            (item.chart_score, 0.15),
        ]
        if scores.valuation is not None:
            parts.append((scores.valuation, 0.10))
        weight = sum(part_weight for _, part_weight in parts)
        total = round(
            sum(score * part_weight for score, part_weight in parts) / weight,
            2,
        )
        localized_name = find_universe_company_name(
            item.member.market,
            item.member.ticker,
        )
        reasons = [
            *item.gate.reasons,
            (
                f"업종 재무 {sector_evidence.financial_sample_size}개와 가격 "
                f"{sector_evidence.price_sample_size}개를 비교한 업종 점수는 "
                f"{sector_evidence.score:.1f}점입니다."
            ),
            (
                "업종의 매출 가속도·영업마진 변화·현금창출력을 합친 선행 성장 "
                f"지속성 점수는 {sector_evidence.outlook_score:.1f}점입니다."
            ),
            CandidateDiscoveryService._reasons(item.eod, DiscoveryStrategy.BALANCED)[0],
        ]
        risks = [*item.gate.risks, *CandidateDiscoveryService._risks(item.eod)]
        if sector_evidence.price_sample_size < 3:
            risks.append(
                "같은 업종의 가격 표본이 3개 미만이라 업종 가격 모멘텀은 중립값으로 처리했습니다."
            )
        if sector_evidence.financial_sample_size < 3:
            risks.append(
                "같은 업종의 재무 표본이 3개 미만이라 업종 재무 성장성은 중립값으로 처리했습니다."
            )
        risks.append(
            "업종 선행 성장 지속성은 정량 대리값이며 장기 수요·경쟁·규제 전망은 "
            "심층 분석에서 검증해야 합니다."
        )
        return FullMarketCandidate(
            market=item.member.market,
            rank=rank,
            score=total,
            ticker=item.member.ticker,
            company_name=localized_name or item.member.company_name,
            official_company_name=item.member.company_name,
            sector=item.fundamentals.sector,
            verdict=(
                DiscoveryVerdict.REVIEW_FIRST if total >= 72 else DiscoveryVerdict.WATCH
            ),
            reasons=tuple(dict.fromkeys(reasons)),
            risks=tuple(dict.fromkeys(risks)),
            breakdown=FullMarketScoreBreakdown(
                financial=scores.quality,
                growth=scores.growth,
                sector=sector_evidence.score,
                outlook=sector_evidence.outlook_score,
                chart=item.chart_score,
                valuation=scores.valuation,
            ),
            eod=item.eod,
            source_url=item.fundamentals.source_urls[0],
        )


def _company_outlook_score(fundamentals: ScreeningFundamentals) -> float:
    """최근 성장 가속도와 수익·현금창출 변화로 선행 지속성 대리점수를 만든다."""

    periods = fundamentals.periods[-3:]
    if len(periods) < 3 or any(
        value is None
        for period in periods
        for value in (
            period.revenue,
            period.operating_income,
            period.operating_cash_flow,
        )
    ):
        return 50.0
    revenues = [float(period.revenue or 0) for period in periods]
    operating_income = [float(period.operating_income or 0) for period in periods]
    operating_cash_flow = [
        float(period.operating_cash_flow or 0) for period in periods
    ]
    if any(revenue <= 0 for revenue in revenues):
        return 0.0
    prior_growth = revenues[1] / revenues[0] - 1
    latest_growth = revenues[2] / revenues[1] - 1
    growth_acceleration = latest_growth - prior_growth
    margins = [
        income / revenue
        for income, revenue in zip(operating_income, revenues, strict=True)
    ]
    margin_change = margins[2] - margins[1]
    cash_margin = operating_cash_flow[2] / revenues[2]
    return round(
        _clamp(
            _scale(latest_growth, -0.05, 0.30) * 0.35
            + _scale(growth_acceleration, -0.15, 0.15) * 0.25
            + _scale(margin_change, -0.05, 0.05) * 0.20
            + _scale(cash_margin, 0, 0.25) * 0.20
        ),
        2,
    )


def _scale(value: float, low: float, high: float) -> float:
    if high <= low:
        raise ValueError("점수 상한은 하한보다 커야 합니다.")
    return _clamp((value - low) / (high - low) * 100)


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))
