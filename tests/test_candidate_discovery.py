# EOD 종목 발굴기의 병렬 조회, 전략별 순위와 제외 사유를 검증한다.
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest

from investment_office.services.candidate_discovery import (
    KR_STARTER_UNIVERSE,
    SAFETY_NOTICE,
    STARTER_UNIVERSE,
    CandidateDiscoveryService,
    DiscoveryStrategy,
    DiscoveryVerdict,
    UniverseMember,
)
from investment_office.services.market_data import EODSnapshot, YahooFinanceError
from investment_office.services.research_contracts import MarketId


def snapshot(
    ticker: str,
    *,
    return_5d: float = 3,
    return_20d: float = 8,
    return_60d: float = 18,
    volatility: float = 25,
    volume: float = 5_000_000,
    observations: int = 260,
) -> EODSnapshot:
    has_history = observations >= 200
    return EODSnapshot(
        ticker=ticker,
        exchange="NMS",
        currency="USD",
        timezone="America/New_York",
        as_of_date=date(2026, 7, 10),
        source_url=f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
        fetched_at=datetime(2026, 7, 11, tzinfo=UTC),
        observations=max(observations, 2),
        current_close=120,
        previous_close=119,
        return_1d_pct=0.84,
        return_5d_pct=return_5d if observations >= 6 else None,
        return_20d_pct=return_20d if observations >= 21 else None,
        return_60d_pct=return_60d if observations >= 61 else None,
        sma_20=110 if observations >= 20 else None,
        sma_50=105 if observations >= 50 else None,
        sma_200=100 if has_history else None,
        rsi_14=62 if observations >= 15 else None,
        atr_14=3 if observations >= 15 else None,
        volatility_20d_pct=volatility if observations >= 21 else None,
        high_52_week=130 if observations >= 252 else None,
        low_52_week=80 if observations >= 252 else None,
        average_volume_20d=volume if observations >= 20 else None,
        data_gaps=[] if has_history else ["SMA200에는 종가 200개가 필요합니다."],
    )


class FakeMarketData:
    def __init__(self, responses: dict[str, EODSnapshot | Exception]) -> None:
        self.responses = responses
        self.active = 0
        self.max_active = 0
        self.calls: list[str] = []

    async def fetch_eod_snapshot(self, ticker: str) -> EODSnapshot:
        self.calls.append(ticker)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.005)
            response = self.responses[ticker]
            if isinstance(response, Exception):
                raise response
            return response
        finally:
            self.active -= 1


def test_starter_universe_is_explicit_unique_and_sector_diversified() -> None:
    tickers = [member.ticker for member in STARTER_UNIVERSE]
    sectors = {member.sector for member in STARTER_UNIVERSE}

    assert 24 <= len(STARTER_UNIVERSE) <= 36
    assert len(tickers) == len(set(tickers))
    assert len(sectors) >= 8
    assert len(KR_STARTER_UNIVERSE) == 30
    assert all(member.market is MarketId.KR for member in KR_STARTER_UNIVERSE)


@pytest.mark.asyncio
async def test_korean_screen_uses_canonical_storage_ticker() -> None:
    universe = (
        UniverseMember(market=MarketId.KR, ticker="005930", sector="semiconductors"),
    )
    market = FakeMarketData({"KR-005930": snapshot("005930")})
    service = CandidateDiscoveryService(market_data=market, universe=universe)

    result = await service.screen(market=MarketId.KR, limit=1)

    assert market.calls == ["KR-005930"]
    assert result.market is MarketId.KR
    assert result.candidates[0].ticker == "005930"
    assert result.candidates[0].market is MarketId.KR


@pytest.mark.asyncio
async def test_screen_respects_concurrency_limit_and_returns_deterministic_ranking() -> None:
    universe = (
        UniverseMember(ticker="AAPL", sector="technology"),
        UniverseMember(ticker="MSFT", sector="technology"),
        UniverseMember(ticker="JPM", sector="financials"),
    )
    market = FakeMarketData(
        {
            "AAPL": snapshot("AAPL", return_20d=18, return_60d=35),
            "MSFT": snapshot("MSFT", return_20d=8, return_60d=18),
            "JPM": snapshot(
                "JPM", return_5d=-8, return_20d=-20, return_60d=-30, volatility=60
            ),
        }
    )
    service = CandidateDiscoveryService(
        market_data=market,
        max_concurrency=2,
        universe=universe,
    )

    result = await service.screen("balanced", limit=2)

    assert market.max_active == 2
    assert result.safety_notice == SAFETY_NOTICE
    assert [item.ticker for item in result.candidates] == ["AAPL", "MSFT"]
    assert result.qualified_count == 2
    assert result.omitted_count == 0
    assert [item.rank for item in result.candidates] == [1, 2]
    assert result.candidates[0].score > result.candidates[1].score
    assert all(item.source_url for item in result.candidates)
    assert result.excluded[0].ticker == "JPM"
    assert result.excluded[0].verdict == DiscoveryVerdict.EXCLUDE

    limited = await service.screen("balanced", limit=1)
    assert limited.qualified_count == 2
    assert limited.omitted_count == 1


@pytest.mark.asyncio
async def test_strategy_changes_weighting_without_changing_input_data() -> None:
    universe = (
        UniverseMember(ticker="FAST", sector="technology"),
        UniverseMember(ticker="CALM", sector="consumer_staples"),
    )
    market = FakeMarketData(
        {
            "FAST": snapshot(
                "FAST", return_5d=8, return_20d=20, return_60d=40, volatility=60
            ),
            "CALM": snapshot(
                "CALM", return_5d=1, return_20d=4, return_60d=8, volatility=15
            ),
        }
    )
    service = CandidateDiscoveryService(market_data=market, universe=universe)

    momentum = await service.screen(DiscoveryStrategy.MOMENTUM, limit=2)
    defensive = await service.screen(DiscoveryStrategy.DEFENSIVE, limit=2)

    assert momentum.candidates[0].ticker == "FAST"
    assert defensive.candidates[0].ticker == "CALM"


@pytest.mark.asyncio
async def test_data_shortage_and_lookup_failure_are_excluded_without_failing_screen() -> None:
    universe = (
        UniverseMember(ticker="GOOD", sector="technology"),
        UniverseMember(ticker="NEW", sector="technology"),
        UniverseMember(ticker="FAIL", sector="financials"),
    )
    market = FakeMarketData(
        {
            "GOOD": snapshot("GOOD"),
            "NEW": snapshot("NEW", observations=20),
            "FAIL": YahooFinanceError("HTTP 429 응답"),
        }
    )
    service = CandidateDiscoveryService(market_data=market, universe=universe)

    result = await service.screen("balanced", limit=5)

    assert [item.ticker for item in result.candidates] == ["GOOD"]
    excluded = {item.ticker: item for item in result.excluded}
    assert "신규 상장 또는 짧은 거래 이력" in excluded["NEW"].reasons[0]
    assert "관측 20개" in excluded["NEW"].reasons[0]
    assert excluded["NEW"].source_url is not None
    assert "Yahoo Finance 조회 실패" in excluded["FAIL"].reasons[0]
    assert "HTTP 429" in excluded["FAIL"].reasons[0]
    assert excluded["FAIL"].source_url is None
    assert result.evaluated_count == 1
    assert result.qualified_count == 1
    assert result.omitted_count == 0


@pytest.mark.asyncio
async def test_validates_public_screen_arguments() -> None:
    service = CandidateDiscoveryService(
        market_data=FakeMarketData({"AAPL": snapshot("AAPL")}),
        universe=(UniverseMember(ticker="AAPL", sector="technology"),),
    )

    with pytest.raises(ValueError, match="strategy"):
        await service.screen("aggressive")
    with pytest.raises(ValueError, match="limit"):
        await service.screen(limit=0)
