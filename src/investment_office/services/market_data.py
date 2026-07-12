# Yahoo Finance의 미국 종목 일봉을 검증하고 기술 지표 스냅샷으로 변환한다
from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from statistics import stdev
from typing import Final, cast

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from investment_office.services.chart_analysis import PriceBar

YAHOO_CHART_URL: Final = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
YAHOO_FALLBACK_CHART_URL: Final = "https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
_REQUEST_HEADERS: Final = {
    "Accept": "application/json",
    "User-Agent": "investment-office/0.1 (+https://finance.yahoo.com/)",
}
_TICKER_PATTERN: Final = re.compile(r"^[A-Z]{1,5}(?:-[A-Z]{1,2})?$")
_US_EXCHANGES: Final = frozenset(
    {
        "ASE",
        "BTS",
        "NCM",
        "NGM",
        "NMS",
        "NYQ",
        "PCX",
        "PNK",
        "OQB",
        "OQX",
    }
)
_SUPPORTED_INSTRUMENT_TYPES: Final = frozenset({"EQUITY", "ETF"})


class MarketDataError(RuntimeError):
    """시장 데이터 조회 또는 변환 실패의 기본 예외."""


class InvalidTickerError(ValueError):
    """지원하지 않는 미국 종목 티커 형식일 때 발생한다."""


class YahooFinanceError(MarketDataError):
    """Yahoo Finance 응답이 실패했거나 계약과 다를 때 발생한다."""


class UnsupportedMarketError(MarketDataError):
    """조회된 자산이 지원 대상인 미국 주식 또는 ETF가 아닐 때 발생한다."""


class InsufficientMarketDataError(MarketDataError):
    """현재가와 직전 종가조차 산출할 수 없을 때 발생한다."""


class EODSnapshot(BaseModel):
    """Yahoo Finance의 완료된 일봉으로 만든 재현 가능한 시장 스냅샷."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    exchange: str
    currency: str
    timezone: str
    as_of_date: date
    source_url: str
    fetched_at: AwareDatetime
    observations: int = Field(ge=2)
    current_close: float = Field(gt=0)
    previous_close: float = Field(gt=0)
    return_1d_pct: float
    return_5d_pct: float | None
    return_20d_pct: float | None
    return_60d_pct: float | None
    sma_20: float | None
    sma_50: float | None
    sma_200: float | None
    rsi_14: float | None
    atr_14: float | None
    volatility_20d_pct: float | None
    high_52_week: float | None
    low_52_week: float | None
    average_volume_20d: float | None
    data_gaps: list[str] = Field(default_factory=list)
    raw_bars: tuple[PriceBar, ...] = Field(default=(), exclude=True, repr=False)


@dataclass(frozen=True, slots=True)
class _EODBar:
    timestamp: int
    open: float | None
    close: float
    high: float | None
    low: float | None
    volume: float | None


def normalize_us_ticker(ticker: str) -> str:
    """Normalize a supported US ticker, including Yahoo's class-share separator."""

    if not isinstance(ticker, str):
        raise InvalidTickerError("티커는 문자열이어야 합니다.")
    normalized = ticker.strip().upper().replace(".", "-")
    if not _TICKER_PATTERN.fullmatch(normalized):
        raise InvalidTickerError("미국 종목 티커 형식이 아닙니다. 예: AAPL, BRK.B, BRK-B")
    return normalized


class YahooFinanceClient:
    """Fetch and validate recent completed Yahoo Finance daily bars."""

    def __init__(
        self,
        timeout_seconds: float = 20.0,
        client: httpx.AsyncClient | None = None,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        if isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds는 0보다 커야 합니다.")
        self.timeout_seconds = float(timeout_seconds)
        self.client = client
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    async def fetch_eod_snapshot(self, ticker: str) -> EODSnapshot:
        """Fetch two years of daily bars and compute a completed-EOD snapshot."""

        normalized = normalize_us_ticker(ticker)
        url = YAHOO_CHART_URL.format(ticker=normalized)
        params = {
            "range": "2y",
            "interval": "1d",
            "events": "div,splits",
            "includeAdjustedClose": "true",
        }
        response = await self._get(url, params)
        payload = self._decode_response(response)
        result = self._extract_result(payload)
        meta = _require_mapping(result.get("meta"), "chart.result[0].meta")
        exchange, currency, timezone = self._validate_asset(meta, normalized)
        now = self._aware_now()
        bars, parse_gaps = self._parse_bars(result)
        bars = self._drop_incomplete_regular_session(bars, meta, now)
        if len(bars) < 2:
            raise InsufficientMarketDataError(f"{normalized}의 완료된 유효 일봉이 2개 미만입니다.")

        return self._build_snapshot(
            ticker=normalized,
            exchange=exchange,
            currency=currency,
            timezone=timezone,
            source_url=str(response.request.url),
            fetched_at=now,
            bars=bars,
            parse_gaps=parse_gaps,
        )

    async def _get(self, url: str, params: Mapping[str, str]) -> httpx.Response:
        try:
            if self.client is not None:
                response = await self._request_with_fallback(self.client, url, params)
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await self._request_with_fallback(client, url, params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise YahooFinanceError(f"Yahoo Finance 일봉 요청이 실패했습니다. {exc}") from exc
        return response

    async def _request_with_fallback(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: Mapping[str, str],
    ) -> httpx.Response:
        response = await client.get(
            url,
            params=params,
            headers=_REQUEST_HEADERS,
            timeout=self.timeout_seconds,
        )
        if response.status_code != httpx.codes.TOO_MANY_REQUESTS:
            return response
        fallback_url = YAHOO_FALLBACK_CHART_URL.format(ticker=url.rsplit("/", maxsplit=1)[-1])
        return await client.get(
            fallback_url,
            params=params,
            headers=_REQUEST_HEADERS,
            timeout=self.timeout_seconds,
        )

    @staticmethod
    def _decode_response(response: httpx.Response) -> Mapping[str, object]:
        try:
            payload: object = response.json()
        except ValueError as exc:
            raise YahooFinanceError("Yahoo Finance가 유효한 JSON을 반환하지 않았습니다.") from exc
        return _require_mapping(payload, "응답 최상위 객체")

    @staticmethod
    def _extract_result(payload: Mapping[str, object]) -> Mapping[str, object]:
        chart = _require_mapping(payload.get("chart"), "chart")
        chart_error = chart.get("error")
        if chart_error is not None:
            detail = "알 수 없는 Yahoo Finance 오류"
            if isinstance(chart_error, Mapping):
                description = chart_error.get("description")
                code = chart_error.get("code")
                detail = str(description or code or detail)
            raise YahooFinanceError(f"Yahoo Finance가 종목 조회를 거부했습니다. {detail}")
        results = _require_sequence(chart.get("result"), "chart.result")
        if not results:
            raise YahooFinanceError("Yahoo Finance 응답에 종목 결과가 없습니다.")
        return _require_mapping(results[0], "chart.result[0]")

    @staticmethod
    def _validate_asset(meta: Mapping[str, object], requested_ticker: str) -> tuple[str, str, str]:
        symbol = _require_text(meta.get("symbol"), "meta.symbol").upper().replace(".", "-")
        if symbol != requested_ticker:
            raise YahooFinanceError(
                f"Yahoo Finance 응답 티커가 요청과 다릅니다. {symbol} != {requested_ticker}"
            )

        exchange = _require_text(meta.get("exchangeName"), "meta.exchangeName").upper()
        currency = _require_text(meta.get("currency"), "meta.currency").upper()
        timezone = _require_text(meta.get("exchangeTimezoneName"), "meta.exchangeTimezoneName")
        instrument_type_value = meta.get("instrumentType")
        instrument_type = (
            instrument_type_value.upper() if isinstance(instrument_type_value, str) else "EQUITY"
        )
        if currency != "USD" or exchange not in _US_EXCHANGES:
            raise UnsupportedMarketError(
                f"{requested_ticker}은 지원 대상 미국 시장 종목이 아닙니다. "
                f"exchange={exchange}, currency={currency}"
            )
        if instrument_type not in _SUPPORTED_INSTRUMENT_TYPES:
            raise UnsupportedMarketError(
                f"{requested_ticker}의 자산 유형 {instrument_type}은 지원하지 않습니다."
            )
        if timezone != "America/New_York":
            raise UnsupportedMarketError(
                f"{requested_ticker}의 거래소 시간대 {timezone}은 지원하지 않습니다."
            )
        return exchange, currency, timezone

    @staticmethod
    def _parse_bars(result: Mapping[str, object]) -> tuple[list[_EODBar], list[str]]:
        timestamps = _require_sequence(result.get("timestamp"), "chart.result[0].timestamp")
        indicators = _require_mapping(result.get("indicators"), "indicators")
        quote_sets = _require_sequence(indicators.get("quote"), "indicators.quote")
        if not quote_sets:
            raise InsufficientMarketDataError("Yahoo Finance 응답에 일봉 시세 배열이 없습니다.")
        quote = _require_mapping(quote_sets[0], "indicators.quote[0]")
        opens = _optional_sequence(quote.get("open"))
        closes = _require_sequence(quote.get("close"), "indicators.quote[0].close")
        highs = _optional_sequence(quote.get("high"))
        lows = _optional_sequence(quote.get("low"))
        volumes = _optional_sequence(quote.get("volume"))

        adjusted_closes: Sequence[object] = ()
        adjusted_sets = _optional_sequence(indicators.get("adjclose"))
        if adjusted_sets:
            adjusted_set = _require_mapping(adjusted_sets[0], "indicators.adjclose[0]")
            adjusted_closes = _optional_sequence(adjusted_set.get("adjclose"))

        bars: list[_EODBar] = []
        missing_close_count = 0
        missing_adjusted_count = 0
        missing_open_count = 0
        missing_high_count = 0
        missing_low_count = 0
        missing_volume_count = 0
        for index, timestamp_value in enumerate(timestamps):
            timestamp = _optional_int(timestamp_value)
            raw_close = _optional_float(_sequence_item(closes, index))
            if timestamp is None or raw_close is None or raw_close <= 0:
                missing_close_count += 1
                continue

            adjusted_close = _optional_float(_sequence_item(adjusted_closes, index))
            if adjusted_close is None or adjusted_close <= 0:
                adjusted_close = raw_close
                missing_adjusted_count += 1
            adjustment_factor = adjusted_close / raw_close
            raw_open = _optional_float(_sequence_item(opens, index))
            raw_high = _optional_float(_sequence_item(highs, index))
            raw_low = _optional_float(_sequence_item(lows, index))
            volume = _optional_float(_sequence_item(volumes, index))
            adjusted_open = raw_open * adjustment_factor if raw_open is not None else None
            high = raw_high * adjustment_factor if raw_high is not None else None
            low = raw_low * adjustment_factor if raw_low is not None else None
            missing_open_count += adjusted_open is None
            missing_high_count += high is None
            missing_low_count += low is None
            missing_volume_count += volume is None
            bars.append(
                _EODBar(
                    timestamp=timestamp,
                    open=adjusted_open,
                    close=adjusted_close,
                    high=high,
                    low=low,
                    volume=volume,
                )
            )

        bars.sort(key=lambda bar: bar.timestamp)
        deduplicated = {bar.timestamp: bar for bar in bars}
        bars = list(deduplicated.values())
        gaps: list[str] = []
        if missing_close_count:
            gaps.append(f"종가 또는 타임스탬프가 없는 일봉 {missing_close_count}개를 제외했습니다.")
        if missing_adjusted_count:
            gaps.append(
                f"조정 종가가 없는 일봉 {missing_adjusted_count}개는 원 종가를 사용했습니다."
            )
        if missing_open_count:
            gaps.append(f"시가가 없는 일봉이 {missing_open_count}개 있습니다.")
        if missing_high_count:
            gaps.append(f"고가가 없는 일봉이 {missing_high_count}개 있습니다.")
        if missing_low_count:
            gaps.append(f"저가가 없는 일봉이 {missing_low_count}개 있습니다.")
        if missing_volume_count:
            gaps.append(f"거래량이 없는 일봉이 {missing_volume_count}개 있습니다.")
        return bars, gaps

    @staticmethod
    def _drop_incomplete_regular_session(
        bars: list[_EODBar], meta: Mapping[str, object], now: datetime
    ) -> list[_EODBar]:
        if not bars:
            return bars
        trading_periods = _optional_mapping(meta.get("currentTradingPeriod"))
        regular = _optional_mapping(trading_periods.get("regular")) if trading_periods else None
        if regular is None:
            return bars
        start = _optional_int(regular.get("start"))
        end = _optional_int(regular.get("end"))
        if start is None or end is None:
            return bars
        now_timestamp = int(now.timestamp())
        if start <= bars[-1].timestamp <= end and start <= now_timestamp < end:
            return bars[:-1]
        return bars

    @staticmethod
    def _build_snapshot(
        *,
        ticker: str,
        exchange: str,
        currency: str,
        timezone: str,
        source_url: str,
        fetched_at: datetime,
        bars: list[_EODBar],
        parse_gaps: list[str],
    ) -> EODSnapshot:
        closes = [bar.close for bar in bars]
        data_gaps = list(parse_gaps)

        return_5d = _return_pct(closes, 5, data_gaps)
        return_20d = _return_pct(closes, 20, data_gaps)
        return_60d = _return_pct(closes, 60, data_gaps)
        sma_20 = _sma(closes, 20, data_gaps)
        sma_50 = _sma(closes, 50, data_gaps)
        sma_200 = _sma(closes, 200, data_gaps)
        rsi_14 = _rsi(closes, 14, data_gaps)
        atr_14 = _atr(bars, 14, data_gaps)
        volatility = _volatility(closes, 20, data_gaps)
        high_52_week, low_52_week = _year_range(bars, data_gaps)
        average_volume = _average_volume(bars, 20, data_gaps)

        # 미국 정규장 일봉 타임스탬프는 UTC에서도 거래일과 같은 날짜다.
        as_of_date = datetime.fromtimestamp(bars[-1].timestamp, UTC).date()
        raw_bars = tuple(
            PriceBar(
                trade_date=datetime.fromtimestamp(bar.timestamp, UTC).date(),
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
            )
            for bar in bars
        )
        return EODSnapshot(
            ticker=ticker,
            exchange=exchange,
            currency=currency,
            timezone=timezone,
            as_of_date=as_of_date,
            source_url=source_url,
            fetched_at=fetched_at,
            observations=len(bars),
            current_close=_round_price(closes[-1]),
            previous_close=_round_price(closes[-2]),
            return_1d_pct=_round_pct((closes[-1] / closes[-2] - 1) * 100),
            return_5d_pct=return_5d,
            return_20d_pct=return_20d,
            return_60d_pct=return_60d,
            sma_20=sma_20,
            sma_50=sma_50,
            sma_200=sma_200,
            rsi_14=rsi_14,
            atr_14=atr_14,
            volatility_20d_pct=volatility,
            high_52_week=high_52_week,
            low_52_week=low_52_week,
            average_volume_20d=average_volume,
            data_gaps=list(dict.fromkeys(data_gaps)),
            raw_bars=raw_bars,
        )

    def _aware_now(self) -> datetime:
        now = self._now_factory()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now_factory는 시간대가 있는 datetime을 반환해야 합니다.")
        return now.astimezone(UTC)


def _return_pct(closes: Sequence[float], horizon: int, gaps: list[str]) -> float | None:
    if len(closes) <= horizon:
        gaps.append(f"{horizon}거래일 수익률에는 종가 {horizon + 1}개가 필요합니다.")
        return None
    base = closes[-horizon - 1]
    if base <= 0:
        gaps.append(f"{horizon}거래일 수익률 기준 종가가 유효하지 않습니다.")
        return None
    return _round_pct((closes[-1] / base - 1) * 100)


def _sma(closes: Sequence[float], period: int, gaps: list[str]) -> float | None:
    if len(closes) < period:
        gaps.append(f"SMA{period}에는 종가 {period}개가 필요합니다.")
        return None
    return _round_price(sum(closes[-period:]) / period)


def _rsi(closes: Sequence[float], period: int, gaps: list[str]) -> float | None:
    if len(closes) <= period:
        gaps.append(f"RSI{period}에는 종가 {period + 1}개가 필요합니다.")
        return None
    deltas = [current - previous for previous, current in zip(closes, closes[1:], strict=False)]
    gains = [max(delta, 0.0) for delta in deltas]
    losses = [max(-delta, 0.0) for delta in deltas]
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:], strict=True):
        average_gain = (average_gain * (period - 1) + gain) / period
        average_loss = (average_loss * (period - 1) + loss) / period
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    relative_strength = average_gain / average_loss
    return _round_pct(100 - 100 / (1 + relative_strength))


def _atr(bars: Sequence[_EODBar], period: int, gaps: list[str]) -> float | None:
    trailing: list[_EODBar] = []
    for bar in reversed(bars):
        if bar.high is None or bar.low is None:
            break
        trailing.append(bar)
    trailing.reverse()
    if len(trailing) <= period:
        gaps.append(f"ATR{period}에는 고가·저가가 있는 연속 일봉 {period + 1}개가 필요합니다.")
        return None
    true_ranges = [
        max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        )
        for previous, current in zip(trailing, trailing[1:], strict=False)
        if current.high is not None and current.low is not None
    ]
    average_range = sum(true_ranges[:period]) / period
    for true_range in true_ranges[period:]:
        average_range = (average_range * (period - 1) + true_range) / period
    return _round_price(average_range)


def _volatility(closes: Sequence[float], period: int, gaps: list[str]) -> float | None:
    if len(closes) <= period:
        gaps.append(f"{period}거래일 변동성에는 종가 {period + 1}개가 필요합니다.")
        return None
    recent = closes[-period - 1 :]
    daily_returns = [
        current / previous - 1
        for previous, current in zip(recent, recent[1:], strict=False)
        if previous > 0
    ]
    if len(daily_returns) != period:
        gaps.append(f"{period}거래일 변동성에 유효하지 않은 종가가 있습니다.")
        return None
    return _round_pct(stdev(daily_returns) * math.sqrt(252) * 100)


def _year_range(bars: Sequence[_EODBar], gaps: list[str]) -> tuple[float | None, float | None]:
    period = 252
    if len(bars) < period:
        gaps.append("52주 고가·저가에는 일봉 252개가 필요합니다.")
        return None, None
    recent = bars[-period:]
    if any(bar.high is None or bar.low is None for bar in recent):
        gaps.append("최근 252개 일봉에 고가 또는 저가 누락값이 있습니다.")
        return None, None
    highs = [cast(float, bar.high) for bar in recent]
    lows = [cast(float, bar.low) for bar in recent]
    return _round_price(max(highs)), _round_price(min(lows))


def _average_volume(bars: Sequence[_EODBar], period: int, gaps: list[str]) -> float | None:
    if len(bars) < period:
        gaps.append(f"{period}거래일 평균 거래량에는 일봉 {period}개가 필요합니다.")
        return None
    volumes = [bar.volume for bar in bars[-period:]]
    if any(volume is None for volume in volumes):
        gaps.append(f"최근 {period}개 일봉에 거래량 누락값이 있습니다.")
        return None
    return _round_price(sum(cast(float, volume) for volume in volumes) / period)


def _round_price(value: float) -> float:
    return round(value, 6)


def _round_pct(value: float) -> float:
    return round(value, 4)


def _require_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise YahooFinanceError(f"Yahoo Finance {field} 값이 객체가 아닙니다.")
    return cast(Mapping[str, object], value)


def _optional_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


def _require_sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise YahooFinanceError(f"Yahoo Finance {field} 값이 배열이 아닙니다.")
    return cast(Sequence[object], value)


def _optional_sequence(value: object) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return cast(Sequence[object], value)


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise YahooFinanceError(f"Yahoo Finance {field} 값이 비어 있습니다.")
    return value.strip()


def _sequence_item(values: Sequence[object], index: int) -> object:
    return values[index] if index < len(values) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    resolved = float(value)
    return resolved if math.isfinite(resolved) else None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    resolved = float(value)
    if not math.isfinite(resolved):
        return None
    return int(resolved)
