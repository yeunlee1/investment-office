# 미국 SEC 대량 공시와 한국 OpenDART 묶음 응답을 전체시장 재무 입력으로 변환한다.
from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import zipfile
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol, cast

import httpx
from pydantic import AnyHttpUrl, AwareDatetime, BaseModel, ConfigDict, Field

from investment_office.services.fundamental_screening import (
    AnnualFundamentals,
    IndustryModel,
    ScreeningFundamentals,
)
from investment_office.services.research_contracts import MarketId
from investment_office.services.universe_catalog import (
    UniverseCatalogMember,
    UniverseSnapshot,
)

SEC_COMPANY_FACTS_ARCHIVE_URL = (
    "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
)
SEC_COMPANY_FACTS_GUIDE_URL = (
    "https://www.sec.gov/search-filings/edgar-application-programming-interfaces"
)
SEC_SUBMISSIONS_ARCHIVE_URL = (
    "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
)
DART_BULK_MAIN_URL = "https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/main.do"
DART_BULK_LIST_URL = "https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/list.do"
DART_BULK_DOWNLOAD_URL = "https://opendart.fss.or.kr/cmm/downloadFnlttZip.do"
DEFAULT_SEC_ARCHIVE_PATH = Path("var") / "discovery" / "sec-companyfacts.zip"
DEFAULT_SEC_SUBMISSIONS_PATH = Path("var") / "discovery" / "sec-submissions.zip"
DEFAULT_SEC_CACHE_PATH = Path("var") / "discovery" / "sec-fundamentals.json"
DEFAULT_DART_CACHE_PATH = Path("var") / "discovery" / "dart-fundamentals.json"
_DART_REPORT_MAX_AGE_DAYS = 550
_DART_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

type BulkFundamentalsProgress = Callable[[int, int, int], Awaitable[None]]


class BulkFundamentalsError(RuntimeError):
    """대량 재무 원천이나 변환이 실패했을 때 발생한다."""


class BulkFundamentalsConfigurationError(BulkFundamentalsError):
    """필수 연락처 또는 인증키가 설정되지 않았을 때 발생한다."""


class BulkFundamentalsSourceError(BulkFundamentalsError):
    """공식 대량 재무 원천이 유효한 응답을 주지 않았을 때 발생한다."""


class BulkFundamentalsBatch(BaseModel):
    """시장 전체 재무 수집 결과와 누락 종목 집계다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    market: MarketId
    retrieved_at: AwareDatetime
    items: tuple[ScreeningFundamentals, ...]
    requested_count: int = Field(ge=1)
    missing_tickers: tuple[str, ...] = ()
    source_urls: tuple[AnyHttpUrl, ...] = Field(min_length=1)
    warnings: tuple[str, ...] = ()
    cache_hit: bool = False


class BulkFundamentalsProvider(Protocol):
    """한 유니버스의 재무를 묶음으로 반환하는 공급자 계약이다."""

    @property
    def supported_markets(self) -> frozenset[MarketId]: ...

    async def fetch_many(
        self,
        snapshot: UniverseSnapshot,
        *,
        progress: BulkFundamentalsProgress | None = None,
        force_refresh: bool = False,
    ) -> BulkFundamentalsBatch: ...


class CompositeBulkFundamentalsProvider:
    """시장별 대량 재무 공급자를 하나의 계약으로 라우팅한다."""

    def __init__(self, providers: Iterable[BulkFundamentalsProvider]) -> None:
        self._providers: dict[MarketId, BulkFundamentalsProvider] = {}
        for provider in providers:
            for market in provider.supported_markets:
                if market in self._providers:
                    raise ValueError(f"{market.value} 시장 재무 공급자가 중복되었습니다.")
                self._providers[market] = provider
        if not self._providers:
            raise ValueError("대량 재무 공급자는 하나 이상 필요합니다.")

    @property
    def supported_markets(self) -> frozenset[MarketId]:
        return frozenset(self._providers)

    async def fetch_many(
        self,
        snapshot: UniverseSnapshot,
        *,
        progress: BulkFundamentalsProgress | None = None,
        force_refresh: bool = False,
    ) -> BulkFundamentalsBatch:
        provider = self._providers.get(snapshot.market)
        if provider is None:
            raise BulkFundamentalsConfigurationError(
                f"{snapshot.market.value} 시장의 대량 재무 공급자가 구성되지 않았습니다."
            )
        return await provider.fetch_many(
            snapshot,
            progress=progress,
            force_refresh=force_refresh,
        )


class UnavailableBulkFundamentalsProvider:
    """필수 설정이 없을 때 가격만으로 추천하지 않도록 명시적으로 차단한다."""

    def __init__(self, market: MarketId, message: str) -> None:
        self.market = market
        self.message = message

    @property
    def supported_markets(self) -> frozenset[MarketId]:
        return frozenset({self.market})

    async def fetch_many(
        self,
        snapshot: UniverseSnapshot,
        *,
        progress: BulkFundamentalsProgress | None = None,
        force_refresh: bool = False,
    ) -> BulkFundamentalsBatch:
        del snapshot, progress, force_refresh
        raise BulkFundamentalsConfigurationError(self.message)


class SecCompanyFactsBulkProvider:
    """SEC 일괄 Company Facts 파일을 내려받아 CIK별 3개년 재무를 만든다."""

    supported_markets = frozenset({MarketId.US})

    def __init__(
        self,
        *,
        user_agent: str,
        archive_path: Path | str = DEFAULT_SEC_ARCHIVE_PATH,
        submissions_path: Path | str = DEFAULT_SEC_SUBMISSIONS_PATH,
        cache_path: Path | str = DEFAULT_SEC_CACHE_PATH,
        cache_ttl: timedelta = timedelta(hours=24),
        timeout_seconds: float = 180.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("SEC 요청에는 연락처를 포함한 User-Agent가 필요합니다.")
        self.user_agent = user_agent.strip()
        self.archive_path = Path(archive_path)
        self.submissions_path = Path(submissions_path)
        self.cache_path = Path(cache_path)
        self.cache_ttl = cache_ttl
        self.timeout_seconds = timeout_seconds
        self.client = client

    async def fetch_many(
        self,
        snapshot: UniverseSnapshot,
        *,
        progress: BulkFundamentalsProgress | None = None,
        force_refresh: bool = False,
    ) -> BulkFundamentalsBatch:
        if snapshot.market is not MarketId.US:
            raise BulkFundamentalsConfigurationError("SEC 재무 공급자는 미국 시장만 지원합니다.")
        cached = None if force_refresh else _read_fresh_batch_cache(
            self.cache_path,
            self.cache_ttl,
            MarketId.US,
        )
        if cached is not None:
            if progress is not None:
                await progress(cached.requested_count, len(cached.items), len(cached.items))
            return cached.model_copy(update={"cache_hit": True})

        await self._download_archive(
            SEC_COMPANY_FACTS_ARCHIVE_URL,
            self.archive_path,
            "SEC 대량 재무",
        )
        industry_warning: str | None = None
        try:
            await self._download_archive(
                SEC_SUBMISSIONS_ARCHIVE_URL,
                self.submissions_path,
                "SEC 대량 제출인",
            )
        except BulkFundamentalsSourceError as exc:
            industry_warning = f"SEC 업종 자료를 보강하지 못했습니다. {exc}"
        members = {member.cik: member for member in snapshot.members if member.cik is not None}
        if not members:
            raise BulkFundamentalsSourceError(
                "미국 전체 원장에 SEC CIK가 없어 재무제표와 연결할 수 없습니다."
            )
        industries = (
            await asyncio.to_thread(
                _parse_sec_industries,
                self.submissions_path,
                frozenset(members),
            )
            if industry_warning is None
            else {}
        )
        batch = await asyncio.to_thread(
            _parse_sec_archive,
            self.archive_path,
            snapshot,
            members,
            industries,
        )
        if industry_warning is not None:
            batch = batch.model_copy(
                update={"warnings": (*batch.warnings, industry_warning)}
            )
        if progress is not None:
            await progress(batch.requested_count, len(batch.items), 0)
        _write_batch_cache(self.cache_path, batch)
        return batch

    async def _download_archive(self, url: str, path: Path, label: str) -> None:
        headers = {
            "Accept": "application/zip, application/octet-stream",
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": self.user_agent,
        }
        temporary = path.with_suffix(".zip.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if self.client is None:
                async with (
                    httpx.AsyncClient(
                        timeout=self.timeout_seconds,
                        follow_redirects=True,
                    ) as client,
                    client.stream("GET", url, headers=headers) as response,
                ):
                    response.raise_for_status()
                    with temporary.open("wb") as output:
                        async for chunk in response.aiter_bytes():
                            output.write(chunk)
            else:
                response = await self.client.get(
                    url,
                    headers=headers,
                    timeout=self.timeout_seconds,
                    follow_redirects=True,
                )
                response.raise_for_status()
                temporary.write_bytes(response.content)
            if not zipfile.is_zipfile(temporary):
                raise BulkFundamentalsSourceError(
                    f"{label} 응답이 ZIP 파일이 아닙니다."
                )
            temporary.replace(path)
        except BulkFundamentalsSourceError:
            temporary.unlink(missing_ok=True)
            raise
        except httpx.HTTPError as exc:
            temporary.unlink(missing_ok=True)
            raise BulkFundamentalsSourceError(
                f"{label} 파일 요청이 실패했습니다."
            ) from exc
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise BulkFundamentalsSourceError(
                f"{label} 파일을 저장하지 못했습니다."
            ) from exc


class DartMultiCompanyBulkProvider:
    """OpenDART 연간 BS·PL·CF 일괄 ZIP으로 한국 전체시장 재무를 조회한다."""

    supported_markets = frozenset({MarketId.KR})

    def __init__(
        self,
        *,
        api_key: str | None = None,
        cache_path: Path | str = DEFAULT_DART_CACHE_PATH,
        cache_ttl: timedelta = timedelta(hours=24),
        timeout_seconds: float = 60.0,
        fiscal_year: int | None = None,
        client: httpx.AsyncClient | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        del api_key
        self.cache_path = Path(cache_path)
        self.cache_ttl = cache_ttl
        self.timeout_seconds = timeout_seconds
        self.fiscal_year = fiscal_year or datetime.now(UTC).year - 1
        self.client = client
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    async def fetch_many(
        self,
        snapshot: UniverseSnapshot,
        *,
        progress: BulkFundamentalsProgress | None = None,
        force_refresh: bool = False,
    ) -> BulkFundamentalsBatch:
        if snapshot.market is not MarketId.KR:
            raise BulkFundamentalsConfigurationError(
                "OpenDART 재무 공급자는 한국 시장만 지원합니다."
            )
        cached = None if force_refresh else _read_fresh_batch_cache(
            self.cache_path,
            self.cache_ttl,
            MarketId.KR,
        )
        if cached is not None:
            if progress is not None:
                await progress(
                    cached.requested_count,
                    cached.requested_count,
                    cached.requested_count,
                )
            return cached.model_copy(update={"cache_hit": True})

        if self.client is None:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=True,
            ) as client:
                items, warnings, selected_year, source_urls = await self._fetch_bulk_archives(
                    snapshot,
                    client,
                    progress,
                )
        else:
            items, warnings, selected_year, source_urls = await self._fetch_bulk_archives(
                snapshot,
                self.client,
                progress,
            )
        present = {item.ticker for item in items}
        batch = BulkFundamentalsBatch(
            market=MarketId.KR,
            retrieved_at=datetime.now(UTC),
            items=tuple(items),
            requested_count=len(snapshot.members),
            missing_tickers=tuple(
                member.ticker for member in snapshot.members if member.ticker not in present
            ),
            source_urls=source_urls,
            warnings=(
                f"OpenDART {selected_year}년 사업보고서 연결재무제표를 항목별로 우선했습니다.",
                "일괄 재무표에 없는 값은 0으로 간주하지 않고 자료 부족으로 보류합니다.",
                *warnings,
            ),
        )
        _write_batch_cache(self.cache_path, batch)
        return batch

    async def _fetch_bulk_archives(
        self,
        snapshot: UniverseSnapshot,
        client: httpx.AsyncClient,
        progress: BulkFundamentalsProgress | None,
    ) -> tuple[
        list[ScreeningFundamentals],
        tuple[str, ...],
        int,
        tuple[AnyHttpUrl, ...],
    ]:
        total_work = len(snapshot.members) + 5
        processed = 0
        await self._request(client, DART_BULK_MAIN_URL)
        processed += 1
        if progress is not None:
            await progress(total_work, processed, 0)
        listing = await self._request(client, DART_BULK_LIST_URL)
        processed += 1
        candidates = _parse_dart_bulk_listing(
            listing.text,
            self.fiscal_year,
            as_of_date=self._now().date(),
        )
        if progress is not None:
            await progress(total_work, processed, 0)

        failures: list[str] = []
        for candidate_index, (selected_year, file_names) in enumerate(candidates):
            if candidate_index > 0:
                total_work += 3
                if progress is not None:
                    await progress(total_work, processed, 0)
            rows: list[Mapping[str, object]] = []
            year_errors: list[str] = []
            selected_sources = [DART_BULK_MAIN_URL, DART_BULK_LIST_URL]
            for statement in ("BS", "PL", "CF"):
                file_name = file_names[statement]
                source_url = f"{DART_BULK_DOWNLOAD_URL}?fl_nm={file_name}"
                try:
                    response = await self._request(
                        client,
                        DART_BULK_DOWNLOAD_URL,
                        params={"fl_nm": file_name},
                    )
                    rows.extend(
                        _parse_dart_bulk_zip(
                            response.content,
                            file_name=file_name,
                            content_type=response.headers.get("content-type"),
                        )
                    )
                    selected_sources.append(source_url)
                except BulkFundamentalsSourceError as exc:
                    year_errors.append(f"{statement} {exc}")
                processed += 1
                if progress is not None:
                    await progress(total_work, processed, 0)
            if year_errors:
                failures.append(f"{selected_year}년: {'; '.join(year_errors)}")
                continue

            items = _parse_dart_rows(rows, snapshot.members, selected_year)
            processed += len(snapshot.members)
            if progress is not None:
                await progress(total_work, processed, 0)
            warnings = (
                ()
                if not failures
                else (
                    "최신 연간 묶음이 유효하지 않아 이전 신선 연도로 대체했습니다. "
                    + " | ".join(failures),
                )
            )
            return items, warnings, selected_year, _urls(*selected_sources)

        raise BulkFundamentalsSourceError(
            "OpenDART의 모든 신선 연간 BS·PL·CF 묶음이 실패했습니다. "
            + " | ".join(failures)
        )

    async def _request(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        headers = dict(_DART_BROWSER_HEADERS)
        if url != DART_BULK_MAIN_URL:
            headers["Referer"] = DART_BULK_MAIN_URL
        try:
            response = await client.get(
                url,
                params=params,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BulkFundamentalsSourceError("OpenDART 일괄 재무 요청이 실패했습니다.") from exc
        return response

    def _now(self) -> datetime:
        now = self._now_factory()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now_factory는 시간대가 있는 datetime을 반환해야 합니다.")
        return now.astimezone(UTC)

def _parse_sec_industries(
    archive_path: Path,
    requested_ciks: frozenset[int],
) -> dict[int, str]:
    industries: dict[int, str] = {}
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for file_name in archive.namelist():
                match = re.search(r"CIK(\d{10})\.json$", file_name, re.IGNORECASE)
                if match is None:
                    continue
                cik = int(match.group(1))
                if cik not in requested_ciks:
                    continue
                try:
                    payload: object = json.loads(archive.read(file_name))
                except (KeyError, ValueError):
                    continue
                if not isinstance(payload, Mapping):
                    continue
                description = str(payload.get("sicDescription", "")).strip()
                sic = str(payload.get("sic", "")).strip()
                if description:
                    industries[cik] = (
                        f"{description} (SIC {sic})" if sic else description
                    )
    except (OSError, zipfile.BadZipFile) as exc:
        raise BulkFundamentalsSourceError("SEC 대량 제출인 ZIP을 읽지 못했습니다.") from exc
    return industries


def _parse_sec_archive(
    archive_path: Path,
    snapshot: UniverseSnapshot,
    members: Mapping[int, UniverseCatalogMember],
    industries: Mapping[int, str] | None = None,
) -> BulkFundamentalsBatch:
    items: list[ScreeningFundamentals] = []
    processed_ciks: set[int] = set()
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for file_name in archive.namelist():
                match = re.search(r"CIK(\d{10})\.json$", file_name, re.IGNORECASE)
                if match is None:
                    continue
                cik = int(match.group(1))
                member = members.get(cik)
                if member is None:
                    continue
                processed_ciks.add(cik)
                try:
                    payload: object = json.loads(archive.read(file_name))
                    if isinstance(payload, Mapping):
                        item = _parse_sec_company_facts(
                            cast(Mapping[str, object], payload),
                            member,
                            industry=(industries or {}).get(cik),
                        )
                        if item is not None:
                            items.append(item)
                except (KeyError, ValueError):
                    continue
    except (OSError, zipfile.BadZipFile) as exc:
        raise BulkFundamentalsSourceError("SEC 대량 재무 ZIP을 읽지 못했습니다.") from exc
    present = {item.ticker for item in items}
    missing = tuple(member.ticker for member in snapshot.members if member.ticker not in present)
    warnings: list[str] = []
    no_cik_count = sum(member.cik is None for member in snapshot.members)
    if no_cik_count:
        warnings.append(
            f"SEC CIK가 연결되지 않은 종목 {no_cik_count}개는 "
            "재무 평가에서 보류했습니다."
        )
    if len(processed_ciks) < len(members):
        warnings.append("일괄 Company Facts에 없는 발행사는 자료 부족으로 보류했습니다.")
    return BulkFundamentalsBatch(
        market=MarketId.US,
        retrieved_at=datetime.now(UTC),
        items=tuple(sorted(items, key=lambda item: item.ticker)),
        requested_count=len(snapshot.members),
        missing_tickers=missing,
        source_urls=_urls(
            SEC_COMPANY_FACTS_ARCHIVE_URL,
            SEC_SUBMISSIONS_ARCHIVE_URL,
            SEC_COMPANY_FACTS_GUIDE_URL,
        ),
        warnings=tuple(warnings),
    )


_US_GAAP_TAGS: Mapping[str, tuple[str, ...]] = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForAdditionsToPropertyPlantAndEquipment",
    ),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "assets": ("Assets",),
    "liabilities": ("Liabilities",),
}

_IFRS_TAGS: Mapping[str, tuple[str, ...]] = {
    "revenue": (
        "Revenue",
        "RevenueFromContractsWithCustomers",
        "RevenueFromSaleOfGoods",
    ),
    "operating_income": ("ProfitLossFromOperatingActivities",),
    "net_income": ("ProfitLoss", "ProfitLossAttributableToOwnersOfParent"),
    "operating_cash_flow": ("CashFlowsFromUsedInOperatingActivities",),
    "capex": ("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",),
    "equity": ("Equity", "EquityAttributableToOwnersOfParent"),
    "assets": ("Assets",),
    "liabilities": ("Liabilities",),
}

_SEC_TAGS_BY_TAXONOMY: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "us-gaap": _US_GAAP_TAGS,
    "ifrs-full": _IFRS_TAGS,
}


def _parse_sec_company_facts(
    payload: Mapping[str, object],
    member: UniverseCatalogMember,
    industry: str | None = None,
) -> ScreeningFundamentals | None:
    facts = payload.get("facts")
    if not isinstance(facts, Mapping):
        return None
    taxonomy_name = next(
        (
            name
            for name in ("us-gaap", "ifrs-full")
            if isinstance(facts.get(name), Mapping)
        ),
        None,
    )
    if taxonomy_name is None:
        return None
    taxonomy = cast(Mapping[str, object], facts[taxonomy_name])
    tags_by_field = _SEC_TAGS_BY_TAXONOMY[taxonomy_name]
    currency = _sec_monetary_unit(taxonomy, tags_by_field["revenue"])
    if currency is None:
        return None
    series = {
        field: _sec_annual_values(taxonomy, tags, currency=currency)
        for field, tags in tags_by_field.items()
    }
    years = sorted(series["revenue"])[-3:]
    if not years:
        return None
    periods: list[AnnualFundamentals] = []
    latest_filed: date | None = None
    for year in years:
        filed_dates = [
            filed
            for values in series.values()
            if (entry := values.get(year)) is not None
            for filed in (entry[1],)
        ]
        if filed_dates:
            latest_filed = max([latest_filed, *filed_dates]) if latest_filed else max(filed_dates)
        capex_entry = series["capex"].get(year)
        cash_entry = series["operating_cash_flow"].get(year)
        free_cash_flow = None
        if cash_entry is not None and capex_entry is not None:
            free_cash_flow = cash_entry[0] - abs(capex_entry[0])
        periods.append(
            AnnualFundamentals(
                fiscal_year=year,
                revenue=_sec_value(series["revenue"], year),
                operating_income=_sec_value(series["operating_income"], year),
                net_income=_sec_value(series["net_income"], year),
                operating_cash_flow=_sec_value(series["operating_cash_flow"], year),
                free_cash_flow=free_cash_flow,
                equity=_sec_value(series["equity"], year),
                assets=_sec_value(series["assets"], year),
                liabilities=_sec_value(series["liabilities"], year),
            )
        )
    if latest_filed is None:
        return None
    return ScreeningFundamentals(
        market=MarketId.US,
        ticker=member.ticker,
        company_name=member.company_name,
        sector=industry or member.industry or "SEC 업종 미분류",
        industry_model=_industry_model(industry or member.industry, member.company_name),
        currency=currency,
        periods=tuple(periods),
        latest_report_date=latest_filed,
        source_urls=_urls(SEC_COMPANY_FACTS_GUIDE_URL),
    )


def _sec_annual_values(
    taxonomy: Mapping[str, object],
    tags: tuple[str, ...],
    *,
    currency: str,
) -> dict[int, tuple[float, date]]:
    chosen: dict[int, tuple[float, date]] = {}
    for tag in tags:
        concept = taxonomy.get(tag)
        if not isinstance(concept, Mapping):
            continue
        units = concept.get("units")
        if not isinstance(units, Mapping):
            continue
        entries = units.get(currency)
        if not isinstance(entries, Sequence):
            continue
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            if str(entry.get("form", "")) not in {"10-K", "20-F", "40-F"}:
                continue
            if str(entry.get("fp", "")) not in {"FY", ""}:
                continue
            end = _parse_iso_date(entry.get("end"))
            filed = _parse_iso_date(entry.get("filed"))
            value = _number(entry.get("val"))
            if end is None or filed is None or value is None:
                continue
            current = chosen.get(end.year)
            if current is None or filed > current[1]:
                chosen[end.year] = (value, filed)
        if chosen:
            break
    return chosen


def _sec_monetary_unit(
    taxonomy: Mapping[str, object],
    revenue_tags: tuple[str, ...],
) -> str | None:
    for tag in revenue_tags:
        concept = taxonomy.get(tag)
        if not isinstance(concept, Mapping):
            continue
        units = concept.get("units")
        if not isinstance(units, Mapping):
            continue
        monetary_units = [
            str(unit)
            for unit, entries in units.items()
            if re.fullmatch(r"[A-Z]{3}", str(unit))
            and isinstance(entries, Sequence)
            and entries
        ]
        if "USD" in monetary_units:
            return "USD"
        if monetary_units:
            return sorted(monetary_units)[0]
    return None


def _sec_value(values: Mapping[int, tuple[float, date]], year: int) -> float | None:
    entry = values.get(year)
    return entry[0] if entry is not None else None


def _parse_dart_bulk_listing(
    html: str,
    preferred_year: int,
    *,
    as_of_date: date,
) -> tuple[tuple[int, dict[str, str]], ...]:
    matches = re.findall(
        r"download_ext002\(\s*'(\d{4})'\s*,\s*'FY'\s*,\s*'(BS|PL|CF)'\s*,\s*'([^']+)'",
        html,
    )
    by_year: dict[int, dict[str, str]] = defaultdict(dict)
    for year_text, statement, file_name in matches:
        by_year[int(year_text)][statement] = file_name
    complete_years = sorted(
        (
        year
        for year, files in by_year.items()
        if year <= preferred_year
        and all(statement in files for statement in ("BS", "PL", "CF"))
        and 0 <= (as_of_date - date(year + 1, 3, 31)).days <= _DART_REPORT_MAX_AGE_DAYS
        ),
        reverse=True,
    )
    if not complete_years:
        raise BulkFundamentalsSourceError(
            f"OpenDART 목록에서 {preferred_year}년 이하의 "
            f"{_DART_REPORT_MAX_AGE_DAYS}일 이내 완전한 연간 BS·PL·CF 묶음을 찾지 못했습니다."
        )
    return tuple((year, by_year[year]) for year in complete_years)


def _parse_dart_bulk_zip(
    content: bytes,
    *,
    file_name: str = "이름 미상 ZIP",
    content_type: str | None = None,
) -> list[Mapping[str, object]]:
    if not zipfile.is_zipfile(io.BytesIO(content)):
        safe_content_type = re.sub(r"[^\w+./;= -]", "?", content_type or "미보고")[:120]
        safe_file_name = re.sub(r"[^A-Za-z0-9_.-]", "?", file_name)[:160]
        raise BulkFundamentalsSourceError(
            f"{safe_file_name} 응답이 ZIP이 아닙니다. "
            f"Content-Type {safe_content_type}, {len(content)}바이트."
        )
    rows: list[Mapping[str, object]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for file_name in archive.namelist():
                if not file_name.lower().endswith(".txt"):
                    continue
                decoded = archive.read(file_name).decode("cp949")
                rows.extend(_parse_dart_bulk_tsv(decoded))
    except (KeyError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise BulkFundamentalsSourceError(
            "OpenDART 일괄 재무 ZIP의 CP949 TSV를 읽지 못했습니다."
        ) from exc
    if not rows:
        raise BulkFundamentalsSourceError("OpenDART 일괄 재무 ZIP에 유효한 TSV 행이 없습니다.")
    return rows


def _parse_dart_bulk_tsv(text: str) -> list[Mapping[str, object]]:
    table = csv.reader(io.StringIO(text), delimiter="\t")
    header = next(table, None)
    expected = ("재무제표종류", "종목코드", "회사명", "시장구분")
    if header is None or tuple(header[:4]) != expected:
        raise BulkFundamentalsSourceError("OpenDART 일괄 재무 TSV 열 계약이 변경되었습니다.")
    column_indexes = {
        name: header.index(name)
        for name in ("당기", "전기", "전전기")
        if name in header
    }
    if set(column_indexes) != {"당기", "전기", "전전기"}:
        raise BulkFundamentalsSourceError("OpenDART 일괄 재무 TSV 금액 열이 누락되었습니다.")
    last_required_index = max(11, *column_indexes.values())
    rows: list[Mapping[str, object]] = []
    for values in table:
        if len(values) <= last_required_index:
            continue
        ticker = values[1].strip().removeprefix("[").removesuffix("]")
        if re.fullmatch(r"\d{6}", ticker) is None:
            continue
        statement_name = values[0].strip()
        rows.append(
            {
                "stock_code": ticker,
                "fs_div": "CFS" if "연결" in statement_name else "OFS",
                "account_id": values[10].strip(),
                "account_nm": values[11].strip(),
                "thstrm_amount": values[column_indexes["당기"]],
                "frmtrm_amount": values[column_indexes["전기"]],
                "bfefrmtrm_amount": values[column_indexes["전전기"]],
            }
        )
    return rows


_DART_ACCOUNT_FIELDS: Mapping[str, tuple[str, ...]] = {
    "revenue": ("매출액", "수익(매출액)", "영업수익"),
    "operating_income": ("영업이익", "영업이익(손실)"),
    "net_income": ("당기순이익", "당기순이익(손실)"),
    "operating_cash_flow": ("영업활동으로 인한 현금흐름", "영업활동현금흐름"),
    "capex": ("유형자산의 취득", "유형자산 취득"),
    "equity": ("자본총계",),
    "assets": ("자산총계",),
    "liabilities": ("부채총계",),
}


def _parse_dart_rows(
    rows: Sequence[Mapping[str, object]],
    members: Sequence[UniverseCatalogMember],
    fiscal_year: int,
) -> list[ScreeningFundamentals]:
    by_ticker: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        ticker = str(row.get("stock_code", "")).strip()
        if re.fullmatch(r"\d{6}", ticker):
            by_ticker[ticker].append(row)
    member_by_ticker = {member.ticker: member for member in members}
    items: list[ScreeningFundamentals] = []
    for ticker, company_rows in by_ticker.items():
        member = member_by_ticker.get(ticker)
        if member is None:
            continue
        values: dict[str, tuple[float | None, float | None, float | None]] = {}
        for field, aliases in _DART_ACCOUNT_FIELDS.items():
            account_row = _find_dart_account(company_rows, aliases)
            values[field] = (
                _dart_amount(account_row.get("bfefrmtrm_amount"))
                if account_row
                else None,
                _dart_amount(account_row.get("frmtrm_amount")) if account_row else None,
                _dart_amount(account_row.get("thstrm_amount")) if account_row else None,
            )
        periods: list[AnnualFundamentals] = []
        for index in range(3):
            operating_cash_flow = values["operating_cash_flow"][index]
            capex = values["capex"][index]
            free_cash_flow = (
                operating_cash_flow - abs(capex)
                if operating_cash_flow is not None and capex is not None
                else None
            )
            periods.append(
                AnnualFundamentals(
                    fiscal_year=fiscal_year - 2 + index,
                    revenue=values["revenue"][index],
                    operating_income=values["operating_income"][index],
                    net_income=values["net_income"][index],
                    operating_cash_flow=operating_cash_flow,
                    free_cash_flow=free_cash_flow,
                    equity=values["equity"][index],
                    assets=values["assets"][index],
                    liabilities=values["liabilities"][index],
                )
            )
        items.append(
            ScreeningFundamentals(
                market=MarketId.KR,
                ticker=ticker,
                company_name=member.company_name,
                sector=member.industry or "한국거래소 업종 미분류",
                industry_model=_industry_model(member.industry, member.company_name),
                currency="KRW",
                periods=tuple(periods),
                latest_report_date=date(fiscal_year + 1, 3, 31),
                source_urls=_urls(DART_BULK_LIST_URL),
            )
        )
    return sorted(items, key=lambda item: item.ticker)


def _prefer_consolidated_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    consolidated = [row for row in rows if str(row.get("fs_div", "")) == "CFS"]
    return consolidated or list(rows)


def _find_dart_account(
    rows: Sequence[Mapping[str, object]],
    aliases: Sequence[str],
) -> Mapping[str, object] | None:
    normalized_aliases = {_normalize_account_name(alias) for alias in aliases}
    matches = [
        row
        for row in rows
        if _normalize_account_name(str(row.get("account_nm", ""))) in normalized_aliases
    ]
    return next(
        (row for row in matches if str(row.get("fs_div", "")) == "CFS"),
        matches[0] if matches else None,
    )


def _industry_model(industry: str | None, company_name: str) -> IndustryModel:
    text = f"{industry or ''} {company_name}".casefold()
    if any(token in text for token in ("보험", "insurance")):
        return IndustryModel.INSURANCE
    if any(token in text for token in ("은행", "금융", "증권", "bank", "financial")):
        return IndustryModel.FINANCIAL
    if any(token in text for token in ("리츠", "reit")):
        return IndustryModel.REIT
    return IndustryModel.GENERAL if industry else IndustryModel.UNKNOWN


def _normalize_account_name(value: str) -> str:
    return re.sub(r"[\s·_-]+", "", value).casefold()


def _dart_amount(value: object) -> float | None:
    if value is None:
        return None
    normalized = str(value).replace(",", "").strip()
    if not normalized or normalized == "-":
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if number == number else None


def _parse_iso_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _urls(*values: str) -> tuple[AnyHttpUrl, ...]:
    return tuple(AnyHttpUrl(value) for value in values)


def _chunks[T](values: Sequence[T], size: int) -> Iterable[Sequence[T]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _read_fresh_batch_cache(
    path: Path,
    ttl: timedelta,
    market: MarketId,
) -> BulkFundamentalsBatch | None:
    if not path.exists():
        return None
    try:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        if datetime.now(UTC) - modified_at >= ttl:
            return None
        batch = BulkFundamentalsBatch.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return batch if batch.market is market else None


def _write_batch_cache(path: Path, batch: BulkFundamentalsBatch) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(batch.model_dump_json(), encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise BulkFundamentalsSourceError("대량 재무 캐시를 저장하지 못했습니다.") from exc
