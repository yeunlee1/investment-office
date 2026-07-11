# 미국과 한국 시장의 일봉 가격 공급자를 선택하고 공통 스냅샷으로 변환한다
from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Final, Protocol, cast
from urllib.parse import unquote

import httpx

from investment_office.services.instrument_identity import normalize_instrument
from investment_office.services.market_data import EODSnapshot, YahooFinanceClient, _EODBar
from investment_office.services.research_contracts import InstrumentRef, MarketId

KOREA_STOCK_PRICE_URL: Final = (
    "https://apis.data.go.kr/1160100/service/"
    "GetStockSecuritiesInfoService/getStockPriceInfo"
)
_REQUEST_HEADERS: Final = {
    "Accept": "application/json",
    "User-Agent": "investment-office/0.1",
}
_KOREA_MARKET_CATEGORIES: Final = frozenset({"KOSPI", "KOSDAQ", "KONEX"})
_HISTORY_DAYS: Final = 730
_MAX_ROWS: Final = 500


class PriceGatewayError(RuntimeError):
    """시장별 가격 공급자 선택 또는 변환 실패의 기본 예외."""


class MissingPriceApiKeyError(PriceGatewayError):
    """필수 가격 API 인증키가 설정되지 않았을 때 발생한다."""


class PriceProviderResponseError(PriceGatewayError):
    """가격 공급자 응답이 실패했거나 계약과 다를 때 발생한다."""


class InsufficientPriceDataError(PriceGatewayError):
    """공통 일봉 스냅샷을 만들 유효 자료가 부족할 때 발생한다."""


class PriceMarketMismatchError(PriceGatewayError):
    """공급자나 응답 시장이 요청 종목 시장과 다를 때 발생한다."""


class UnsupportedPriceMarketError(PriceGatewayError):
    """요청 시장을 처리할 가격 공급자가 등록되지 않았을 때 발생한다."""


class PriceProvider(Protocol):
    """시장 하나의 일봉 가격을 공통 스냅샷으로 제공한다."""

    @property
    def market(self) -> MarketId: ...

    async def fetch_eod_snapshot(self, instrument: InstrumentRef) -> EODSnapshot: ...


@dataclass(frozen=True, slots=True)
class KoreaDailyBar:
    """공공데이터포털 주식시세 응답에서 검증한 한국 일봉."""

    trade_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: float | None


class YahooPriceProvider:
    """기존 Yahoo Finance 클라이언트를 미국 시장 공급자로 감싼다."""

    market = MarketId.US

    def __init__(self, client: YahooFinanceClient | None = None) -> None:
        self.client = client or YahooFinanceClient()

    async def fetch_eod_snapshot(self, instrument: InstrumentRef) -> EODSnapshot:
        _require_market(instrument, self.market)
        return await self.client.fetch_eod_snapshot(instrument.symbol)


class KoreaPublicDataPriceProvider:
    """금융위원회 공공데이터 API에서 한국 주식 일봉을 조회한다."""

    market = MarketId.KR

    def __init__(
        self,
        service_key: str | None,
        *,
        timeout_seconds: float = 20.0,
        client: httpx.AsyncClient | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        if isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds는 0보다 커야 합니다.")
        self.service_key = service_key.strip() if service_key else None
        self.timeout_seconds = float(timeout_seconds)
        self.client = client
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    async def fetch_eod_snapshot(self, instrument: InstrumentRef) -> EODSnapshot:
        _require_market(instrument, self.market)
        if self.service_key is None:
            raise MissingPriceApiKeyError("한국 주식 가격 조회용 공공데이터 인증키가 없습니다.")

        fetched_at = self._aware_now()
        response = await self._get(
            {
                "serviceKey": unquote(self.service_key),
                "resultType": "json",
                "numOfRows": str(_MAX_ROWS),
                "pageNo": "1",
                "beginBasDt": (fetched_at.date() - timedelta(days=_HISTORY_DAYS)).strftime(
                    "%Y%m%d"
                ),
                "likeSrtnCd": instrument.symbol,
            }
        )
        items = _extract_korea_items(_decode_json(response))
        return build_kr_eod_snapshot(
            instrument,
            items,
            source_url=KOREA_STOCK_PRICE_URL,
            fetched_at=fetched_at,
        )

    async def _get(self, params: Mapping[str, str]) -> httpx.Response:
        try:
            if self.client is not None:
                response = await self.client.get(
                    KOREA_STOCK_PRICE_URL,
                    params=params,
                    headers=_REQUEST_HEADERS,
                    timeout=self.timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.get(
                        KOREA_STOCK_PRICE_URL,
                        params=params,
                        headers=_REQUEST_HEADERS,
                    )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise PriceProviderResponseError(
                f"한국 주식 가격 요청이 HTTP {exc.response.status_code}로 실패했습니다."
            ) from exc
        except httpx.RequestError as exc:
            raise PriceProviderResponseError(
                "한국 주식 가격 요청 중 네트워크 오류가 발생했습니다."
            ) from exc
        return response

    def _aware_now(self) -> datetime:
        now = self._now_factory()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now_factory는 시간대가 있는 datetime을 반환해야 합니다.")
        return now.astimezone(UTC)


class MarketPriceGateway:
    """InstrumentRef 시장에 맞는 가격 공급자를 선택한다."""

    def __init__(self, providers: Iterable[PriceProvider]) -> None:
        by_market: dict[MarketId, PriceProvider] = {}
        for provider in providers:
            if provider.market in by_market:
                raise ValueError(f"{provider.market.value} 시장 가격 공급자가 중복되었습니다.")
            by_market[provider.market] = provider
        self._providers = by_market

    async def fetch_eod_snapshot(self, instrument: InstrumentRef) -> EODSnapshot:
        provider = self._providers.get(instrument.market)
        if provider is None:
            raise UnsupportedPriceMarketError(
                f"{instrument.market.value} 시장 가격 공급자가 등록되지 않았습니다."
            )
        return await provider.fetch_eod_snapshot(instrument)


class CommitteePriceGateway:
    """기존 위원회의 문자열 티커 계약을 시장별 가격 게이트웨이에 연결한다."""

    def __init__(self, gateway: MarketPriceGateway) -> None:
        self.gateway = gateway

    async def fetch_eod_snapshot(self, storage_ticker: str) -> EODSnapshot:
        if storage_ticker.startswith("KR-"):
            identity = normalize_instrument(MarketId.KR, storage_ticker.removeprefix("KR-"))
            exchange = "KRX"
        else:
            identity = normalize_instrument(MarketId.US, storage_ticker)
            exchange = "US"
        instrument = InstrumentRef(
            market=identity.market,
            symbol=identity.symbol,
            exchange=exchange,
            currency=identity.currency,
        )
        return await self.gateway.fetch_eod_snapshot(instrument)


def build_default_price_gateway(
    *,
    yahoo_client: YahooFinanceClient | None = None,
    korea_service_key: str | None = None,
    korea_client: httpx.AsyncClient | None = None,
    timeout_seconds: float = 20.0,
    now_factory: Callable[[], datetime] | None = None,
) -> MarketPriceGateway:
    """미국 Yahoo와 한국 공공데이터 공급자를 사용하는 기본 게이트웨이를 만든다."""

    return MarketPriceGateway(
        (
            YahooPriceProvider(yahoo_client),
            KoreaPublicDataPriceProvider(
                korea_service_key,
                timeout_seconds=timeout_seconds,
                client=korea_client,
                now_factory=now_factory,
            ),
        )
    )


def build_default_committee_price_gateway(
    *,
    yahoo_client: YahooFinanceClient | None = None,
    korea_service_key: str | None = None,
    timeout_seconds: float = 20.0,
) -> CommitteePriceGateway:
    """앱 기본 설정을 기존 투자위원회가 바로 사용할 가격 클라이언트로 만든다."""

    return CommitteePriceGateway(
        build_default_price_gateway(
            yahoo_client=yahoo_client,
            korea_service_key=korea_service_key,
            timeout_seconds=timeout_seconds,
        )
    )


def build_kr_eod_snapshot(
    instrument: InstrumentRef,
    items: Sequence[Mapping[str, object]],
    *,
    source_url: str,
    fetched_at: datetime,
) -> EODSnapshot:
    """한국 일별 OHLCV 자료를 기존 지표 의미의 불변 스냅샷으로 계산한다."""

    _require_market(instrument, MarketId.KR)
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise ValueError("fetched_at은 시간대가 있는 datetime이어야 합니다.")

    daily_bars, data_gaps = parse_kr_daily_bars(instrument, items)
    if len(daily_bars) < 2:
        raise InsufficientPriceDataError(
            f"{instrument.symbol}의 완료된 유효 한국 일봉이 2개 미만입니다."
        )

    bars = [
        _EODBar(
            timestamp=int(datetime.combine(bar.trade_date, time.min, tzinfo=UTC).timestamp()),
            close=bar.close,
            high=bar.high,
            low=bar.low,
            volume=bar.volume,
        )
        for bar in daily_bars
    ]
    return YahooFinanceClient._build_snapshot(
        ticker=instrument.symbol,
        exchange=instrument.exchange,
        currency=instrument.currency,
        timezone="Asia/Seoul",
        source_url=source_url,
        fetched_at=fetched_at.astimezone(UTC),
        bars=bars,
        parse_gaps=data_gaps,
    )


def parse_kr_daily_bars(
    instrument: InstrumentRef,
    items: Sequence[Mapping[str, object]],
) -> tuple[list[KoreaDailyBar], list[str]]:
    """공공데이터포털 항목을 날짜순 한국 OHLCV와 품질 공백으로 순수 변환한다."""

    _require_market(instrument, MarketId.KR)
    bars_by_date: dict[date, KoreaDailyBar] = {}
    skipped = 0
    missing_open = 0
    missing_high = 0
    missing_low = 0
    missing_volume = 0
    duplicate_dates = 0

    for item in items:
        symbol = _normalize_kr_symbol(item.get("srtnCd"))
        if symbol != instrument.symbol:
            raise PriceProviderResponseError(
                f"한국 가격 응답 종목이 요청과 다릅니다. {symbol} != {instrument.symbol}"
            )
        market_category = _required_text(item.get("mrktCtg"), "mrktCtg").upper()
        if market_category not in _KOREA_MARKET_CATEGORIES:
            raise PriceMarketMismatchError(
                f"{instrument.symbol} 응답의 시장 구분 {market_category}은 "
                "한국 주식시장이 아닙니다."
            )
        if instrument.exchange.upper() not in {"KRX", market_category}:
            raise PriceMarketMismatchError(
                f"응답 시장 {market_category}이 요청 거래소 {instrument.exchange}와 다릅니다."
            )

        trade_date = _optional_date(item.get("basDt"))
        close = _optional_number(item.get("clpr"), allow_zero=False)
        if trade_date is None or close is None:
            skipped += 1
            continue

        open_price = _optional_number(item.get("mkp"), allow_zero=False)
        high = _optional_number(item.get("hipr"), allow_zero=False)
        low = _optional_number(item.get("lopr"), allow_zero=False)
        volume = _optional_number(item.get("trqu"), allow_zero=True)
        _validate_kr_ohlc(trade_date, open_price, high, low, close)
        missing_open += open_price is None
        missing_high += high is None
        missing_low += low is None
        missing_volume += volume is None
        if trade_date in bars_by_date:
            duplicate_dates += 1
        bars_by_date[trade_date] = KoreaDailyBar(
            trade_date=trade_date,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )

    data_gaps = [
        "공공데이터포털 시세는 조정주가가 아니므로 기업행사 전후 지표가 왜곡될 수 있습니다."
    ]
    if skipped:
        data_gaps.append(f"기준일자 또는 종가가 유효하지 않은 일봉 {skipped}개를 제외했습니다.")
    if missing_open:
        data_gaps.append(f"시가가 없는 일봉이 {missing_open}개 있습니다.")
    if missing_high:
        data_gaps.append(f"고가가 없는 일봉이 {missing_high}개 있습니다.")
    if missing_low:
        data_gaps.append(f"저가가 없는 일봉이 {missing_low}개 있습니다.")
    if missing_volume:
        data_gaps.append(f"거래량이 없는 일봉이 {missing_volume}개 있습니다.")
    if duplicate_dates:
        data_gaps.append(f"중복 거래일 {duplicate_dates}개는 마지막 응답값을 사용했습니다.")
    return sorted(bars_by_date.values(), key=lambda bar: bar.trade_date), data_gaps


def _require_market(instrument: InstrumentRef, expected: MarketId) -> None:
    if instrument.market is not expected:
        raise PriceMarketMismatchError(
            f"{expected.value} 시장 공급자에 {instrument.market.value} 종목을 요청했습니다."
        )


def _decode_json(response: httpx.Response) -> Mapping[str, object]:
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise PriceProviderResponseError(
            "한국 주식 가격 API가 유효한 JSON을 반환하지 않았습니다."
        ) from exc
    return _require_mapping(payload, "응답 최상위 객체")


def _extract_korea_items(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    response = _require_mapping(payload.get("response"), "response")
    header = _require_mapping(response.get("header"), "response.header")
    result_code = str(header.get("resultCode", "")).strip()
    if result_code not in {"00", "0000"}:
        result_message = str(header.get("resultMsg", "알 수 없는 오류")).strip()
        raise PriceProviderResponseError(
            f"한국 주식 가격 API가 요청을 거부했습니다. {result_code} {result_message}"
        )

    body = _require_mapping(response.get("body"), "response.body")
    items_container = body.get("items")
    if items_container is None or items_container == "":
        return []
    items = _require_mapping(items_container, "response.body.items").get("item")
    if items is None or items == "":
        return []
    if isinstance(items, Mapping):
        return [cast(Mapping[str, object], items)]
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)):
        raise PriceProviderResponseError("한국 주식 가격 API의 item 값이 배열이 아닙니다.")
    return [_require_mapping(item, "response.body.items.item[]") for item in items]


def _require_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PriceProviderResponseError(f"한국 주식 가격 API의 {field} 값이 객체가 아닙니다.")
    return cast(Mapping[str, object], value)


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PriceProviderResponseError(f"한국 주식 가격 API의 {field} 값이 비어 있습니다.")
    return value.strip()


def _normalize_kr_symbol(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise PriceProviderResponseError("한국 주식 가격 API의 srtnCd 값이 올바르지 않습니다.")
    normalized = str(value).strip().zfill(6)
    if len(normalized) != 6 or not normalized.isdigit():
        raise PriceProviderResponseError("한국 주식 가격 API의 srtnCd 형식이 올바르지 않습니다.")
    return normalized


def _optional_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if len(normalized) != 8 or not normalized.isdigit():
        return None
    try:
        return datetime.strptime(normalized, "%Y%m%d").date()
    except ValueError:
        return None


def _optional_number(value: object, *, allow_zero: bool) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        normalized = value.strip().replace(",", "")
        if not normalized:
            return None
        try:
            resolved = float(normalized)
        except ValueError:
            return None
    elif isinstance(value, (int, float)):
        resolved = float(value)
    else:
        return None
    if not math.isfinite(resolved) or resolved < 0 or (resolved == 0 and not allow_zero):
        return None
    return resolved


def _validate_kr_ohlc(
    trade_date: date,
    open_price: float | None,
    high: float | None,
    low: float | None,
    close: float,
) -> None:
    observed_prices = [price for price in (open_price, close) if price is not None]
    if high is not None and any(price > high for price in observed_prices):
        raise PriceProviderResponseError(f"{trade_date} 일봉의 고가보다 시가 또는 종가가 큽니다.")
    if low is not None and any(price < low for price in observed_prices):
        raise PriceProviderResponseError(f"{trade_date} 일봉의 저가보다 시가 또는 종가가 작습니다.")
    if high is not None and low is not None and high < low:
        raise PriceProviderResponseError(f"{trade_date} 일봉의 고가가 저가보다 작습니다.")
