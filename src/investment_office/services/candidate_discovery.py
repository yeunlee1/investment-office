# 미국 대형 유동성 주식의 EOD 지표를 병렬 조회해 심층 검토 후보를 선별한다.
from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

from investment_office.services.instrument_identity import normalize_instrument
from investment_office.services.market_data import EODSnapshot
from investment_office.services.research_contracts import MarketId

SAFETY_NOTICE = (
    "이 결과는 매수 추천이 아니라 심층 검토 후보를 좁히는 저비용 1차 스크리닝입니다."
)


class UniverseMember(BaseModel):
    """명시적 스타터 유니버스의 종목과 섹터."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    market: MarketId = MarketId.US
    ticker: str = Field(min_length=1, max_length=10)
    sector: str = Field(min_length=1, max_length=80)


STARTER_UNIVERSE: tuple[UniverseMember, ...] = (
    UniverseMember(ticker="AAPL", sector="technology"),
    UniverseMember(ticker="MSFT", sector="technology"),
    UniverseMember(ticker="NVDA", sector="technology"),
    UniverseMember(ticker="AVGO", sector="technology"),
    UniverseMember(ticker="ORCL", sector="technology"),
    UniverseMember(ticker="CRM", sector="technology"),
    UniverseMember(ticker="GOOGL", sector="communication_services"),
    UniverseMember(ticker="META", sector="communication_services"),
    UniverseMember(ticker="NFLX", sector="communication_services"),
    UniverseMember(ticker="TMUS", sector="communication_services"),
    UniverseMember(ticker="AMZN", sector="consumer_discretionary"),
    UniverseMember(ticker="TSLA", sector="consumer_discretionary"),
    UniverseMember(ticker="HD", sector="consumer_discretionary"),
    UniverseMember(ticker="MCD", sector="consumer_discretionary"),
    UniverseMember(ticker="WMT", sector="consumer_staples"),
    UniverseMember(ticker="COST", sector="consumer_staples"),
    UniverseMember(ticker="PG", sector="consumer_staples"),
    UniverseMember(ticker="KO", sector="consumer_staples"),
    UniverseMember(ticker="BRK-B", sector="financials"),
    UniverseMember(ticker="JPM", sector="financials"),
    UniverseMember(ticker="V", sector="financials"),
    UniverseMember(ticker="MA", sector="financials"),
    UniverseMember(ticker="LLY", sector="health_care"),
    UniverseMember(ticker="UNH", sector="health_care"),
    UniverseMember(ticker="JNJ", sector="health_care"),
    UniverseMember(ticker="ABBV", sector="health_care"),
    UniverseMember(ticker="GE", sector="industrials"),
    UniverseMember(ticker="CAT", sector="industrials"),
    UniverseMember(ticker="XOM", sector="energy"),
    UniverseMember(ticker="CVX", sector="energy"),
)

KR_STARTER_UNIVERSE: tuple[UniverseMember, ...] = (
    UniverseMember(market=MarketId.KR, ticker="005930", sector="semiconductors"),
    UniverseMember(market=MarketId.KR, ticker="000660", sector="semiconductors"),
    UniverseMember(market=MarketId.KR, ticker="005380", sector="automobiles"),
    UniverseMember(market=MarketId.KR, ticker="000270", sector="automobiles"),
    UniverseMember(market=MarketId.KR, ticker="035420", sector="internet"),
    UniverseMember(market=MarketId.KR, ticker="035720", sector="internet"),
    UniverseMember(market=MarketId.KR, ticker="207940", sector="biotechnology"),
    UniverseMember(market=MarketId.KR, ticker="068270", sector="biotechnology"),
    UniverseMember(market=MarketId.KR, ticker="373220", sector="batteries"),
    UniverseMember(market=MarketId.KR, ticker="051910", sector="chemicals"),
    UniverseMember(market=MarketId.KR, ticker="006400", sector="batteries"),
    UniverseMember(market=MarketId.KR, ticker="105560", sector="financials"),
    UniverseMember(market=MarketId.KR, ticker="055550", sector="financials"),
    UniverseMember(market=MarketId.KR, ticker="086790", sector="financials"),
    UniverseMember(market=MarketId.KR, ticker="316140", sector="financials"),
    UniverseMember(market=MarketId.KR, ticker="012330", sector="auto_parts"),
    UniverseMember(market=MarketId.KR, ticker="028260", sector="industrials"),
    UniverseMember(market=MarketId.KR, ticker="009150", sector="electronics"),
    UniverseMember(market=MarketId.KR, ticker="034730", sector="holding_companies"),
    UniverseMember(market=MarketId.KR, ticker="096770", sector="energy"),
    UniverseMember(market=MarketId.KR, ticker="015760", sector="utilities"),
    UniverseMember(market=MarketId.KR, ticker="017670", sector="telecommunications"),
    UniverseMember(market=MarketId.KR, ticker="030200", sector="telecommunications"),
    UniverseMember(market=MarketId.KR, ticker="032830", sector="insurance"),
    UniverseMember(market=MarketId.KR, ticker="010130", sector="materials"),
    UniverseMember(market=MarketId.KR, ticker="066570", sector="electronics"),
    UniverseMember(market=MarketId.KR, ticker="003670", sector="materials"),
    UniverseMember(market=MarketId.KR, ticker="005490", sector="steel"),
    UniverseMember(market=MarketId.KR, ticker="018260", sector="information_technology"),
    UniverseMember(market=MarketId.KR, ticker="042700", sector="semiconductor_equipment"),
)


class DiscoveryStrategy(StrEnum):
    """1차 정량 스크리닝의 가중치 전략."""

    BALANCED = "balanced"
    MOMENTUM = "momentum"
    DEFENSIVE = "defensive"


class DiscoveryVerdict(StrEnum):
    """심층 검토 우선순위를 나타내는 비매매 판정."""

    REVIEW_FIRST = "review_first"
    WATCH = "watch"
    EXCLUDE = "exclude"


class DiscoveryEODMetrics(BaseModel):
    """스크리닝 판단을 재현할 수 있는 완료 일봉 핵심 수치."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of_date: str
    current_close: float
    return_1d_pct: float
    return_5d_pct: float
    return_20d_pct: float
    return_60d_pct: float
    sma_20: float
    sma_50: float
    sma_200: float
    rsi_14: float
    volatility_20d_pct: float
    average_volume_20d: float
    high_52_week: float
    low_52_week: float
    observations: int
    source_url: str


class CandidateDiscoveryItem(BaseModel):
    """순위가 있거나 제외 사유가 기록된 유니버스 종목."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    market: MarketId = MarketId.US
    rank: int | None = Field(default=None, ge=1)
    score: float = Field(ge=0, le=100)
    ticker: str
    sector: str
    verdict: DiscoveryVerdict
    reasons: list[str] = Field(min_length=1)
    risks: list[str] = Field(min_length=1)
    eod: DiscoveryEODMetrics | None
    source_url: str | None


class CandidateDiscoveryResult(BaseModel):
    """후보와 제외 종목을 분리한 1차 스크리닝 결과."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    market: MarketId = MarketId.US
    strategy: DiscoveryStrategy
    safety_notice: str = SAFETY_NOTICE
    universe_size: int = Field(ge=1)
    evaluated_count: int = Field(ge=0)
    qualified_count: int = Field(ge=0)
    omitted_count: int = Field(ge=0)
    candidates: list[CandidateDiscoveryItem]
    excluded: list[CandidateDiscoveryItem]


class EODMarketDataClient(Protocol):
    """YahooFinanceClient가 제공하는 읽기 전용 완료 일봉 계약."""

    async def fetch_eod_snapshot(self, ticker: str) -> EODSnapshot: ...


_STRATEGY_WEIGHTS: dict[DiscoveryStrategy, tuple[float, float, float, float]] = {
    DiscoveryStrategy.BALANCED: (0.35, 0.30, 0.20, 0.15),
    DiscoveryStrategy.MOMENTUM: (0.25, 0.50, 0.10, 0.15),
    DiscoveryStrategy.DEFENSIVE: (0.30, 0.15, 0.40, 0.15),
}


class CandidateDiscoveryService:
    """LLM과 DB 없이 Yahoo EOD 지표만으로 스타터 유니버스를 선별한다."""

    def __init__(
        self,
        *,
        market_data: EODMarketDataClient,
        max_concurrency: int = 6,
        universe: Sequence[UniverseMember] = STARTER_UNIVERSE,
    ) -> None:
        if isinstance(max_concurrency, bool) or max_concurrency < 1:
            raise ValueError("max_concurrency는 1 이상이어야 합니다.")
        if not universe:
            raise ValueError("universe는 비어 있을 수 없습니다.")
        tickers = [member.ticker for member in universe]
        if len(tickers) != len(set(tickers)):
            raise ValueError("universe에 중복 티커가 있습니다.")
        self.market_data = market_data
        self.max_concurrency = max_concurrency
        self.universe = tuple(universe)
        grouped_universes: dict[MarketId, tuple[UniverseMember, ...]] = {
            market: tuple(member for member in self.universe if member.market is market)
            for market in MarketId
        }
        self.universes = {
            market: members for market, members in grouped_universes.items() if members
        }
        if universe is STARTER_UNIVERSE:
            self.universes[MarketId.KR] = KR_STARTER_UNIVERSE

    async def screen(
        self,
        strategy: DiscoveryStrategy | str = DiscoveryStrategy.BALANCED,
        limit: int = 10,
        market: MarketId | str = MarketId.US,
    ) -> CandidateDiscoveryResult:
        """유니버스를 병렬 조회하고 결정론적 점수순으로 심층 검토 후보를 반환한다."""

        try:
            selected_strategy = DiscoveryStrategy(strategy)
        except ValueError as exc:
            choices = ", ".join(item.value for item in DiscoveryStrategy)
            raise ValueError(f"strategy는 {choices} 중 하나여야 합니다.") from exc
        if isinstance(limit, bool) or limit < 1:
            raise ValueError("limit은 1 이상이어야 합니다.")
        try:
            selected_market = MarketId(market)
        except ValueError as exc:
            raise ValueError("market은 us 또는 kr이어야 합니다.") from exc
        selected_universe = self.universes.get(selected_market)
        if not selected_universe:
            raise ValueError(f"{selected_market.value} 시장 유니버스가 구성되지 않았습니다.")

        semaphore = asyncio.Semaphore(self.max_concurrency)
        items = await asyncio.gather(
            *(
                self._screen_member(member, selected_strategy, semaphore)
                for member in selected_universe
            )
        )
        scored = sorted(
            (item for item in items if item.eod is not None),
            key=lambda item: (-item.score, item.ticker),
        )
        ranked = [item.model_copy(update={"rank": rank}) for rank, item in enumerate(scored, 1)]
        qualified = [item for item in ranked if item.verdict != DiscoveryVerdict.EXCLUDE]
        candidates = qualified[:limit]
        excluded = [item for item in ranked if item.verdict == DiscoveryVerdict.EXCLUDE]
        excluded.extend(item for item in items if item.eod is None)
        excluded.sort(key=lambda item: (item.rank is None, item.rank or 0, item.ticker))
        return CandidateDiscoveryResult(
            market=selected_market,
            strategy=selected_strategy,
            universe_size=len(selected_universe),
            evaluated_count=len(scored),
            qualified_count=len(qualified),
            omitted_count=max(0, len(qualified) - len(candidates)),
            candidates=candidates,
            excluded=excluded,
        )

    async def _screen_member(
        self,
        member: UniverseMember,
        strategy: DiscoveryStrategy,
        semaphore: asyncio.Semaphore,
    ) -> CandidateDiscoveryItem:
        async with semaphore:
            try:
                storage_ticker = normalize_instrument(
                    member.market,
                    member.ticker,
                ).storage_ticker
                snapshot = await self.market_data.fetch_eod_snapshot(storage_ticker)
            except Exception as exc:
                return self._failed_item(member, exc)

        missing = self._missing_scoring_data(snapshot)
        if missing:
            detail = ", ".join(missing)
            gaps = " ".join(snapshot.data_gaps)
            reason = (
                "신규 상장 또는 짧은 거래 이력으로 1차 랭킹 데이터가 부족합니다. "
                f"관측 {snapshot.observations}개, 누락 항목은 {detail}입니다."
            )
            if gaps:
                reason = f"{reason} Yahoo 세부 정보는 {gaps}"
            return CandidateDiscoveryItem(
                market=member.market,
                score=0,
                ticker=member.ticker,
                sector=member.sector,
                verdict=DiscoveryVerdict.EXCLUDE,
                reasons=[reason],
                risks=["데이터 이력이 부족해 추세와 변동성 비교가 불가능합니다."],
                eod=None,
                source_url=snapshot.source_url,
            )

        metrics = self._metrics(snapshot)
        score = self._score(metrics, strategy)
        verdict = self._verdict(score, metrics.average_volume_20d)
        reasons = self._reasons(metrics, strategy)
        risks = self._risks(metrics)
        if verdict == DiscoveryVerdict.EXCLUDE and metrics.average_volume_20d < 1_000_000:
            reasons.insert(0, "20일 평균 거래량이 100만 주 미만이라 유동성 기준에서 제외했습니다.")
        return CandidateDiscoveryItem(
            market=member.market,
            score=score,
            ticker=member.ticker,
            sector=member.sector,
            verdict=verdict,
            reasons=reasons,
            risks=risks,
            eod=metrics,
            source_url=metrics.source_url,
        )

    @staticmethod
    def _failed_item(member: UniverseMember, exc: Exception) -> CandidateDiscoveryItem:
        detail = str(exc).strip() or exc.__class__.__name__
        return CandidateDiscoveryItem(
            market=member.market,
            score=0,
            ticker=member.ticker,
            sector=member.sector,
            verdict=DiscoveryVerdict.EXCLUDE,
            reasons=[f"Yahoo Finance 조회 실패로 제외했습니다. {detail}"],
            risks=["시장 데이터가 없어 정량 비교를 수행하지 못했습니다."],
            eod=None,
            source_url=None,
        )

    @staticmethod
    def _missing_scoring_data(snapshot: EODSnapshot) -> list[str]:
        missing: list[str] = []
        if snapshot.observations < 200:
            missing.append("완료 일봉 200개")
        required = {
            "5일 수익률": snapshot.return_5d_pct,
            "20일 수익률": snapshot.return_20d_pct,
            "60일 수익률": snapshot.return_60d_pct,
            "SMA20": snapshot.sma_20,
            "SMA50": snapshot.sma_50,
            "SMA200": snapshot.sma_200,
            "RSI14": snapshot.rsi_14,
            "20일 변동성": snapshot.volatility_20d_pct,
            "20일 평균 거래량": snapshot.average_volume_20d,
            "52주 고가": snapshot.high_52_week,
            "52주 저가": snapshot.low_52_week,
        }
        missing.extend(name for name, value in required.items() if value is None)
        return missing

    @staticmethod
    def _metrics(snapshot: EODSnapshot) -> DiscoveryEODMetrics:
        values = (
            snapshot.return_5d_pct,
            snapshot.return_20d_pct,
            snapshot.return_60d_pct,
            snapshot.sma_20,
            snapshot.sma_50,
            snapshot.sma_200,
            snapshot.rsi_14,
            snapshot.volatility_20d_pct,
            snapshot.average_volume_20d,
            snapshot.high_52_week,
            snapshot.low_52_week,
        )
        if any(value is None for value in values):
            raise ValueError("필수 EOD 지표가 누락되었습니다.")
        return DiscoveryEODMetrics(
            as_of_date=snapshot.as_of_date.isoformat(),
            current_close=snapshot.current_close,
            return_1d_pct=snapshot.return_1d_pct,
            return_5d_pct=cast(float, snapshot.return_5d_pct),
            return_20d_pct=cast(float, snapshot.return_20d_pct),
            return_60d_pct=cast(float, snapshot.return_60d_pct),
            sma_20=cast(float, snapshot.sma_20),
            sma_50=cast(float, snapshot.sma_50),
            sma_200=cast(float, snapshot.sma_200),
            rsi_14=cast(float, snapshot.rsi_14),
            volatility_20d_pct=cast(float, snapshot.volatility_20d_pct),
            average_volume_20d=cast(float, snapshot.average_volume_20d),
            high_52_week=cast(float, snapshot.high_52_week),
            low_52_week=cast(float, snapshot.low_52_week),
            observations=snapshot.observations,
            source_url=snapshot.source_url,
        )

    @classmethod
    def _score(cls, metrics: DiscoveryEODMetrics, strategy: DiscoveryStrategy) -> float:
        trend = sum(
            (
                cls._scale(metrics.current_close / metrics.sma_20 - 1, -0.10, 0.10),
                cls._scale(metrics.current_close / metrics.sma_50 - 1, -0.20, 0.20),
                cls._scale(metrics.current_close / metrics.sma_200 - 1, -0.30, 0.30),
                cls._range_position(metrics),
            )
        ) / 4
        momentum = sum(
            (
                cls._scale(metrics.return_5d_pct, -8, 8),
                cls._scale(metrics.return_20d_pct, -20, 20),
                cls._scale(metrics.return_60d_pct, -30, 40),
                cls._scale(metrics.rsi_14, 30, 70),
            )
        ) / 4
        stability = 100 - cls._scale(metrics.volatility_20d_pct, 15, 60)
        liquidity = cls._scale(math.log10(max(metrics.average_volume_20d, 1)), 6, 8)
        weights = _STRATEGY_WEIGHTS[strategy]
        score = sum(
            component * weight
            for component, weight in zip(
                (trend, momentum, stability, liquidity), weights, strict=True
            )
        )
        return round(cls._clamp(score, 0, 100), 2)

    @staticmethod
    def _verdict(score: float, average_volume: float) -> DiscoveryVerdict:
        if average_volume < 1_000_000 or score < 50:
            return DiscoveryVerdict.EXCLUDE
        if score >= 70:
            return DiscoveryVerdict.REVIEW_FIRST
        return DiscoveryVerdict.WATCH

    @staticmethod
    def _reasons(
        metrics: DiscoveryEODMetrics,
        strategy: DiscoveryStrategy,
    ) -> list[str]:
        above = sum(
            metrics.current_close > average
            for average in (metrics.sma_20, metrics.sma_50, metrics.sma_200)
        )
        return [
            f"종가가 SMA20·50·200 중 {above}개 위에 있습니다.",
            (
                f"5·20·60거래일 수익률은 {metrics.return_5d_pct:.1f}%, "
                f"{metrics.return_20d_pct:.1f}%, {metrics.return_60d_pct:.1f}%입니다."
            ),
            (
                f"{strategy.value} 전략에서 연환산 20일 변동성 "
                f"{metrics.volatility_20d_pct:.1f}%를 반영했습니다."
            ),
            f"20일 평균 거래량은 {metrics.average_volume_20d:,.0f}주입니다.",
        ]

    @staticmethod
    def _risks(metrics: DiscoveryEODMetrics) -> list[str]:
        risks = ["실적·밸류에이션·뉴스를 반영하지 않은 가격·거래량 기반 1차 결과입니다."]
        if metrics.volatility_20d_pct >= 45:
            risks.append("최근 변동성이 높아 순위가 빠르게 바뀔 수 있습니다.")
        if metrics.rsi_14 >= 70:
            risks.append("RSI14가 70 이상으로 단기 과열 가능성이 있습니다.")
        elif metrics.rsi_14 <= 30:
            risks.append("RSI14가 30 이하로 하락 추세 지속 가능성이 있습니다.")
        if metrics.current_close < metrics.sma_200:
            risks.append("종가가 SMA200 아래여서 장기 추세가 약합니다.")
        if metrics.return_20d_pct < 0:
            risks.append("20거래일 수익률이 음수입니다.")
        return risks

    @classmethod
    def _range_position(cls, metrics: DiscoveryEODMetrics) -> float:
        span = metrics.high_52_week - metrics.low_52_week
        if span <= 0:
            return 50
        position = (metrics.current_close - metrics.low_52_week) / span
        return cls._clamp(position * 100, 0, 100)

    @classmethod
    def _scale(cls, value: float, low: float, high: float) -> float:
        if high <= low:
            raise ValueError("정규화 상한은 하한보다 커야 합니다.")
        return cls._clamp((value - low) / (high - low) * 100, 0, 100)

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))
