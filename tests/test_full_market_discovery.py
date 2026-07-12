# 전체시장 추천이 재무를 먼저 적용하고 단계별 수량과 최종 순위를 남기는지 검증한다.
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from investment_office.services.bulk_fundamentals import BulkFundamentalsBatch
from investment_office.services.discovery_jobs import (
    DiscoveryJobStatus,
    DiscoveryProgressUpdate,
    DiscoveryStage,
)
from investment_office.services.full_market_discovery import (
    FullMarketDiscoveryService,
    _company_outlook_score,
)
from investment_office.services.fundamental_screening import (
    AnnualFundamentals,
    IndustryModel,
    ScreeningFundamentals,
)
from investment_office.services.market_data import EODSnapshot
from investment_office.services.research_contracts import MarketId
from investment_office.services.universe_catalog import (
    UniverseCatalogMember,
    UniverseSnapshot,
    UniverseTier,
)


def member(ticker: str, sector: str = "technology") -> UniverseCatalogMember:
    return UniverseCatalogMember(
        market=MarketId.US,
        ticker=ticker,
        company_name=f"{ticker} Company",
        exchange="Nasdaq",
        issuer_id=f"sec:{ticker}",
        cik=100 + len(ticker),
        tiers=tuple(UniverseTier),
        industry=sector,
    )


def fundamentals(
    ticker: str,
    *,
    profitable: bool = True,
    sector: str = "technology",
    revenues: tuple[float, float, float] = (100.0, 115.0, 135.0),
) -> ScreeningFundamentals:
    net = (8.0, 10.0, 12.0) if profitable else (4.0, -2.0, -3.0)
    cash = (10.0, 12.0, 14.0) if profitable else (4.0, -1.0, -2.0)
    return ScreeningFundamentals(
        market=MarketId.US,
        ticker=ticker,
        company_name=f"{ticker} Company",
        sector=sector,
        industry_model=IndustryModel.GENERAL,
        currency="USD",
        periods=tuple(
            AnnualFundamentals(
                fiscal_year=year,
                revenue=revenue,
                operating_income=income * 1.4,
                net_income=income,
                operating_cash_flow=operating_cash_flow,
                free_cash_flow=operating_cash_flow * 0.7,
                equity=100,
                assets=190,
                liabilities=90,
            )
            for year, revenue, income, operating_cash_flow in zip(
                (2023, 2024, 2025),
                revenues,
                net,
                cash,
                strict=True,
            )
        ),
        latest_report_date=date(2026, 2, 20),
        source_urls=("https://www.sec.gov/",),
        trailing_pe=18,
        price_to_book=2,
    )


def eod(ticker: str, *, return_60d: float, volume: float = 2_000_000) -> EODSnapshot:
    return EODSnapshot(
        ticker=ticker,
        exchange="NMS",
        currency="USD",
        timezone="America/New_York",
        as_of_date=date(2026, 7, 10),
        source_url=f"https://example.com/prices/{ticker}",
        fetched_at=datetime(2026, 7, 11, tzinfo=UTC),
        observations=260,
        current_close=120,
        previous_close=119,
        return_1d_pct=0.84,
        return_5d_pct=3,
        return_20d_pct=8,
        return_60d_pct=return_60d,
        sma_20=110,
        sma_50=105,
        sma_200=100,
        rsi_14=62,
        atr_14=3,
        volatility_20d_pct=25,
        high_52_week=130,
        low_52_week=80,
        average_volume_20d=volume,
        data_gaps=[],
    )


class FakeCatalog:
    supported_markets = frozenset({MarketId.US})

    def __init__(self, members: tuple[UniverseCatalogMember, ...]) -> None:
        self.members = members

    async def load_snapshot(
        self,
        market: MarketId,
        *,
        force_refresh: bool = False,
    ) -> UniverseSnapshot:
        del force_refresh
        return UniverseSnapshot(
            market=market,
            provider_id="test:full-market",
            source_url="https://example.com/universe",
            source_documentation_url="https://example.com/universe-guide",
            source_urls=("https://example.com/universe",),
            retrieved_at=datetime(2026, 7, 13, tzinfo=UTC),
            members=self.members,
            raw_count=len(self.members) + 1,
            excluded_count=1,
            duplicate_count=0,
        )


class FakeFundamentals:
    supported_markets = frozenset({MarketId.US})

    def __init__(self, items: tuple[ScreeningFundamentals, ...]) -> None:
        self.items = items

    async def fetch_many(
        self,
        snapshot: UniverseSnapshot,
        *,
        progress=None,
        force_refresh: bool = False,
    ) -> BulkFundamentalsBatch:
        del force_refresh
        if progress is not None:
            await progress(len(snapshot.members), len(snapshot.members), 0)
        return BulkFundamentalsBatch(
            market=snapshot.market,
            retrieved_at=datetime(2026, 7, 13, tzinfo=UTC),
            items=self.items,
            requested_count=len(snapshot.members),
            source_urls=("https://example.com/fundamentals",),
        )


class FakeMarketData:
    def __init__(self, responses: dict[str, EODSnapshot | Exception]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    async def fetch_eod_snapshot(self, ticker: str) -> EODSnapshot:
        self.calls.append(ticker)
        response = self.responses[ticker]
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.asyncio
async def test_full_market_pipeline_filters_fundamentals_before_price_calls() -> None:
    members = tuple(member(ticker) for ticker in ("AAA", "BBB", "CCC", "DDD", "LOSS"))
    batch = tuple(
        [fundamentals(ticker) for ticker in ("AAA", "BBB", "CCC", "DDD")]
        + [fundamentals("LOSS", profitable=False)]
    )
    market = FakeMarketData(
        {
            "AAA": eod("AAA", return_60d=35),
            "BBB": eod("BBB", return_60d=25),
            "CCC": eod("CCC", return_60d=15),
            "DDD": eod("DDD", return_60d=5),
        }
    )
    service = FullMarketDiscoveryService(
        universe_catalog=FakeCatalog(members),
        fundamentals=FakeFundamentals(batch),
        market_data=market,
        max_price_concurrency=2,
    )
    updates: list[DiscoveryProgressUpdate] = []

    async def progress(update: DiscoveryProgressUpdate) -> None:
        updates.append(update)

    outcome = await service.screen(
        market="us",
        strategy="balanced",
        risk_profile="balanced",
        limit=3,
        progress=progress,
    )

    assert outcome.status is DiscoveryJobStatus.COMPLETE
    assert set(market.calls) == {"AAA", "BBB", "CCC", "DDD"}
    assert "LOSS" not in market.calls
    result = outcome.result
    assert isinstance(result, dict)
    assert result["universe_size"] == 5
    assert result["fundamentals_passed_count"] == 4
    assert result["fundamentals_excluded_count"] == 1
    assert result["fundamentals_insufficient_count"] == 0
    assert result["fundamentals_special_review_count"] == 0
    assert result["liquidity_passed_count"] == 4
    assert len(result["candidates"]) == 3
    assert [item["ticker"] for item in result["candidates"]] == ["AAA", "BBB", "CCC"]
    assert all("outlook" in item["breakdown"] for item in result["candidates"])
    fundamentals_updates = [
        update for update in updates if update.stage is DiscoveryStage.FUNDAMENTALS
    ]
    assert fundamentals_updates[0].processed == 0
    assert fundamentals_updates[0].message == (
        "미국 전체 재무 파일을 내려받아 상장 원장과 연결하고 있습니다."
    )
    completed_stages = {update.stage for update in updates if update.completed}
    assert completed_stages == set(DiscoveryStage)


@pytest.mark.asyncio
async def test_price_failures_are_partial_instead_of_normal_zero_result() -> None:
    members = tuple(member(ticker) for ticker in ("AAA", "BBB", "CCC"))
    market = FakeMarketData(
        {
            "AAA": eod("AAA", return_60d=25),
            "BBB": RuntimeError("가격 공급원 실패"),
            "CCC": eod("CCC", return_60d=5, volume=10),
        }
    )
    service = FullMarketDiscoveryService(
        universe_catalog=FakeCatalog(members),
        fundamentals=FakeFundamentals(tuple(fundamentals(item.ticker) for item in members)),
        market_data=market,
    )

    async def progress(update: DiscoveryProgressUpdate) -> None:
        del update

    outcome = await service.screen(
        market=MarketId.US,
        strategy="balanced",
        risk_profile="balanced",
        limit=3,
        progress=progress,
    )

    assert outcome.status is DiscoveryJobStatus.PARTIAL
    assert isinstance(outcome.result, dict)
    assert len(outcome.result["candidates"]) == 1
    assert outcome.result["price_data_failure_count"] == 1
    assert outcome.result["liquidity_excluded_count"] == 1
    assert "일부 자료 공백" in (outcome.message or "")


@pytest.mark.asyncio
async def test_liquidity_filtering_alone_is_not_reported_as_partial_data_failure() -> None:
    members = tuple(member(ticker) for ticker in ("AAA", "BBB", "CCC", "DDD"))
    market = FakeMarketData(
        {
            "AAA": eod("AAA", return_60d=25),
            "BBB": eod("BBB", return_60d=10, volume=10),
            "CCC": eod("CCC", return_60d=5, volume=10),
            "DDD": eod("DDD", return_60d=0, volume=10),
        }
    )
    service = FullMarketDiscoveryService(
        universe_catalog=FakeCatalog(members),
        fundamentals=FakeFundamentals(
            tuple(fundamentals(item.ticker) for item in members)
        ),
        market_data=market,
    )

    async def progress(update: DiscoveryProgressUpdate) -> None:
        del update

    outcome = await service.screen(
        market=MarketId.US,
        strategy="balanced",
        risk_profile="balanced",
        limit=3,
        progress=progress,
    )

    assert outcome.status is DiscoveryJobStatus.COMPLETE
    assert isinstance(outcome.result, dict)
    assert outcome.result["liquidity_excluded_count"] == 3
    assert outcome.result["price_data_failure_count"] == 0


@pytest.mark.asyncio
async def test_thin_sector_does_not_reuse_one_stock_return_as_sector_momentum() -> None:
    members = (
        member("AAA", sector="희소 업종"),
        member("BBB", sector="비교 업종"),
        member("CCC", sector="비교 업종"),
    )
    market = FakeMarketData(
        {
            "AAA": eod("AAA", return_60d=80),
            "BBB": eod("BBB", return_60d=-20),
            "CCC": eod("CCC", return_60d=-20),
        }
    )
    service = FullMarketDiscoveryService(
        universe_catalog=FakeCatalog(members),
        fundamentals=FakeFundamentals(
            tuple(
                fundamentals(
                    item.ticker,
                    sector=item.industry or "미분류",
                    revenues=(100.0, 180.0, 300.0)
                    if item.ticker == "AAA"
                    else (100.0, 100.0, 100.0),
                )
                for item in members
            )
        ),
        market_data=market,
    )

    async def progress(update: DiscoveryProgressUpdate) -> None:
        del update

    outcome = await service.screen(
        market=MarketId.US,
        strategy="balanced",
        risk_profile="balanced",
        limit=3,
        progress=progress,
    )

    assert isinstance(outcome.result, dict)
    sector_scores = {
        candidate["ticker"]: candidate["breakdown"]["sector"]
        for candidate in outcome.result["candidates"]
    }
    assert sector_scores["AAA"] == sector_scores["BBB"] == sector_scores["CCC"]


def test_company_outlook_score_rewards_recent_acceleration_before_shortlist() -> None:
    accelerating = fundamentals(
        "FAST",
        revenues=(100.0, 110.0, 150.0),
    )
    slowing = fundamentals(
        "SLOW",
        revenues=(100.0, 150.0, 160.0),
    )

    assert _company_outlook_score(accelerating) > _company_outlook_score(slowing)
