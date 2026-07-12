# 미국·한국 전체 상장 발행사 유니버스를 공식 원천과 로컬 캐시에서 구성한다.
from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol, Self, cast

import httpx
from pydantic import (
    AnyHttpUrl,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from investment_office.services.research_contracts import MarketId

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
NASDAQ_OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
NASDAQ_SYMBOL_DIRECTORY_SOURCE_URL = "https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs"
SEC_COMPANY_TICKERS_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_COMPANY_TICKERS_EXCHANGE_SOURCE_URL = (
    "https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data"
)
KRX_KIND_KOSPI_URL = (
    "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
    "&marketType=stockMkt"
)
KRX_KIND_KOSDAQ_URL = (
    "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
    "&marketType=kosdaqMkt"
)
KRX_KIND_SOURCE_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=loadInitPage"

US_UNIVERSE_PROVIDER_ID = "official:nasdaq-trader:us-listings"
KR_UNIVERSE_PROVIDER_ID = "official:krx-kind:listed-companies"
DEFAULT_US_UNIVERSE_CACHE_PATH = Path("var") / "universe" / "us-listed.json"
DEFAULT_KR_UNIVERSE_CACHE_PATH = Path("var") / "universe" / "kr-listed.json"
DEFAULT_UNIVERSE_CACHE_PATH = DEFAULT_US_UNIVERSE_CACHE_PATH

_NASDAQ_EXCHANGE_CODES = {
    "A": "NYSE American",
    "N": "NYSE",
    "P": "NYSE Arca",
    "V": "IEX",
    "Z": "Cboe BZX",
}
_NON_COMMON_NAME_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bETF\b",
        r"\bETN\b",
        r"\bNEXTSHARES\b",
        r"EXCHANGE[- ]TRADED (?:FUND|NOTE)",
        r"\bPREFERRED\b",
        r"\bPFD\b",
        r"\bDEPOSITARY SHARES?\b.*\bPREFERRED\b",
        r"\bPREFERRED\b.*\bDEPOSITARY SHARES?\b",
        r"\bWARRANTS?\b",
        r"\bRIGHTS?\b",
        r"\bUNITS?\b",
        r"\bSENIOR NOTES?\b",
        r"\bSUBORDINATED NOTES?\b",
        r"\bNOTES? DUE\b",
        r"\bDEBENTURES?\b",
        r"\bFUND\b",
    )
)
_KR_NON_COMMON_NAME_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ETF",
        r"ETN",
        r"스팩",
        r"기업인수목적",
        r"우선주",
        r"(?:\d+)?우(?:B|C)?$",
    )
)
_US_TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")
_KR_TICKER_PATTERN = re.compile(r"^\d{6}$")


class UniverseCatalogError(RuntimeError):
    """유니버스 원천, 캐시 또는 공급자 계약이 실패했을 때의 기본 오류."""


class UniverseCatalogSourceError(UniverseCatalogError):
    """공식 원천 요청이나 응답이 유효하지 않을 때 발생한다."""


class UniverseCatalogCacheError(UniverseCatalogError):
    """로컬 유니버스 캐시를 읽거나 쓸 수 없을 때 발생한다."""


class UniverseCatalogUnavailableError(UniverseCatalogError):
    """유효한 캐시와 공식 원천을 모두 사용할 수 없을 때 발생한다."""


class UnsupportedUniverseMarketError(UniverseCatalogError):
    """등록된 유니버스 공급자가 없는 시장을 요청했을 때 발생한다."""


class UniverseTier(StrEnum):
    """재무 필터 뒤에 적용할 핵심·성장·공격형 후보군."""

    CORE = "core"
    GROWTH = "growth"
    AGGRESSIVE = "aggressive"


class UniverseCatalogMember(BaseModel):
    """거래소 상장 발행사 한 종목의 공급원 독립 식별 계약."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    market: MarketId
    ticker: str = Field(min_length=1, max_length=15)
    company_name: str = Field(min_length=1, max_length=300)
    exchange: str = Field(min_length=1, max_length=80)
    issuer_id: str = Field(min_length=1, max_length=80)
    cik: int | None = Field(default=None, ge=1)
    tiers: tuple[UniverseTier, ...] = Field(min_length=1)
    industry: str | None = Field(default=None, min_length=1, max_length=300)
    main_products: str | None = Field(default=None, min_length=1, max_length=1_000)
    listed_on: date | None = None

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator(
        "company_name",
        "exchange",
        "issuer_id",
        "industry",
        "main_products",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value: object) -> object:
        return " ".join(value.split()) if isinstance(value, str) else value

    @field_validator("tiers")
    @classmethod
    def normalize_tiers(
        cls,
        value: tuple[UniverseTier, ...],
    ) -> tuple[UniverseTier, ...]:
        return tuple(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        pattern = _US_TICKER_PATTERN if self.market is MarketId.US else _KR_TICKER_PATTERN
        if pattern.fullmatch(self.ticker) is None:
            raise ValueError("시장에 맞는 종목 식별자 형식이 아닙니다.")
        return self


class UniverseSnapshot(BaseModel):
    """한 시점의 원천별 유니버스와 제외·중복·출처 집계."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    market: MarketId
    provider_id: str = Field(min_length=1, max_length=120)
    source_url: AnyHttpUrl
    source_documentation_url: AnyHttpUrl
    source_urls: tuple[AnyHttpUrl, ...] = Field(min_length=1)
    retrieved_at: AwareDatetime
    members: tuple[UniverseCatalogMember, ...] = Field(min_length=1)
    raw_count: int = Field(ge=1)
    excluded_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    warnings: tuple[str, ...] = ()
    cache_hit: bool = False

    @model_validator(mode="after")
    def validate_counts_and_market(self) -> Self:
        if any(member.market is not self.market for member in self.members):
            raise ValueError("스냅샷 시장과 종목 시장이 일치하지 않습니다.")
        if self.raw_count != len(self.members) + self.excluded_count + self.duplicate_count:
            raise ValueError("유니버스 원본·포함·제외·중복 집계가 일치하지 않습니다.")
        return self


class UniverseCatalogProvider(Protocol):
    """시장별 유니버스 공급자를 교체하거나 합성하기 위한 비동기 계약."""

    @property
    def supported_markets(self) -> frozenset[MarketId]: ...

    async def load_snapshot(
        self,
        market: MarketId,
        *,
        force_refresh: bool = False,
    ) -> UniverseSnapshot: ...


class CompositeUniverseCatalogProvider:
    """미국 거래소와 향후 한국 KRX·OpenDART 공급자를 시장별로 라우팅한다."""

    def __init__(self, providers: Iterable[UniverseCatalogProvider]) -> None:
        by_market: dict[MarketId, UniverseCatalogProvider] = {}
        for provider in providers:
            if not provider.supported_markets:
                raise ValueError("유니버스 공급자는 지원 시장을 하나 이상 선언해야 합니다.")
            for market in provider.supported_markets:
                if market in by_market:
                    raise ValueError(f"{market.value} 시장 유니버스 공급자가 중복되었습니다.")
                by_market[market] = provider
        if not by_market:
            raise ValueError("유니버스 공급자는 하나 이상 필요합니다.")
        self._providers = by_market

    @property
    def supported_markets(self) -> frozenset[MarketId]:
        return frozenset(self._providers)

    async def load_snapshot(
        self,
        market: MarketId,
        *,
        force_refresh: bool = False,
    ) -> UniverseSnapshot:
        provider = self._providers.get(market)
        if provider is None:
            raise UnsupportedUniverseMarketError(
                f"{market.value} 시장 유니버스 공급자가 등록되지 않았습니다."
            )
        return await provider.load_snapshot(market, force_refresh=force_refresh)


class _CachedUniverseCatalogProvider:
    """공식 원천 전용 TTL 캐시와 명시적 실패 정책을 공유한다."""

    supported_markets: frozenset[MarketId]
    market: MarketId
    provider_id: str
    required_source_urls: frozenset[str]

    def __init__(
        self,
        *,
        user_agent: str,
        cache_path: Path | str,
        cache_ttl: timedelta,
        timeout_seconds: float,
        client: httpx.AsyncClient | None,
        now_factory: Callable[[], datetime] | None,
    ) -> None:
        normalized_user_agent = user_agent.strip()
        if not normalized_user_agent:
            raise ValueError("공식 원천 요청에는 식별 가능한 User-Agent가 필요합니다.")
        try:
            normalized_user_agent.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("공식 원천 User-Agent는 ASCII 문자로 작성해야 합니다.") from exc
        if cache_ttl <= timedelta(0):
            raise ValueError("유니버스 캐시 TTL은 0보다 커야 합니다.")
        if isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise ValueError("유니버스 요청 제한 시간은 0보다 커야 합니다.")
        self.user_agent = normalized_user_agent
        self.cache_path = Path(cache_path)
        self.cache_ttl = cache_ttl
        self.timeout_seconds = float(timeout_seconds)
        self.client = client
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    async def load_snapshot(
        self,
        market: MarketId,
        *,
        force_refresh: bool = False,
    ) -> UniverseSnapshot:
        if market is not self.market:
            raise UnsupportedUniverseMarketError(
                f"{self.market.value} 유니버스 공급자는 {market.value} 시장을 지원하지 않습니다."
            )
        now = _aware_utc(self._now_factory())
        cache_state = "강제 새로고침으로 확인하지 않음" if force_refresh else "없음"
        if not force_refresh:
            try:
                cached = self._read_cache()
            except UniverseCatalogCacheError as exc:
                cached = None
                cache_state = f"손상됨: {exc}"
            if cached is not None:
                age = now - cached.retrieved_at
                if timedelta(0) <= age < self.cache_ttl:
                    return cached.model_copy(update={"cache_hit": True})
                cache_state = "만료됨"
        try:
            snapshot = await self._fetch_snapshot(now)
        except UniverseCatalogSourceError as exc:
            raise UniverseCatalogUnavailableError(
                f"{self.market.value} 유니버스 수집이 실패했고 사용할 캐시가 없습니다. "
                f"캐시 상태는 {cache_state}입니다. 원천 오류는 {exc}"
            ) from exc
        self._write_cache(snapshot)
        return snapshot

    def _read_cache(self) -> UniverseSnapshot | None:
        if not self.cache_path.exists():
            return None
        try:
            content = self.cache_path.read_text(encoding="utf-8")
            snapshot = UniverseSnapshot.model_validate_json(content)
        except (OSError, ValueError) as exc:
            raise UniverseCatalogCacheError(
                f"유니버스 캐시 {self.cache_path}을 읽을 수 없습니다."
            ) from exc
        if snapshot.market is not self.market or snapshot.provider_id != self.provider_id:
            raise UniverseCatalogCacheError("유니버스 캐시의 시장 또는 공급자 정보가 다릅니다.")
        cached_source_urls = {str(source_url) for source_url in snapshot.source_urls}
        if not self.required_source_urls.issubset(cached_source_urls):
            raise UniverseCatalogCacheError("전체시장 필수 원천이 빠진 유니버스 캐시입니다.")
        return snapshot

    def _write_cache(self, snapshot: UniverseSnapshot) -> None:
        temporary_path = self.cache_path.with_suffix(f"{self.cache_path.suffix}.tmp")
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
            temporary_path.replace(self.cache_path)
        except OSError as exc:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
            raise UniverseCatalogCacheError(
                f"유니버스 캐시 {self.cache_path}을 저장할 수 없습니다."
            ) from exc

    async def _fetch_snapshot(self, retrieved_at: datetime) -> UniverseSnapshot:
        raise NotImplementedError

    def _headers(self) -> dict[str, str]:
        return {
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": self.user_agent,
        }


class UsExchangeUniverseCatalogProvider(_CachedUniverseCatalogProvider):
    """Nasdaq Trader 미국 상장 원장에 SEC CIK를 보강한다."""

    supported_markets = frozenset({MarketId.US})
    market = MarketId.US
    provider_id = US_UNIVERSE_PROVIDER_ID
    required_source_urls = frozenset({NASDAQ_LISTED_URL, NASDAQ_OTHER_LISTED_URL})

    def __init__(
        self,
        *,
        user_agent: str,
        cache_path: Path | str = DEFAULT_US_UNIVERSE_CACHE_PATH,
        cache_ttl: timedelta = timedelta(hours=24),
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(
            user_agent=user_agent,
            cache_path=cache_path,
            cache_ttl=cache_ttl,
            timeout_seconds=timeout_seconds,
            client=client,
            now_factory=now_factory,
        )

    async def _fetch_snapshot(self, retrieved_at: datetime) -> UniverseSnapshot:
        if self.client is None:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                return await self._fetch_with_client(client, retrieved_at)
        return await self._fetch_with_client(self.client, retrieved_at)

    async def _fetch_with_client(
        self,
        client: httpx.AsyncClient,
        retrieved_at: datetime,
    ) -> UniverseSnapshot:
        parsed_sources: list[_ParsedListings] = []
        source_urls: list[str] = []
        warnings: list[str] = []
        primary_failures: list[str] = []
        for url, parser, label in (
            (NASDAQ_LISTED_URL, _parse_nasdaq_listed, "Nasdaq 상장 파일"),
            (NASDAQ_OTHER_LISTED_URL, _parse_other_listed, "기타 거래소 상장 파일"),
        ):
            try:
                response = await _get_response(client, url, self._headers(), self.timeout_seconds)
                parsed_sources.append(parser(response.text))
                source_urls.append(url)
            except UniverseCatalogSourceError as exc:
                primary_failures.append(f"{label}: {exc}")
        if primary_failures:
            raise UniverseCatalogSourceError(
                "미국 전체시장에는 Nasdaq Trader의 두 미국 상장 원장이 모두 필요합니다. "
                f"실패 내용은 {'; '.join(primary_failures)}"
            )

        cik_by_ticker: dict[str, int] = {}
        try:
            sec_response = await _get_response(
                client,
                SEC_COMPANY_TICKERS_EXCHANGE_URL,
                {**self._headers(), "Accept": "application/json"},
                self.timeout_seconds,
            )
            cik_by_ticker = _parse_sec_cik_map(sec_response)
            source_urls.append(SEC_COMPANY_TICKERS_EXCHANGE_URL)
        except UniverseCatalogSourceError as exc:
            warnings.append(f"SEC CIK 보강을 사용할 수 없어 거래소 티커로 식별합니다. {exc}")

        raw_count = sum(source.raw_count for source in parsed_sources)
        excluded_count = sum(source.excluded_count for source in parsed_sources)
        duplicate_count = 0
        members: list[UniverseCatalogMember] = []
        seen: set[tuple[int | None, str]] = set()
        unmapped_count = 0
        for record in (record for source in parsed_sources for record in source.records):
            cik = cik_by_ticker.get(_ticker_match_key(record.ticker))
            key = (cik, _ticker_match_key(record.ticker))
            if key in seen:
                duplicate_count += 1
                continue
            seen.add(key)
            if cik is None:
                unmapped_count += 1
            members.append(
                UniverseCatalogMember(
                    market=MarketId.US,
                    ticker=record.ticker,
                    company_name=record.company_name,
                    exchange=record.exchange,
                    issuer_id=(f"sec:{cik:010d}" if cik is not None else f"us:{record.ticker}"),
                    cik=cik,
                    tiers=tuple(UniverseTier),
                )
            )
        if not members:
            raise UniverseCatalogSourceError("미국 상장 원장에서 보통주 후보를 찾지 못했습니다.")
        if cik_by_ticker and unmapped_count:
            warnings.append(f"SEC CIK를 연결하지 못한 종목이 {unmapped_count}개 있습니다.")
        members.sort(key=lambda member: (member.ticker, member.cik or 0))
        return UniverseSnapshot(
            market=MarketId.US,
            provider_id=self.provider_id,
            source_url=AnyHttpUrl(source_urls[0]),
            source_documentation_url=AnyHttpUrl(NASDAQ_SYMBOL_DIRECTORY_SOURCE_URL),
            source_urls=tuple(AnyHttpUrl(url) for url in source_urls),
            retrieved_at=retrieved_at,
            members=tuple(members),
            raw_count=raw_count,
            excluded_count=excluded_count,
            duplicate_count=duplicate_count,
            warnings=tuple(warnings),
        )


class KrxKindUniverseCatalogProvider(_CachedUniverseCatalogProvider):
    """KRX KIND의 KOSPI·KOSDAQ 상장회사 표를 한국 후보 원장으로 변환한다."""

    supported_markets = frozenset({MarketId.KR})
    market = MarketId.KR
    provider_id = KR_UNIVERSE_PROVIDER_ID
    required_source_urls = frozenset({KRX_KIND_KOSPI_URL, KRX_KIND_KOSDAQ_URL})

    def __init__(
        self,
        *,
        user_agent: str,
        cache_path: Path | str = DEFAULT_KR_UNIVERSE_CACHE_PATH,
        cache_ttl: timedelta = timedelta(hours=24),
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(
            user_agent=user_agent,
            cache_path=cache_path,
            cache_ttl=cache_ttl,
            timeout_seconds=timeout_seconds,
            client=client,
            now_factory=now_factory,
        )

    async def _fetch_snapshot(self, retrieved_at: datetime) -> UniverseSnapshot:
        if self.client is None:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                return await self._fetch_with_client(client, retrieved_at)
        return await self._fetch_with_client(self.client, retrieved_at)

    async def _fetch_with_client(
        self,
        client: httpx.AsyncClient,
        retrieved_at: datetime,
    ) -> UniverseSnapshot:
        parsed_sources: list[_ParsedListings] = []
        source_urls: list[str] = []
        warnings: list[str] = []
        primary_failures: list[str] = []
        for url, exchange in (
            (KRX_KIND_KOSPI_URL, "KOSPI"),
            (KRX_KIND_KOSDAQ_URL, "KOSDAQ"),
        ):
            try:
                response = await _get_response(client, url, self._headers(), self.timeout_seconds)
                parsed_sources.append(_parse_krx_kind(_decode_krx_html(response), exchange))
                source_urls.append(url)
            except UniverseCatalogSourceError as exc:
                primary_failures.append(f"{exchange}: {exc}")
        if primary_failures:
            raise UniverseCatalogSourceError(
                "한국 전체시장에는 KRX KIND의 KOSPI·KOSDAQ 원장이 모두 필요합니다. "
                f"실패 내용은 {'; '.join(primary_failures)}"
            )

        raw_count = sum(source.raw_count for source in parsed_sources)
        excluded_count = sum(source.excluded_count for source in parsed_sources)
        duplicate_count = 0
        members: list[UniverseCatalogMember] = []
        seen: set[str] = set()
        for record in (record for source in parsed_sources for record in source.records):
            if record.ticker in seen:
                duplicate_count += 1
                continue
            seen.add(record.ticker)
            members.append(
                UniverseCatalogMember(
                    market=MarketId.KR,
                    ticker=record.ticker,
                    company_name=record.company_name,
                    exchange=record.exchange,
                    issuer_id=f"krx:{record.ticker}",
                    tiers=tuple(UniverseTier),
                    industry=record.industry,
                    main_products=record.main_products,
                    listed_on=record.listed_on,
                )
            )
        if not members:
            raise UniverseCatalogSourceError("한국 상장 원장에서 보통주 후보를 찾지 못했습니다.")
        members.sort(key=lambda member: member.ticker)
        return UniverseSnapshot(
            market=MarketId.KR,
            provider_id=self.provider_id,
            source_url=AnyHttpUrl(source_urls[0]),
            source_documentation_url=AnyHttpUrl(KRX_KIND_SOURCE_URL),
            source_urls=tuple(AnyHttpUrl(url) for url in source_urls),
            retrieved_at=retrieved_at,
            members=tuple(members),
            raw_count=raw_count,
            excluded_count=excluded_count,
            duplicate_count=duplicate_count,
            warnings=tuple(warnings),
        )


@dataclass(frozen=True, slots=True)
class _ListingRecord:
    ticker: str
    company_name: str
    exchange: str
    industry: str | None = None
    main_products: str | None = None
    listed_on: date | None = None


@dataclass(frozen=True, slots=True)
class _ParsedListings:
    records: tuple[_ListingRecord, ...]
    raw_count: int
    excluded_count: int


def _parse_nasdaq_listed(content: str) -> _ParsedListings:
    return _parse_symbol_directory(
        content,
        ticker_field="Symbol",
        exchange="Nasdaq",
        next_shares_field="NextShares",
    )


def _parse_other_listed(content: str) -> _ParsedListings:
    return _parse_symbol_directory(
        content,
        ticker_field="ACT Symbol",
        exchange=None,
        next_shares_field=None,
    )


def _parse_symbol_directory(
    content: str,
    *,
    ticker_field: str,
    exchange: str | None,
    next_shares_field: str | None,
) -> _ParsedListings:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        raise UniverseCatalogSourceError("Nasdaq Trader 상장 파일이 비어 있습니다.")
    fields = tuple(part.strip() for part in lines[0].split("|"))
    required = {ticker_field, "Security Name", "ETF", "Test Issue"}
    if exchange is None:
        required.add("Exchange")
    if not required.issubset(fields):
        raise UniverseCatalogSourceError("Nasdaq Trader 상장 파일 필드가 올바르지 않습니다.")
    indexes = {field: fields.index(field) for field in required}
    if next_shares_field is not None and next_shares_field in fields:
        indexes[next_shares_field] = fields.index(next_shares_field)
    financial_index = fields.index("Financial Status") if "Financial Status" in fields else None

    records: list[_ListingRecord] = []
    excluded_count = 0
    raw_count = 0
    for line in lines[1:]:
        if line.casefold().startswith("file creation time"):
            continue
        raw_count += 1
        values = tuple(part.strip() for part in line.split("|"))
        if len(values) < len(fields):
            excluded_count += 1
            continue
        ticker = values[indexes[ticker_field]].upper()
        name = _compact(values[indexes["Security Name"]])
        exchange_name = exchange
        if exchange_name is None:
            exchange_name = _NASDAQ_EXCHANGE_CODES.get(values[indexes["Exchange"]].upper())
        is_next_shares = (
            next_shares_field is not None
            and next_shares_field in indexes
            and values[indexes[next_shares_field]].upper() == "Y"
        )
        abnormal_financial_status = financial_index is not None and values[
            financial_index
        ].upper() not in {"", "N"}
        if (
            exchange_name is None
            or values[indexes["ETF"]].upper() != "N"
            or values[indexes["Test Issue"]].upper() != "N"
            or is_next_shares
            or abnormal_financial_status
            or _US_TICKER_PATTERN.fullmatch(ticker) is None
            or not name
            or _is_obvious_non_common_security(name)
        ):
            excluded_count += 1
            continue
        records.append(_ListingRecord(ticker=ticker, company_name=name, exchange=exchange_name))
    if raw_count == 0:
        raise UniverseCatalogSourceError("Nasdaq Trader 상장 파일에 종목 행이 없습니다.")
    if not records:
        raise UniverseCatalogSourceError("Nasdaq Trader 상장 파일에 보통주 후보가 없습니다.")
    return _ParsedListings(tuple(records), raw_count, excluded_count)


def _parse_sec_cik_map(response: httpx.Response) -> dict[str, int]:
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise UniverseCatalogSourceError("SEC CIK 응답이 유효한 JSON이 아닙니다.") from exc
    if not isinstance(payload, Mapping):
        raise UniverseCatalogSourceError("SEC CIK 응답이 JSON 객체가 아닙니다.")
    fields = _require_sequence(payload.get("fields"), "SEC CIK 필드")
    rows = _require_sequence(payload.get("data"), "SEC CIK 데이터")
    field_names = tuple(field for field in fields if isinstance(field, str))
    if len(field_names) != len(fields) or not {"cik", "ticker"}.issubset(field_names):
        raise UniverseCatalogSourceError("SEC CIK 응답 필드가 올바르지 않습니다.")
    cik_index = field_names.index("cik")
    ticker_index = field_names.index("ticker")
    result: dict[str, int] = {}
    for raw_row in rows:
        if not _is_sequence(raw_row):
            continue
        row = cast(Sequence[object], raw_row)
        if len(row) < len(field_names):
            continue
        cik = row[cik_index]
        ticker = row[ticker_index]
        if (
            isinstance(cik, int)
            and not isinstance(cik, bool)
            and cik > 0
            and isinstance(ticker, str)
        ):
            normalized_ticker = ticker.strip().upper()
            if _US_TICKER_PATTERN.fullmatch(normalized_ticker) is not None:
                result.setdefault(_ticker_match_key(normalized_ticker), cik)
    if not result:
        raise UniverseCatalogSourceError("SEC CIK 응답에 사용할 종목 매핑이 없습니다.")
    return result


class _HtmlTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() == "tr":
            self._row = []
        elif tag.casefold() in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if normalized in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(_compact(" ".join(self._cell)))
            self._cell = None
        elif normalized == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell = None


def _parse_krx_kind(content: str, exchange: str) -> _ParsedListings:
    parser = _HtmlTableParser()
    try:
        parser.feed(content)
        parser.close()
    except ValueError as exc:
        raise UniverseCatalogSourceError(f"KRX {exchange} HTML 표를 읽을 수 없습니다.") from exc
    required_headers = {"회사명", "종목코드", "업종", "주요제품", "상장일"}
    header_index = next(
        (index for index, row in enumerate(parser.rows) if required_headers.issubset(row)),
        None,
    )
    if header_index is None:
        raise UniverseCatalogSourceError(f"KRX {exchange} 표 머리글이 올바르지 않습니다.")
    headers = parser.rows[header_index]
    indexes = {header: headers.index(header) for header in required_headers}
    records: list[_ListingRecord] = []
    excluded_count = 0
    raw_count = 0
    for row in parser.rows[header_index + 1 :]:
        if len(row) < len(headers):
            continue
        raw_count += 1
        ticker = row[indexes["종목코드"]].strip().zfill(6)
        name = _compact(row[indexes["회사명"]])
        industry = _optional_text(row[indexes["업종"]])
        main_products = _optional_text(row[indexes["주요제품"]])
        listed_on = _parse_listing_date(row[indexes["상장일"]])
        if (
            _KR_TICKER_PATTERN.fullmatch(ticker) is None
            or not name
            or _is_obvious_kr_non_common_security(name)
        ):
            excluded_count += 1
            continue
        records.append(
            _ListingRecord(
                ticker=ticker,
                company_name=name,
                exchange=exchange,
                industry=industry,
                main_products=main_products,
                listed_on=listed_on,
            )
        )
    if raw_count == 0:
        raise UniverseCatalogSourceError(f"KRX {exchange} 표에 종목 행이 없습니다.")
    if not records:
        raise UniverseCatalogSourceError(f"KRX {exchange} 표에 보통주 후보가 없습니다.")
    return _ParsedListings(tuple(records), raw_count, excluded_count)


async def _get_response(
    client: httpx.AsyncClient,
    url: str,
    headers: Mapping[str, str],
    timeout_seconds: float,
) -> httpx.Response:
    try:
        response = await client.get(
            url,
            headers=headers,
            timeout=timeout_seconds,
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise UniverseCatalogSourceError(f"공식 원천 {url} 요청이 실패했습니다.") from exc
    return response


def _decode_krx_html(response: httpx.Response) -> str:
    encodings = tuple(
        dict.fromkeys(
            encoding for encoding in (response.encoding, "euc-kr", "utf-8") if encoding is not None
        )
    )
    for encoding in encodings:
        try:
            return response.content.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    raise UniverseCatalogSourceError("KRX KIND 응답의 문자 인코딩을 판별할 수 없습니다.")


def _is_obvious_non_common_security(company_name: str) -> bool:
    return any(pattern.search(company_name) is not None for pattern in _NON_COMMON_NAME_PATTERNS)


def _ticker_match_key(ticker: str) -> str:
    return ticker.strip().upper().replace("-", ".")


def _is_obvious_kr_non_common_security(company_name: str) -> bool:
    return any(pattern.search(company_name) is not None for pattern in _KR_NON_COMMON_NAME_PATTERNS)


def _parse_listing_date(value: str) -> date | None:
    normalized = value.strip()
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(normalized, pattern).date()
        except ValueError:
            continue
    return None


def _optional_text(value: str) -> str | None:
    normalized = _compact(value)
    return normalized or None


def _compact(value: str) -> str:
    return " ".join(value.split())


def _require_sequence(value: object, label: str) -> Sequence[object]:
    if not _is_sequence(value):
        raise UniverseCatalogSourceError(f"{label} 배열이 없습니다.")
    return cast(Sequence[object], value)


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("유니버스 수집 시각에는 시간대가 필요합니다.")
    return value.astimezone(UTC)
