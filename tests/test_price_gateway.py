# 미국과 한국 가격 게이트웨이의 선택, 변환, 실패 경계를 네트워크 없이 검증한다
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest

from investment_office.services.market_data import EODSnapshot, YahooFinanceClient
from investment_office.services.price_gateway import (
    CommitteePriceGateway,
    InsufficientPriceDataError,
    KoreaPublicDataPriceProvider,
    MarketPriceGateway,
    MissingPriceApiKeyError,
    PriceMarketMismatchError,
    PriceProviderResponseError,
    UnsupportedPriceMarketError,
    build_default_price_gateway,
    build_kr_eod_snapshot,
    parse_kr_daily_bars,
)
from investment_office.services.research_contracts import InstrumentRef, MarketId

NOW = datetime(2026, 1, 2, 12, tzinfo=UTC)


class RecordingProvider:
    def __init__(self, market: MarketId) -> None:
        self.market = market
        self.requested: list[InstrumentRef] = []

    async def fetch_eod_snapshot(self, instrument: InstrumentRef) -> EODSnapshot:
        self.requested.append(instrument)
        return EODSnapshot(
            ticker=instrument.symbol,
            exchange=instrument.exchange,
            currency=instrument.currency,
            timezone=("America/New_York" if instrument.market is MarketId.US else "Asia/Seoul"),
            as_of_date=date(2026, 1, 1),
            source_url="https://example.com/prices",
            fetched_at=NOW,
            observations=2,
            current_close=101,
            previous_close=100,
            return_1d_pct=1,
            return_5d_pct=None,
            return_20d_pct=None,
            return_60d_pct=None,
            sma_20=None,
            sma_50=None,
            sma_200=None,
            rsi_14=None,
            atr_14=None,
            volatility_20d_pct=None,
            high_52_week=None,
            low_52_week=None,
            average_volume_20d=None,
        )


def _instrument(
    market: MarketId = MarketId.KR,
    *,
    symbol: str | None = None,
    exchange: str | None = None,
) -> InstrumentRef:
    if market is MarketId.KR:
        return InstrumentRef(
            market=market,
            symbol=symbol or "005930",
            name="삼성전자",
            exchange=exchange or "KRX",
            currency="KRW",
        )
    return InstrumentRef(
        market=market,
        symbol=symbol or "AAPL",
        name="Apple",
        exchange=exchange or "NASDAQ",
        currency="USD",
    )


def _kr_items(count: int, *, market: str = "KOSPI") -> list[dict[str, str]]:
    start = date(2024, 1, 2)
    items = []
    for index in range(count):
        close = 100 + index
        items.append(
            {
                "basDt": (start + timedelta(days=index)).strftime("%Y%m%d"),
                "srtnCd": "005930",
                "isinCd": "KR7005930003",
                "itmsNm": "삼성전자",
                "mrktCtg": market,
                "clpr": str(close),
                "mkp": str(close - 1),
                "hipr": str(close + 2),
                "lopr": str(close - 2),
                "trqu": str(1_000_000 + index),
            }
        )
    return list(reversed(items))


def _kr_payload(items: object, *, result_code: str = "00") -> dict[str, Any]:
    return {
        "response": {
            "header": {
                "resultCode": result_code,
                "resultMsg": "정상" if result_code == "00" else "인증 실패",
            },
            "body": {
                "numOfRows": 500,
                "pageNo": 1,
                "totalCount": len(items) if isinstance(items, list) else 0,
                "items": {"item": items},
            },
        }
    }


def _yahoo_payload() -> dict[str, Any]:
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "currency": "USD",
                        "symbol": "AAPL",
                        "exchangeName": "NMS",
                        "instrumentType": "EQUITY",
                        "exchangeTimezoneName": "America/New_York",
                        "currentTradingPeriod": {
                            "regular": {"start": 1_900_000_000, "end": 1_900_023_400}
                        },
                    },
                    "timestamp": [1_704_110_400, 1_704_196_800],
                    "indicators": {
                        "quote": [
                            {
                                "open": [99.0, 100.0],
                                "high": [102.0, 103.0],
                                "low": [98.0, 99.0],
                                "close": [100.0, 101.0],
                                "volume": [1_000_000, 1_100_000],
                            }
                        ],
                        "adjclose": [{"adjclose": [100.0, 101.0]}],
                    },
                }
            ],
            "error": None,
        }
    }


@pytest.mark.asyncio
async def test_default_gateway_routes_us_to_existing_yahoo_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_yahoo_payload(), request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        gateway = build_default_price_gateway(
            yahoo_client=YahooFinanceClient(client=http_client, now_factory=lambda: NOW)
        )
        snapshot = await gateway.fetch_eod_snapshot(_instrument(MarketId.US))
    finally:
        await http_client.aclose()

    assert snapshot.ticker == "AAPL"
    assert snapshot.currency == "USD"
    assert snapshot.current_close == 101.0


@pytest.mark.asyncio
async def test_committee_gateway_converts_storage_tickers_to_market_instruments() -> None:
    us_provider = RecordingProvider(MarketId.US)
    kr_provider = RecordingProvider(MarketId.KR)
    client = CommitteePriceGateway(MarketPriceGateway((us_provider, kr_provider)))

    await client.fetch_eod_snapshot("AAPL")
    await client.fetch_eod_snapshot("KR-005930")

    assert us_provider.requested[0].symbol == "AAPL"
    assert us_provider.requested[0].market is MarketId.US
    assert kr_provider.requested[0].symbol == "005930"
    assert kr_provider.requested[0].exchange == "KRX"


@pytest.mark.asyncio
async def test_default_gateway_fetches_and_computes_korea_eod_snapshot() -> None:
    observed_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_request
        observed_request = request
        return httpx.Response(200, json=_kr_payload(_kr_items(260)), request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        gateway = build_default_price_gateway(
            korea_service_key="encoded%2Bkey",
            korea_client=http_client,
            now_factory=lambda: NOW,
        )
        snapshot = await gateway.fetch_eod_snapshot(_instrument())
    finally:
        await http_client.aclose()

    assert observed_request is not None
    assert observed_request.url.params["serviceKey"] == "encoded+key"
    assert observed_request.url.params["resultType"] == "json"
    assert observed_request.url.params["likeSrtnCd"] == "005930"
    assert observed_request.url.params["numOfRows"] == "500"
    assert snapshot.ticker == "005930"
    assert snapshot.exchange == "KRX"
    assert snapshot.currency == "KRW"
    assert snapshot.timezone == "Asia/Seoul"
    assert snapshot.observations == 260
    assert snapshot.current_close == 359.0
    assert snapshot.previous_close == 358.0
    assert snapshot.return_20d_pct == pytest.approx((359 / 339 - 1) * 100, abs=1e-4)
    assert snapshot.sma_20 == 349.5
    assert snapshot.high_52_week == 361.0
    assert snapshot.low_52_week == 106.0
    assert snapshot.average_volume_20d == 1_000_249.5
    assert snapshot.as_of_date == date(2024, 9, 17)
    assert snapshot.source_url.startswith("https://apis.data.go.kr/")
    assert "encoded" not in snapshot.source_url
    assert any("조정주가가 아니므로" in gap for gap in snapshot.data_gaps)


def test_pure_korea_parser_sorts_and_preserves_ohlcv() -> None:
    items = _kr_items(3)

    bars, gaps = parse_kr_daily_bars(_instrument(), items)

    assert [bar.trade_date for bar in bars] == [
        date(2024, 1, 2),
        date(2024, 1, 3),
        date(2024, 1, 4),
    ]
    assert bars[-1].open == 101.0
    assert bars[-1].high == 104.0
    assert bars[-1].low == 100.0
    assert bars[-1].close == 102.0
    assert bars[-1].volume == 1_000_002.0
    assert gaps == [
        "공공데이터포털 시세는 조정주가가 아니므로 기업행사 전후 지표가 왜곡될 수 있습니다."
    ]


def test_pure_snapshot_reports_invalid_and_missing_values_as_data_gaps() -> None:
    items = _kr_items(3)
    items[0]["basDt"] = "잘못된 날짜"
    items[1]["hipr"] = ""
    items[1]["trqu"] = ""

    snapshot = build_kr_eod_snapshot(
        _instrument(),
        items,
        source_url="https://example.com/price",
        fetched_at=NOW,
    )

    assert snapshot.observations == 2
    assert any("1개를 제외" in gap for gap in snapshot.data_gaps)
    assert any("고가가 없는 일봉" in gap for gap in snapshot.data_gaps)
    assert any("거래량이 없는 일봉" in gap for gap in snapshot.data_gaps)


@pytest.mark.asyncio
async def test_korea_provider_requires_api_key_before_network() -> None:
    provider = KoreaPublicDataPriceProvider(None)

    with pytest.raises(MissingPriceApiKeyError, match="인증키"):
        await provider.fetch_eod_snapshot(_instrument())


@pytest.mark.asyncio
async def test_korea_provider_surfaces_api_result_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_kr_payload([], result_code="30"), request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        provider = KoreaPublicDataPriceProvider(
            "secret",
            client=http_client,
            now_factory=lambda: NOW,
        )
        with pytest.raises(PriceProviderResponseError, match="30 인증 실패"):
            await provider.fetch_eod_snapshot(_instrument())
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_korea_provider_does_not_leak_key_in_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        provider = KoreaPublicDataPriceProvider("highly-secret", client=http_client)
        with pytest.raises(PriceProviderResponseError) as caught:
            await provider.fetch_eod_snapshot(_instrument())
    finally:
        await http_client.aclose()

    assert "highly-secret" not in str(caught.value)
    assert "503" in str(caught.value)


@pytest.mark.asyncio
async def test_korea_provider_rejects_insufficient_history() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_kr_payload(_kr_items(1)), request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        provider = KoreaPublicDataPriceProvider(
            "secret",
            client=http_client,
            now_factory=lambda: NOW,
        )
        with pytest.raises(InsufficientPriceDataError, match="2개 미만"):
            await provider.fetch_eod_snapshot(_instrument())
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_provider_rejects_instrument_from_another_market() -> None:
    provider = KoreaPublicDataPriceProvider("secret")

    with pytest.raises(PriceMarketMismatchError, match="kr 시장 공급자에 us"):
        await provider.fetch_eod_snapshot(_instrument(MarketId.US))


def test_parser_rejects_non_korea_response_market() -> None:
    with pytest.raises(PriceMarketMismatchError, match="한국 주식시장이 아닙니다"):
        parse_kr_daily_bars(_instrument(), _kr_items(2, market="NYSE"))


def test_parser_rejects_response_symbol_mismatch() -> None:
    items = _kr_items(2)
    items[0]["srtnCd"] = "000660"

    with pytest.raises(PriceProviderResponseError, match="요청과 다릅니다"):
        parse_kr_daily_bars(_instrument(), items)


def test_parser_rejects_impossible_ohlc_values() -> None:
    items = _kr_items(2)
    items[0]["hipr"] = "50"

    with pytest.raises(PriceProviderResponseError, match="고가보다"):
        parse_kr_daily_bars(_instrument(), items)


@pytest.mark.asyncio
async def test_gateway_rejects_market_without_registered_provider() -> None:
    gateway = MarketPriceGateway(())

    with pytest.raises(UnsupportedPriceMarketError, match="등록되지 않았습니다"):
        await gateway.fetch_eod_snapshot(_instrument())
