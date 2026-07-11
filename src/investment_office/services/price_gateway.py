# 미국과 한국 시장의 일봉 가격 공급자를 선택하고 공통 스냅샷으로 변환한다
from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Final, Protocol, cast
from urllib.parse import unquote

import httpx

from investment_office.services.instrument_identity import normalize_instrument
from investment_office.services.market_data import (
    EODSnapshot,
    InsufficientMarketDataError,
    YahooFinanceClient,
    YahooFinanceError,
    _EODBar,
)
from investment_office.services.research_contracts import InstrumentRef, MarketId

KOREA_STOCK_PRICE_URL: Final = (
    "https://apis.data.go.kr/1160100/service/"
    "GetStockSecuritiesInfoService/getStockPriceInfo"
)
YAHOO_KOREA_CHART_URL: Final = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
)
YAHOO_KOREA_FALLBACK_CHART_URL: Final = (
    "https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
)
TIINGO_META_URL: Final = "https://api.tiingo.com/tiingo/daily/{ticker}"
TIINGO_PRICES_URL: Final = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"
_REQUEST_HEADERS: Final = {
    "Accept": "application/json",
    "User-Agent": "investment-office/0.1",
}
_KOREA_MARKET_CATEGORIES: Final = frozenset({"KOSPI", "KOSDAQ", "KONEX"})
_TIINGO_US_EXCHANGES: Final = frozenset(
    {
        "AMEX",
        "BATS",
        "CBOE",
        "IEX",
        "NASDAQ",
        "NYSE",
        "NYSEAMERICAN",
        "NYSEARCA",
        "OTC",
        "OTCBB",
        "OTCMKTS",
    }
)
_TIINGO_CONFIRMED_AFTER: Final = time(20, 0)
_TIINGO_FALLBACK_GAP: Final = (
    "Tiingo 조정 일봉을 사용할 수 없어 Yahoo Finance 대체 자료를 사용했습니다."
)
_KOREA_YAHOO_FALLBACK_GAP: Final = (
    "공공데이터포털 가격을 사용할 수 없어 비공식 Yahoo Finance 한국 시세를 "
    "대체 자료로 사용했습니다."
)
_KOREA_YAHOO_QUALITY_GAPS: Final = (
    "Yahoo Finance의 한국 조정주가 적용 방식은 공식 거래소 자료와 다를 수 있어 "
    "기업행사 전후 지표를 재확인해야 합니다.",
    "KOSPI·KOSDAQ 시장 구분은 Yahoo Finance 접미사와 응답 메타데이터를 "
    "바탕으로 확인했으므로 공식 시장 자료로 재검증해야 합니다.",
)
_KOREA_YAHOO_CANDIDATES: Final = (
    (".KS", "KOSPI", "KSC"),
    (".KQ", "KOSDAQ", "KOE"),
)
_KOREA_YAHOO_INSTRUMENT_TYPES: Final = frozenset({"EQUITY", "ETF"})
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


class TiingoPriceProvider:
    """Tiingo 공식 조정 일봉을 검증해 미국 시장 스냅샷으로 변환한다."""

    market = MarketId.US

    def __init__(
        self,
        api_token: str | None,
        *,
        timeout_seconds: float = 20.0,
        client: httpx.AsyncClient | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        if isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds는 0보다 커야 합니다.")
        self._api_token = api_token.strip() if api_token and api_token.strip() else None
        self.timeout_seconds = float(timeout_seconds)
        self.client = client
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    async def fetch_eod_snapshot(self, instrument: InstrumentRef) -> EODSnapshot:
        _require_market(instrument, self.market)
        if self._api_token is None:
            raise MissingPriceApiKeyError("Tiingo 미국 주식 가격 조회용 인증 토큰이 없습니다.")

        fetched_at = self._aware_now()
        eastern_now = _to_us_eastern(fetched_at)
        tiingo_ticker = instrument.symbol.replace(".", "-")
        meta_response = await self._get(TIINGO_META_URL.format(ticker=tiingo_ticker))
        metadata = _decode_tiingo_mapping(meta_response, "메타데이터")
        exchange, available_start, available_end = _validate_tiingo_metadata(
            metadata,
            requested_ticker=tiingo_ticker,
        )

        current_date = eastern_now.date()
        prices_response = await self._get(
            TIINGO_PRICES_URL.format(ticker=tiingo_ticker),
            params={
                "startDate": _two_years_before(current_date).isoformat(),
                "endDate": current_date.isoformat(),
                "resampleFreq": "daily",
            },
        )
        price_rows = _decode_tiingo_sequence(prices_response, "조정 일봉")
        bars, data_gaps = _parse_tiingo_bars(price_rows, eastern_now=eastern_now)
        if len(bars) < 2:
            raise InsufficientPriceDataError(
                f"{instrument.symbol}의 확정된 유효 Tiingo 조정 일봉이 2개 미만입니다."
            )
        first_date = datetime.fromtimestamp(bars[0].timestamp, UTC).date()
        last_date = datetime.fromtimestamp(bars[-1].timestamp, UTC).date()
        if first_date < available_start or last_date > available_end:
            raise PriceProviderResponseError(
                "Tiingo 조정 일봉 날짜가 메타데이터의 제공 기간을 벗어났습니다."
            )

        return YahooFinanceClient._build_snapshot(
            ticker=instrument.symbol,
            exchange=exchange,
            currency="USD",
            timezone="America/New_York",
            source_url=str(prices_response.request.url),
            fetched_at=fetched_at,
            bars=bars,
            parse_gaps=data_gaps,
        )

    async def _get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        token = self._api_token
        if token is None:
            raise MissingPriceApiKeyError("Tiingo 미국 주식 가격 조회용 인증 토큰이 없습니다.")
        headers = {**_REQUEST_HEADERS, "Authorization": f"Token {token}"}
        try:
            if self.client is not None:
                response = await self.client.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.get(url, params=params, headers=headers)
            if response.is_error:
                status_code = response.status_code
                raise PriceProviderResponseError(
                    f"Tiingo 가격 요청이 HTTP {status_code}로 실패했습니다."
                )
        except PriceProviderResponseError:
            raise
        except httpx.RequestError as exc:
            if exc.request is not None:
                exc.request.headers.pop("Authorization", None)
            raise PriceProviderResponseError(
                "Tiingo 가격 요청 중 네트워크 오류가 발생했습니다."
            ) from None
        return response

    def _aware_now(self) -> datetime:
        now = self._now_factory()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now_factory는 시간대가 있는 datetime을 반환해야 합니다.")
        return now.astimezone(UTC)


class FallbackPriceProvider:
    """우선 공급자 장애 시 명시적 품질 공백과 함께 대체 공급자를 사용한다."""

    def __init__(
        self,
        primary: PriceProvider,
        fallback: PriceProvider,
        *,
        fallback_on: tuple[type[PriceGatewayError], ...] = (PriceGatewayError,),
        fallback_gap: str = _TIINGO_FALLBACK_GAP,
    ) -> None:
        if primary.market is not fallback.market:
            raise ValueError("우선 공급자와 대체 공급자의 시장이 서로 다릅니다.")
        if not fallback_on:
            raise ValueError("대체 공급자를 사용할 오류 유형이 하나 이상 필요합니다.")
        self.market = primary.market
        self.primary = primary
        self.fallback = fallback
        self.fallback_on = fallback_on
        self.fallback_gap = fallback_gap

    async def fetch_eod_snapshot(self, instrument: InstrumentRef) -> EODSnapshot:
        try:
            return await self.primary.fetch_eod_snapshot(instrument)
        except PriceGatewayError as exc:
            if not isinstance(exc, self.fallback_on):
                raise
            snapshot = await self.fallback.fetch_eod_snapshot(instrument)
            return snapshot.model_copy(
                update={
                    "data_gaps": list(
                        dict.fromkeys([*snapshot.data_gaps, self.fallback_gap])
                    )
                }
            )


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
        self.service_key = service_key.strip() if service_key and service_key.strip() else None
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


class KoreaYahooPriceProvider:
    """한국 거래소 메타데이터를 검증한 Yahoo 일봉을 장애 대체로 제공한다."""

    market = MarketId.KR

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        client: httpx.AsyncClient | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        if isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds는 0보다 커야 합니다.")
        self.timeout_seconds = float(timeout_seconds)
        self.client = client
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    async def fetch_eod_snapshot(self, instrument: InstrumentRef) -> EODSnapshot:
        _require_market(instrument, self.market)
        fetched_at = self._aware_now()

        for suffix, market_name, expected_exchange in _korea_yahoo_candidates(instrument):
            yahoo_symbol = f"{instrument.symbol}{suffix}"
            try:
                response = await self._get(yahoo_symbol)
                result = _decode_korea_yahoo_result(response)
                meta = _yahoo_required_mapping(result.get("meta"), "chart.result[0].meta")
                _validate_korea_yahoo_meta(
                    meta,
                    requested_symbol=yahoo_symbol,
                    expected_exchange=expected_exchange,
                )
                bars, parse_gaps = YahooFinanceClient._parse_bars(result)
                bars = YahooFinanceClient._drop_incomplete_regular_session(
                    bars,
                    meta,
                    fetched_at,
                )
                if len(bars) < 2:
                    raise InsufficientPriceDataError(
                        f"{instrument.symbol}의 완료된 유효 Yahoo 한국 일봉이 2개 미만입니다."
                    )
                snapshot = YahooFinanceClient._build_snapshot(
                    ticker=instrument.symbol,
                    exchange=market_name,
                    currency="KRW",
                    timezone="Asia/Seoul",
                    source_url=str(response.request.url),
                    fetched_at=fetched_at,
                    bars=bars,
                    parse_gaps=[*parse_gaps, *_KOREA_YAHOO_QUALITY_GAPS],
                )
                return snapshot
            except (
                InsufficientMarketDataError,
                InsufficientPriceDataError,
                PriceMarketMismatchError,
                PriceProviderResponseError,
                YahooFinanceError,
            ):
                continue

        raise PriceProviderResponseError(
            f"{instrument.symbol}의 KOSPI·KOSDAQ Yahoo 후보를 모두 검증했으나 "
            "일치하는 한국 일봉을 찾지 못했습니다."
        )

    async def _get(self, yahoo_symbol: str) -> httpx.Response:
        params = {
            "range": "2y",
            "interval": "1d",
            "events": "div,splits",
            "includeAdjustedClose": "true",
        }
        url = YAHOO_KOREA_CHART_URL.format(ticker=yahoo_symbol)
        try:
            response = await self._request(url, params)
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                response = await self._request(
                    YAHOO_KOREA_FALLBACK_CHART_URL.format(ticker=yahoo_symbol),
                    params,
                )
            if response.is_error:
                raise PriceProviderResponseError(
                    f"Yahoo Finance 한국 일봉 요청이 HTTP {response.status_code}로 실패했습니다."
                )
        except PriceProviderResponseError:
            raise
        except httpx.RequestError:
            raise PriceProviderResponseError(
                "Yahoo Finance 한국 일봉 요청 중 네트워크 오류가 발생했습니다."
            ) from None
        return response

    async def _request(
        self,
        url: str,
        params: Mapping[str, str],
    ) -> httpx.Response:
        if self.client is not None:
            return await self.client.get(
                url,
                params=params,
                headers=_REQUEST_HEADERS,
                timeout=self.timeout_seconds,
            )
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            return await client.get(url, params=params, headers=_REQUEST_HEADERS)

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
    tiingo_api_token: str | None = None,
    tiingo_client: httpx.AsyncClient | None = None,
    korea_service_key: str | None = None,
    korea_client: httpx.AsyncClient | None = None,
    korea_yahoo_client: httpx.AsyncClient | None = None,
    timeout_seconds: float = 20.0,
    now_factory: Callable[[], datetime] | None = None,
) -> MarketPriceGateway:
    """미국 Tiingo 우선·Yahoo 대체와 한국 공공데이터 게이트웨이를 만든다."""

    return MarketPriceGateway(
        (
            FallbackPriceProvider(
                TiingoPriceProvider(
                    tiingo_api_token,
                    timeout_seconds=timeout_seconds,
                    client=tiingo_client,
                    now_factory=now_factory,
                ),
                YahooPriceProvider(yahoo_client),
            ),
            FallbackPriceProvider(
                KoreaPublicDataPriceProvider(
                    korea_service_key,
                    timeout_seconds=timeout_seconds,
                    client=korea_client,
                    now_factory=now_factory,
                ),
                KoreaYahooPriceProvider(
                    timeout_seconds=timeout_seconds,
                    client=korea_yahoo_client,
                    now_factory=now_factory,
                ),
                fallback_on=(MissingPriceApiKeyError, PriceProviderResponseError),
                fallback_gap=_KOREA_YAHOO_FALLBACK_GAP,
            ),
        )
    )


def build_default_committee_price_gateway(
    *,
    yahoo_client: YahooFinanceClient | None = None,
    tiingo_api_token: str | None = None,
    tiingo_client: httpx.AsyncClient | None = None,
    korea_service_key: str | None = None,
    timeout_seconds: float = 20.0,
) -> CommitteePriceGateway:
    """앱 기본 설정을 기존 투자위원회가 바로 사용할 가격 클라이언트로 만든다."""

    return CommitteePriceGateway(
        build_default_price_gateway(
            yahoo_client=yahoo_client,
            tiingo_api_token=tiingo_api_token,
            tiingo_client=tiingo_client,
            korea_service_key=korea_service_key,
            timeout_seconds=timeout_seconds,
        )
    )


def _decode_tiingo_payload(response: httpx.Response, label: str) -> object:
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise PriceProviderResponseError(
            f"Tiingo {label} 응답이 유효한 JSON이 아닙니다."
        ) from exc
    if isinstance(payload, Mapping) and any(
        key in payload for key in ("detail", "error", "message")
    ):
        raise PriceProviderResponseError(f"Tiingo {label} 요청이 논리 오류로 거부되었습니다.")
    return payload


def _korea_yahoo_candidates(
    instrument: InstrumentRef,
) -> tuple[tuple[str, str, str], ...]:
    exchange = instrument.exchange.strip().upper()
    if exchange == "KRX":
        return _KOREA_YAHOO_CANDIDATES
    if exchange == "KOSPI":
        return (_KOREA_YAHOO_CANDIDATES[0],)
    if exchange == "KOSDAQ":
        return (_KOREA_YAHOO_CANDIDATES[1],)
    raise PriceMarketMismatchError(
        f"한국 Yahoo 대체 공급자는 KRX·KOSPI·KOSDAQ 요청만 지원합니다. exchange={exchange}"
    )


def _decode_korea_yahoo_result(response: httpx.Response) -> Mapping[str, object]:
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise PriceProviderResponseError(
            "Yahoo Finance 한국 일봉 응답이 유효한 JSON이 아닙니다."
        ) from exc
    root = _yahoo_required_mapping(payload, "응답 최상위 객체")
    chart = _yahoo_required_mapping(root.get("chart"), "chart")
    if chart.get("error") is not None:
        raise PriceProviderResponseError(
            "Yahoo Finance 한국 일봉 조회가 종목 오류로 거부되었습니다."
        )
    results = chart.get("result")
    if not isinstance(results, Sequence) or isinstance(results, (str, bytes, bytearray)):
        raise PriceProviderResponseError("Yahoo Finance 한국 일봉 결과가 배열이 아닙니다.")
    if not results:
        raise PriceProviderResponseError("Yahoo Finance 한국 일봉 결과가 비어 있습니다.")
    return _yahoo_required_mapping(results[0], "chart.result[0]")


def _yahoo_required_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PriceProviderResponseError(
            f"Yahoo Finance 한국 일봉의 {field} 값이 객체가 아닙니다."
        )
    return cast(Mapping[str, object], value)


def _yahoo_required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PriceProviderResponseError(
            f"Yahoo Finance 한국 일봉의 {field} 값이 비어 있습니다."
        )
    return value.strip()


def _validate_korea_yahoo_meta(
    meta: Mapping[str, object],
    *,
    requested_symbol: str,
    expected_exchange: str,
) -> None:
    symbol = _yahoo_required_text(meta.get("symbol"), "meta.symbol").upper()
    currency = _yahoo_required_text(meta.get("currency"), "meta.currency").upper()
    exchange = _yahoo_required_text(meta.get("exchangeName"), "meta.exchangeName").upper()
    exchange_timezone = _yahoo_required_text(
        meta.get("exchangeTimezoneName"),
        "meta.exchangeTimezoneName",
    )
    instrument_type = _yahoo_required_text(
        meta.get("instrumentType"),
        "meta.instrumentType",
    ).upper()
    if symbol != requested_symbol:
        raise PriceMarketMismatchError(
            f"Yahoo Finance 한국 일봉 종목이 요청과 다릅니다. {symbol} != {requested_symbol}"
        )
    if currency != "KRW":
        raise PriceMarketMismatchError(
            f"Yahoo Finance 한국 일봉 통화가 KRW가 아닙니다. currency={currency}"
        )
    if exchange != expected_exchange:
        raise PriceMarketMismatchError(
            "Yahoo Finance 한국 일봉 거래소가 요청 접미사와 다릅니다. "
            f"exchange={exchange}"
        )
    if exchange_timezone != "Asia/Seoul":
        raise PriceMarketMismatchError(
            "Yahoo Finance 한국 일봉 시간대가 Asia/Seoul이 아닙니다. "
            f"timezone={exchange_timezone}"
        )
    if instrument_type not in _KOREA_YAHOO_INSTRUMENT_TYPES:
        raise PriceMarketMismatchError(
            "Yahoo Finance 한국 일봉 자산 유형이 주식 또는 ETF가 아닙니다. "
            f"instrumentType={instrument_type}"
        )


def _decode_tiingo_mapping(
    response: httpx.Response,
    label: str,
) -> Mapping[str, object]:
    payload = _decode_tiingo_payload(response, label)
    if not isinstance(payload, Mapping):
        raise PriceProviderResponseError(f"Tiingo {label} 응답이 객체가 아닙니다.")
    return cast(Mapping[str, object], payload)


def _decode_tiingo_sequence(
    response: httpx.Response,
    label: str,
) -> Sequence[object]:
    payload = _decode_tiingo_payload(response, label)
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes, bytearray)):
        raise PriceProviderResponseError(f"Tiingo {label} 응답이 배열이 아닙니다.")
    return cast(Sequence[object], payload)


def _validate_tiingo_metadata(
    metadata: Mapping[str, object],
    *,
    requested_ticker: str,
) -> tuple[str, date, date]:
    ticker = _tiingo_required_text(metadata.get("ticker"), "ticker").upper()
    if ticker != requested_ticker:
        raise PriceProviderResponseError(
            f"Tiingo 메타데이터 종목이 요청과 다릅니다. {ticker} != {requested_ticker}"
        )
    exchange = _tiingo_required_text(metadata.get("exchangeCode"), "exchangeCode").upper()
    exchange_key = "".join(character for character in exchange if character.isalnum())
    if exchange_key not in _TIINGO_US_EXCHANGES:
        raise PriceMarketMismatchError(
            f"Tiingo 응답 거래소 {exchange}은 지원 대상 미국 시장이 아닙니다."
        )
    start_date = _tiingo_required_date(metadata.get("startDate"), "startDate")
    end_date = _tiingo_required_date(metadata.get("endDate"), "endDate")
    if end_date < start_date:
        raise PriceProviderResponseError("Tiingo 메타데이터의 제공 종료일이 시작일보다 빠릅니다.")
    return exchange, start_date, end_date


def _parse_tiingo_bars(
    rows: Sequence[object],
    *,
    eastern_now: datetime,
) -> tuple[list[_EODBar], list[str]]:
    bars_by_date: dict[date, _EODBar] = {}
    missing_adjusted_close = 0
    missing_open = 0
    missing_high = 0
    missing_low = 0
    missing_volume = 0
    excluded_unconfirmed = 0
    excluded_future = 0
    duplicate_dates = 0

    for value in rows:
        if not isinstance(value, Mapping):
            raise PriceProviderResponseError("Tiingo 조정 일봉 항목이 객체가 아닙니다.")
        row = cast(Mapping[str, object], value)
        trade_date = _tiingo_required_date(row.get("date"), "date")
        if trade_date > eastern_now.date():
            excluded_future += 1
            continue
        is_unconfirmed_today = (
            trade_date == eastern_now.date()
            and eastern_now.time() < _TIINGO_CONFIRMED_AFTER
        )
        if is_unconfirmed_today:
            excluded_unconfirmed += 1
            continue

        close = _optional_number(row.get("adjClose"), allow_zero=False)
        if close is None:
            missing_adjusted_close += 1
            continue
        adjusted_open = _optional_number(row.get("adjOpen"), allow_zero=False)
        high = _optional_number(row.get("adjHigh"), allow_zero=False)
        low = _optional_number(row.get("adjLow"), allow_zero=False)
        volume = _optional_number(row.get("adjVolume"), allow_zero=True)
        _validate_tiingo_ohlc(trade_date, adjusted_open, high, low, close)
        missing_open += adjusted_open is None
        missing_high += high is None
        missing_low += low is None
        missing_volume += volume is None
        timestamp = int(datetime.combine(trade_date, time.min, tzinfo=UTC).timestamp())
        if trade_date in bars_by_date:
            duplicate_dates += 1
        bars_by_date[trade_date] = _EODBar(
            timestamp=timestamp,
            close=close,
            high=high,
            low=low,
            volume=volume,
        )

    gaps: list[str] = []
    if missing_adjusted_close:
        gaps.append(
            f"Tiingo 조정 종가가 없는 일봉 {missing_adjusted_close}개를 제외했습니다."
        )
    if missing_open:
        gaps.append(f"Tiingo 조정 시가가 없는 일봉이 {missing_open}개 있습니다.")
    if missing_high:
        gaps.append(f"Tiingo 조정 고가가 없는 일봉이 {missing_high}개 있습니다.")
    if missing_low:
        gaps.append(f"Tiingo 조정 저가가 없는 일봉이 {missing_low}개 있습니다.")
    if missing_volume:
        gaps.append(f"Tiingo 조정 거래량이 없는 일봉이 {missing_volume}개 있습니다.")
    if excluded_unconfirmed:
        gaps.append(
            f"미국 동부 오후 8시 이전의 미확정 당일 일봉 {excluded_unconfirmed}개를 제외했습니다."
        )
    if excluded_future:
        gaps.append(f"미래 날짜 일봉 {excluded_future}개를 제외했습니다.")
    if duplicate_dates:
        gaps.append(f"중복 거래일 {duplicate_dates}개는 마지막 Tiingo 응답값을 사용했습니다.")
    return [bars_by_date[key] for key in sorted(bars_by_date)], gaps


def _validate_tiingo_ohlc(
    trade_date: date,
    open_price: float | None,
    high: float | None,
    low: float | None,
    close: float,
) -> None:
    observed = [price for price in (open_price, close) if price is not None]
    if high is not None and any(price > high for price in observed):
        raise PriceProviderResponseError(
            f"Tiingo {trade_date} 조정 일봉의 고가보다 시가 또는 종가가 큽니다."
        )
    if low is not None and any(price < low for price in observed):
        raise PriceProviderResponseError(
            f"Tiingo {trade_date} 조정 일봉의 저가보다 시가 또는 종가가 작습니다."
        )
    if high is not None and low is not None and high < low:
        raise PriceProviderResponseError(
            f"Tiingo {trade_date} 조정 일봉의 고가가 저가보다 작습니다."
        )


def _tiingo_required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PriceProviderResponseError(f"Tiingo 메타데이터의 {field} 값이 비어 있습니다.")
    return value.strip()


def _tiingo_required_date(value: object, field: str) -> date:
    if not isinstance(value, str) or len(value.strip()) < 10:
        raise PriceProviderResponseError(f"Tiingo {field} 날짜 형식이 올바르지 않습니다.")
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError as exc:
        raise PriceProviderResponseError(
            f"Tiingo {field} 날짜 형식이 올바르지 않습니다."
        ) from exc


def _two_years_before(value: date) -> date:
    try:
        return value.replace(year=value.year - 2)
    except ValueError:
        return value.replace(year=value.year - 2, day=28)


def _to_us_eastern(value: datetime) -> datetime:
    """Windows의 외부 시간대 자료 없이 현재 미국 동부 시각을 계산한다."""

    utc_value = value.astimezone(UTC)
    year = utc_value.year
    march_first = date(year, 3, 1)
    second_sunday = 8 + (6 - march_first.weekday()) % 7
    november_first = date(year, 11, 1)
    first_sunday = 1 + (6 - november_first.weekday()) % 7
    daylight_start = datetime(year, 3, second_sunday, 7, tzinfo=UTC)
    daylight_end = datetime(year, 11, first_sunday, 6, tzinfo=UTC)
    offset_hours = -4 if daylight_start <= utc_value < daylight_end else -5
    return utc_value.astimezone(timezone(timedelta(hours=offset_hours)))


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
