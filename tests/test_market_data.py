# Yahoo Finance 일봉 파싱과 기술 지표 산출을 실제 네트워크 없이 검증한다
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from investment_office.services.market_data import (
    InsufficientMarketDataError,
    InvalidTickerError,
    UnsupportedMarketError,
    YahooFinanceClient,
    YahooFinanceError,
    normalize_us_ticker,
)


def _chart_payload(
    closes: list[float | None],
    *,
    adjusted_closes: list[float | None] | None = None,
    start_timestamp: int = 1_704_110_400,
    exchange: str = "NMS",
    currency: str = "USD",
    symbol: str = "AAPL",
    regular_start: int = 1_800_000_000,
    regular_end: int = 1_800_023_400,
) -> dict[str, Any]:
    timestamps = [start_timestamp + index * 86_400 for index in range(len(closes))]
    highs = [close + 2 if close is not None else None for close in closes]
    lows = [close - 2 if close is not None else None for close in closes]
    volumes = [
        1_000_000 + index if close is not None else None for index, close in enumerate(closes)
    ]
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "currency": currency,
                        "symbol": symbol,
                        "exchangeName": exchange,
                        "instrumentType": "EQUITY",
                        "exchangeTimezoneName": "America/New_York",
                        "currentTradingPeriod": {
                            "regular": {"start": regular_start, "end": regular_end}
                        },
                    },
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": [
                                    close - 1 if close is not None else None for close in closes
                                ],
                                "high": highs,
                                "low": lows,
                                "close": closes,
                                "volume": volumes,
                            }
                        ],
                        "adjclose": [{"adjclose": adjusted_closes or closes}],
                    },
                }
            ],
            "error": None,
        }
    }


def _mock_client(payload: object, *, status_code: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload, request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_fetch_eod_snapshot_computes_expected_metrics() -> None:
    closes = [100.0 + index for index in range(260)]
    http_client = _mock_client(_chart_payload(closes))
    try:
        client = YahooFinanceClient(
            client=http_client,
            now_factory=lambda: datetime(2026, 1, 2, tzinfo=UTC),
        )
        snapshot = await client.fetch_eod_snapshot("aapl")
    finally:
        await http_client.aclose()

    assert snapshot.ticker == "AAPL"
    assert snapshot.observations == 260
    assert snapshot.current_close == 359.0
    assert snapshot.previous_close == 358.0
    assert snapshot.return_1d_pct == pytest.approx((359 / 358 - 1) * 100, abs=1e-4)
    assert snapshot.return_5d_pct == pytest.approx((359 / 354 - 1) * 100, abs=1e-4)
    assert snapshot.return_20d_pct == pytest.approx((359 / 339 - 1) * 100, abs=1e-4)
    assert snapshot.return_60d_pct == pytest.approx((359 / 299 - 1) * 100, abs=1e-4)
    assert snapshot.sma_20 == 349.5
    assert snapshot.sma_50 == 334.5
    assert snapshot.sma_200 == 259.5
    assert snapshot.rsi_14 == 100.0
    assert snapshot.atr_14 == 4.0
    assert snapshot.volatility_20d_pct is not None
    assert snapshot.high_52_week == 361.0
    assert snapshot.low_52_week == 106.0
    assert snapshot.average_volume_20d == 1_000_249.5
    assert snapshot.data_gaps == []
    assert len(snapshot.raw_bars) == 260
    assert snapshot.raw_bars[0].trade_date < snapshot.raw_bars[-1].trade_date
    assert snapshot.raw_bars[0].open == 99.0
    dumped = snapshot.model_dump(mode="json")
    assert dumped["as_of_date"] == "2024-09-16"
    assert "raw_bars" not in dumped
    assert "raw_bars" not in repr(snapshot)


@pytest.mark.asyncio
async def test_raw_bars_preserve_adjusted_open_and_missing_values_in_date_order() -> None:
    payload = _chart_payload(
        [200.0, 202.0, 204.0],
        adjusted_closes=[100.0, 101.0, 102.0],
    )
    quote = payload["chart"]["result"][0]["indicators"]["quote"][0]
    quote["open"][1] = None
    quote["high"][1] = None
    quote["volume"][1] = None
    http_client = _mock_client(payload)
    try:
        snapshot = await YahooFinanceClient(client=http_client).fetch_eod_snapshot("AAPL")
    finally:
        await http_client.aclose()

    assert [bar.trade_date for bar in snapshot.raw_bars] == sorted(
        bar.trade_date for bar in snapshot.raw_bars
    )
    assert snapshot.raw_bars[0].open == 99.5
    assert snapshot.raw_bars[0].high == 101.0
    assert snapshot.raw_bars[0].low == 99.0
    assert snapshot.raw_bars[0].close == 100.0
    assert snapshot.raw_bars[1].open is None
    assert snapshot.raw_bars[1].high is None
    assert snapshot.raw_bars[1].low == 100.0
    assert snapshot.raw_bars[1].close == 101.0
    assert snapshot.raw_bars[1].volume is None
    assert any("시가가 없는 일봉" in gap for gap in snapshot.data_gaps)
    assert any("고가가 없는 일봉" in gap for gap in snapshot.data_gaps)
    assert any("거래량이 없는 일봉" in gap for gap in snapshot.data_gaps)


@pytest.mark.asyncio
async def test_normalizes_class_share_ticker_before_request() -> None:
    observed_path = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_path
        observed_path = request.url.path
        payload = _chart_payload([100.0, 101.0], symbol="BRK-B")
        return httpx.Response(200, json=payload, request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        snapshot = await YahooFinanceClient(client=http_client).fetch_eod_snapshot(" brk.b ")
    finally:
        await http_client.aclose()

    assert observed_path.endswith("/BRK-B")
    assert snapshot.ticker == "BRK-B"
    assert normalize_us_ticker("brk-b") == "BRK-B"


@pytest.mark.asyncio
async def test_invalid_ticker_fails_before_network_request() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(InvalidTickerError):
            await YahooFinanceClient(client=http_client).fetch_eod_snapshot("BTC-USD=")
    finally:
        await http_client.aclose()

    assert calls == 0


@pytest.mark.asyncio
async def test_short_history_returns_explicit_data_gaps() -> None:
    http_client = _mock_client(_chart_payload([100.0, 101.0, 102.0]))
    try:
        snapshot = await YahooFinanceClient(client=http_client).fetch_eod_snapshot("AAPL")
    finally:
        await http_client.aclose()

    assert snapshot.return_1d_pct == pytest.approx(0.9901)
    assert snapshot.return_5d_pct is None
    assert snapshot.sma_20 is None
    assert snapshot.rsi_14 is None
    assert snapshot.atr_14 is None
    assert snapshot.volatility_20d_pct is None
    assert snapshot.high_52_week is None
    assert snapshot.average_volume_20d is None
    assert any("5거래일 수익률" in gap for gap in snapshot.data_gaps)
    assert any("ATR14" in gap for gap in snapshot.data_gaps)


@pytest.mark.asyncio
async def test_fewer_than_two_valid_completed_closes_is_an_error() -> None:
    http_client = _mock_client(_chart_payload([None, 101.0]))
    try:
        with pytest.raises(InsufficientMarketDataError, match="2개 미만"):
            await YahooFinanceClient(client=http_client).fetch_eod_snapshot("AAPL")
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_drops_current_regular_session_bar_before_close() -> None:
    regular_start = 1_800_000_000
    payload = _chart_payload(
        [100.0, 101.0, 150.0],
        start_timestamp=regular_start - 2 * 86_400,
        regular_start=regular_start,
        regular_end=regular_start + 23_400,
    )
    http_client = _mock_client(payload)
    try:
        snapshot = await YahooFinanceClient(
            client=http_client,
            now_factory=lambda: datetime.fromtimestamp(regular_start + 10_000, UTC),
        ).fetch_eod_snapshot("AAPL")
    finally:
        await http_client.aclose()

    assert snapshot.observations == 2
    assert snapshot.current_close == 101.0
    assert snapshot.previous_close == 100.0


@pytest.mark.asyncio
async def test_rejects_non_us_market_response() -> None:
    http_client = _mock_client(_chart_payload([100.0, 101.0], exchange="KSC", currency="KRW"))
    try:
        with pytest.raises(UnsupportedMarketError, match="미국 시장"):
            await YahooFinanceClient(client=http_client).fetch_eod_snapshot("AAPL")
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_surfaces_yahoo_chart_error() -> None:
    payload = {
        "chart": {
            "result": None,
            "error": {"code": "Not Found", "description": "No data found"},
        }
    }
    http_client = _mock_client(payload)
    try:
        with pytest.raises(YahooFinanceError, match="No data found"):
            await YahooFinanceClient(client=http_client).fetch_eod_snapshot("AAPL")
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_429_retries_once_on_query2_with_headers_and_records_source() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "query1.finance.yahoo.com":
            return httpx.Response(429, request=request)
        return httpx.Response(
            200,
            json=_chart_payload([100.0, 101.0]),
            request=request,
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        snapshot = await YahooFinanceClient(client=http_client).fetch_eod_snapshot("AAPL")
    finally:
        await http_client.aclose()

    assert [request.url.host for request in requests] == [
        "query1.finance.yahoo.com",
        "query2.finance.yahoo.com",
    ]
    assert all(request.headers["accept"] == "application/json" for request in requests)
    assert all(
        request.headers["user-agent"].startswith("investment-office/") for request in requests
    )
    assert snapshot.source_url.startswith("https://query2.finance.yahoo.com/")


@pytest.mark.asyncio
async def test_429_fallback_is_not_retried_again() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(YahooFinanceError, match="429"):
            await YahooFinanceClient(client=http_client).fetch_eod_snapshot("AAPL")
    finally:
        await http_client.aclose()

    assert calls == 2
