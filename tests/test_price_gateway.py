# 미국과 한국 가격 게이트웨이의 선택, 변환, 실패 경계를 네트워크 없이 검증한다
from __future__ import annotations

import traceback
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest

from investment_office.services.market_data import EODSnapshot, YahooFinanceClient
from investment_office.services.price_gateway import (
    CommitteePriceGateway,
    InsufficientPriceDataError,
    KoreaPublicDataPriceProvider,
    KoreaYahooPriceProvider,
    MarketPriceGateway,
    MissingPriceApiKeyError,
    PriceMarketMismatchError,
    PriceProviderResponseError,
    TiingoPriceProvider,
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


def _yahoo_kr_payload(
    *,
    symbol: str = "005930.KS",
    exchange: str = "KSC",
    currency: str = "KRW",
    timezone: str = "Asia/Seoul",
    instrument_type: str = "EQUITY",
) -> dict[str, Any]:
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "currency": currency,
                        "symbol": symbol,
                        "exchangeName": exchange,
                        "instrumentType": instrument_type,
                        "exchangeTimezoneName": timezone,
                        "currentTradingPeriod": {
                            "regular": {"start": 1_900_000_000, "end": 1_900_023_400}
                        },
                    },
                    "timestamp": [1_704_110_400, 1_704_196_800],
                    "indicators": {
                        "quote": [
                            {
                                "open": [69_500.0, 70_000.0],
                                "high": [70_500.0, 71_000.0],
                                "low": [69_000.0, 69_800.0],
                                "close": [70_000.0, 70_500.0],
                                "volume": [10_000_000, 11_000_000],
                            }
                        ],
                        "adjclose": [{"adjclose": [69_800.0, 70_300.0]}],
                    },
                }
            ],
            "error": None,
        }
    }


def _tiingo_meta(
    *,
    ticker: str = "AAPL",
    exchange: str = "NASDAQ",
    start_date: str = "1980-12-12",
    end_date: str = "2026-01-02",
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "name": "Example Company",
        "exchangeCode": exchange,
        "startDate": start_date,
        "endDate": end_date,
    }


def _tiingo_prices(
    dates: list[str],
    *,
    adjusted_closes: list[float] | None = None,
) -> list[dict[str, Any]]:
    closes = adjusted_closes or [100.0 + index for index in range(len(dates))]
    return [
        {
            "date": f"{trade_date}T00:00:00.000Z",
            "open": close * 2 - 2,
            "high": close * 2 + 4,
            "low": close * 2 - 4,
            "close": close * 2,
            "volume": 2_000_000 + index,
            "adjOpen": close - 1,
            "adjHigh": close + 2,
            "adjLow": close - 2,
            "adjClose": close,
            "adjVolume": 1_000_000 + index,
            "divCash": 0,
            "splitFactor": 1,
        }
        for index, (trade_date, close) in enumerate(zip(dates, closes, strict=True))
    ]


@pytest.mark.asyncio
async def test_default_gateway_does_not_use_yahoo_without_tiingo_token() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_yahoo_payload(), request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        gateway = build_default_price_gateway(
            yahoo_client=YahooFinanceClient(client=http_client, now_factory=lambda: NOW)
        )
        with pytest.raises(MissingPriceApiKeyError, match="Tiingo"):
            await gateway.fetch_eod_snapshot(_instrument(MarketId.US))
    finally:
        await http_client.aclose()

    assert calls == 0


@pytest.mark.asyncio
async def test_tiingo_provider_uses_adjusted_bars_and_header_auth_without_secret_leak() -> None:
    requests: list[httpx.Request] = []
    secret = "very-private-tiingo-token"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/prices"):
            payload: object = _tiingo_prices(
                ["2024-01-02", "2024-01-03"],
                adjusted_closes=[50.0, 51.0],
            )
        else:
            payload = _tiingo_meta()
        return httpx.Response(200, json=payload, request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        provider = TiingoPriceProvider(
            secret,
            client=http_client,
            now_factory=lambda: NOW,
        )
        snapshot = await provider.fetch_eod_snapshot(_instrument(MarketId.US))
    finally:
        await http_client.aclose()

    assert len(requests) == 2
    assert all(request.headers["authorization"] == f"Token {secret}" for request in requests)
    assert all(secret not in str(request.url) for request in requests)
    assert requests[1].url.params["startDate"] == "2024-01-02"
    assert requests[1].url.params["endDate"] == "2026-01-02"
    assert requests[1].url.params["resampleFreq"] == "daily"
    assert snapshot.current_close == 51.0
    assert snapshot.previous_close == 50.0
    assert snapshot.exchange == "NASDAQ"
    assert snapshot.source_url.startswith("https://api.tiingo.com/tiingo/daily/AAPL/prices")
    assert secret not in snapshot.source_url
    assert [bar.trade_date for bar in snapshot.raw_bars] == [
        date(2024, 1, 2),
        date(2024, 1, 3),
    ]
    assert snapshot.raw_bars[0].open == 49.0
    assert snapshot.raw_bars[0].high == 52.0
    assert snapshot.raw_bars[0].low == 48.0
    assert snapshot.raw_bars[0].close == 50.0
    assert snapshot.raw_bars[0].volume == 1_000_000.0


@pytest.mark.asyncio
async def test_tiingo_provider_uses_dash_for_class_share_symbol() -> None:
    observed_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_paths.append(request.url.path)
        payload: object = (
            _tiingo_prices(["2024-01-02", "2024-01-03"])
            if request.url.path.endswith("/prices")
            else _tiingo_meta(ticker="BRK-B", exchange="NYSE")
        )
        return httpx.Response(200, json=payload, request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        snapshot = await TiingoPriceProvider(
            "secret",
            client=http_client,
            now_factory=lambda: NOW,
        ).fetch_eod_snapshot(_instrument(MarketId.US, symbol="BRK.B", exchange="NYSE"))
    finally:
        await http_client.aclose()

    assert observed_paths == [
        "/tiingo/daily/BRK-B",
        "/tiingo/daily/BRK-B/prices",
    ]
    assert snapshot.ticker == "BRK.B"


@pytest.mark.asyncio
async def test_tiingo_provider_excludes_unconfirmed_current_eastern_day() -> None:
    now_before_confirmation = datetime(2026, 1, 2, 23, tzinfo=UTC)

    def handler(request: httpx.Request) -> httpx.Response:
        payload: object = (
            _tiingo_prices(["2025-12-31", "2026-01-01", "2026-01-02"])
            if request.url.path.endswith("/prices")
            else _tiingo_meta()
        )
        return httpx.Response(200, json=payload, request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        snapshot = await TiingoPriceProvider(
            "secret",
            client=http_client,
            now_factory=lambda: now_before_confirmation,
        ).fetch_eod_snapshot(_instrument(MarketId.US))
    finally:
        await http_client.aclose()

    assert snapshot.observations == 2
    assert snapshot.as_of_date == date(2026, 1, 1)
    assert snapshot.current_close == 101.0
    assert any("오후 8시 이전" in gap for gap in snapshot.data_gaps)


@pytest.mark.asyncio
async def test_tiingo_provider_requires_token_before_network() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        provider = TiingoPriceProvider(None, client=http_client)
        with pytest.raises(MissingPriceApiKeyError, match="Tiingo.*인증 토큰"):
            await provider.fetch_eod_snapshot(_instrument(MarketId.US))
    finally:
        await http_client.aclose()

    assert calls == 0


@pytest.mark.asyncio
async def test_tiingo_provider_sanitizes_http_and_logical_errors() -> None:
    secret = "never-show-this-token"

    for response_kind in ("http", "logical"):
        def handler(request: httpx.Request, *, kind: str = response_kind) -> httpx.Response:
            if kind == "http":
                return httpx.Response(503, text=secret, request=request)
            return httpx.Response(200, json={"detail": secret}, request=request)

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            provider = TiingoPriceProvider(secret, client=http_client)
            with pytest.raises(PriceProviderResponseError) as caught:
                await provider.fetch_eod_snapshot(_instrument(MarketId.US))
        finally:
            await http_client.aclose()

        assert secret not in str(caught.value)
        if response_kind == "http":
            assert "HTTP 503" in str(caught.value)
        else:
            assert "논리 오류" in str(caught.value)


@pytest.mark.asyncio
async def test_tiingo_provider_rejects_metadata_symbol_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_tiingo_meta(ticker="MSFT"), request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        provider = TiingoPriceProvider("secret", client=http_client, now_factory=lambda: NOW)
        with pytest.raises(PriceProviderResponseError, match="종목이 요청과 다릅니다"):
            await provider.fetch_eod_snapshot(_instrument(MarketId.US))
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_default_gateway_does_not_fallback_to_yahoo_after_tiingo_failure() -> None:
    yahoo_calls = 0

    def tiingo_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    def yahoo_handler(request: httpx.Request) -> httpx.Response:
        nonlocal yahoo_calls
        yahoo_calls += 1
        return httpx.Response(200, json=_yahoo_payload(), request=request)

    tiingo_client = httpx.AsyncClient(transport=httpx.MockTransport(tiingo_handler))
    yahoo_http_client = httpx.AsyncClient(transport=httpx.MockTransport(yahoo_handler))
    try:
        gateway = build_default_price_gateway(
            tiingo_api_token="secret",
            tiingo_client=tiingo_client,
            yahoo_client=YahooFinanceClient(
                client=yahoo_http_client,
                now_factory=lambda: NOW,
            ),
            now_factory=lambda: NOW,
        )
        with pytest.raises(PriceProviderResponseError, match="HTTP 503"):
            await gateway.fetch_eod_snapshot(_instrument(MarketId.US))
    finally:
        await tiingo_client.aclose()
        await yahoo_http_client.aclose()

    assert yahoo_calls == 0


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
    assert len(snapshot.raw_bars) == 260
    assert snapshot.raw_bars[0].trade_date == date(2024, 1, 2)
    assert snapshot.raw_bars[-1].trade_date == date(2024, 9, 17)
    assert snapshot.raw_bars[0].open == 99.0
    assert "raw_bars" not in snapshot.model_dump(mode="json")


@pytest.mark.asyncio
async def test_korea_yahoo_provider_selects_kospi_from_exchange_hint() -> None:
    observed_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_paths.append(request.url.path)
        return httpx.Response(200, json=_yahoo_kr_payload(), request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        snapshot = await KoreaYahooPriceProvider(
            client=http_client,
            now_factory=lambda: NOW,
        ).fetch_eod_snapshot(_instrument(exchange="KOSPI"))
    finally:
        await http_client.aclose()

    assert observed_paths == ["/v8/finance/chart/005930.KS"]
    assert snapshot.ticker == "005930"
    assert snapshot.exchange == "KOSPI"
    assert snapshot.currency == "KRW"
    assert snapshot.timezone == "Asia/Seoul"
    assert snapshot.current_close == 70_300.0
    assert snapshot.raw_bars[0].open == pytest.approx(69_500 * (69_800 / 70_000))
    assert snapshot.raw_bars[0].high == pytest.approx(70_500 * (69_800 / 70_000))
    assert snapshot.raw_bars[0].low == pytest.approx(69_000 * (69_800 / 70_000))
    assert snapshot.raw_bars[0].close == 69_800.0
    assert any("조정주가 적용 방식" in gap for gap in snapshot.data_gaps)
    assert any("시장 구분" in gap for gap in snapshot.data_gaps)


@pytest.mark.asyncio
async def test_korea_yahoo_provider_checks_kospi_then_selects_kosdaq() -> None:
    observed_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_paths.append(request.url.path)
        if request.url.path.endswith(".KS"):
            return httpx.Response(404, text="상세 오류 본문", request=request)
        return httpx.Response(
            200,
            json=_yahoo_kr_payload(symbol="005930.KQ", exchange="KOE"),
            request=request,
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        snapshot = await KoreaYahooPriceProvider(
            client=http_client,
            now_factory=lambda: NOW,
        ).fetch_eod_snapshot(_instrument())
    finally:
        await http_client.aclose()

    assert observed_paths == [
        "/v8/finance/chart/005930.KS",
        "/v8/finance/chart/005930.KQ",
    ]
    assert snapshot.exchange == "KOSDAQ"


@pytest.mark.asyncio
async def test_korea_yahoo_provider_uses_only_kosdaq_from_exchange_hint() -> None:
    observed_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_paths.append(request.url.path)
        return httpx.Response(
            200,
            json=_yahoo_kr_payload(symbol="005930.KQ", exchange="KOE"),
            request=request,
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        snapshot = await KoreaYahooPriceProvider(
            client=http_client,
            now_factory=lambda: NOW,
        ).fetch_eod_snapshot(_instrument(exchange="KOSDAQ"))
    finally:
        await http_client.aclose()

    assert observed_paths == ["/v8/finance/chart/005930.KQ"]
    assert snapshot.exchange == "KOSDAQ"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"symbol": "000660.KS"},
        {"currency": "USD"},
        {"exchange": "KOE"},
        {"timezone": "America/New_York"},
        {"instrument_type": "CRYPTOCURRENCY"},
    ],
)
async def test_korea_yahoo_provider_rejects_metadata_mismatch(
    overrides: dict[str, str],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_yahoo_kr_payload(**overrides), request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        provider = KoreaYahooPriceProvider(client=http_client, now_factory=lambda: NOW)
        with pytest.raises(PriceProviderResponseError, match="모두 검증"):
            await provider.fetch_eod_snapshot(_instrument(exchange="KOSPI"))
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_default_korea_gateway_does_not_use_yahoo_without_public_key() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_yahoo_kr_payload(), request=request)

    yahoo_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        gateway = build_default_price_gateway(
            korea_service_key=None,
            korea_yahoo_client=yahoo_client,
            now_factory=lambda: NOW,
        )
        with pytest.raises(MissingPriceApiKeyError, match="공공데이터"):
            await gateway.fetch_eod_snapshot(_instrument())
    finally:
        await yahoo_client.aclose()

    assert calls == 0


@pytest.mark.asyncio
async def test_default_korea_gateway_does_not_fallback_after_public_response_error() -> None:
    yahoo_calls = 0

    def public_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="노출하면 안 되는 전체 오류 본문", request=request)

    def yahoo_handler(request: httpx.Request) -> httpx.Response:
        nonlocal yahoo_calls
        yahoo_calls += 1
        return httpx.Response(200, json=_yahoo_kr_payload(), request=request)

    public_client = httpx.AsyncClient(transport=httpx.MockTransport(public_handler))
    yahoo_client = httpx.AsyncClient(transport=httpx.MockTransport(yahoo_handler))
    try:
        gateway = build_default_price_gateway(
            korea_service_key="secret",
            korea_client=public_client,
            korea_yahoo_client=yahoo_client,
            now_factory=lambda: NOW,
        )
        with pytest.raises(PriceProviderResponseError, match="HTTP 503"):
            await gateway.fetch_eod_snapshot(_instrument())
    finally:
        await public_client.aclose()
        await yahoo_client.aclose()

    assert yahoo_calls == 0


@pytest.mark.asyncio
async def test_default_korea_gateway_does_not_fallback_for_insufficient_history() -> None:
    yahoo_calls = 0

    def public_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_kr_payload(_kr_items(1)), request=request)

    def yahoo_handler(request: httpx.Request) -> httpx.Response:
        nonlocal yahoo_calls
        yahoo_calls += 1
        return httpx.Response(200, json=_yahoo_kr_payload(), request=request)

    public_client = httpx.AsyncClient(transport=httpx.MockTransport(public_handler))
    yahoo_client = httpx.AsyncClient(transport=httpx.MockTransport(yahoo_handler))
    try:
        gateway = build_default_price_gateway(
            korea_service_key="secret",
            korea_client=public_client,
            korea_yahoo_client=yahoo_client,
            now_factory=lambda: NOW,
        )
        with pytest.raises(InsufficientPriceDataError):
            await gateway.fetch_eod_snapshot(_instrument())
    finally:
        await public_client.aclose()
        await yahoo_client.aclose()

    assert yahoo_calls == 0


@pytest.mark.asyncio
async def test_korea_yahoo_provider_does_not_expose_http_error_body() -> None:
    secret_body = "외부 공급자 비밀 오류 본문"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text=secret_body, request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        provider = KoreaYahooPriceProvider(client=http_client, now_factory=lambda: NOW)
        with pytest.raises(PriceProviderResponseError) as caught:
            await provider.fetch_eod_snapshot(_instrument(exchange="KOSPI"))
    finally:
        await http_client.aclose()

    assert secret_body not in str(caught.value)


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
    assert len(snapshot.raw_bars) == 2
    assert snapshot.raw_bars[0].trade_date < snapshot.raw_bars[1].trade_date
    assert snapshot.raw_bars[1].high is None
    assert snapshot.raw_bars[1].volume is None
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
    rendered_traceback = "".join(traceback.format_exception(caught.value))
    assert "highly-secret" not in rendered_traceback


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
