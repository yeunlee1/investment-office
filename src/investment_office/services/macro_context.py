# 공통 거시 지표를 권리 확인된 공식 원공급원에서 수집해 연구 계약으로 정규화한다
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import math
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final, Literal
from xml.etree import ElementTree

import httpx
from pydantic import AnyHttpUrl

from investment_office.services.research_contracts import (
    Fact,
    PublicationTimeBasis,
    ResearchSection,
    SectionStatus,
    SourceRef,
    SourceTier,
)

FRED_CSV_URL: Final = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_SOURCE_ID: Final = "official:fred:macro"
LOOKBACK_DAYS: Final = 30
BASELINE_MAX_LAG_DAYS: Final = 7
DEFAULT_MAX_AGE_DAYS: Final = 7
MAX_FRED_ARCHIVE_BYTES: Final = 5 * 1024 * 1024
MAX_FRED_UNCOMPRESSED_BYTES: Final = 20 * 1024 * 1024
FRED_REQUEST_CHUNK_SIZE: Final = 10
TREASURY_XML_URL: Final = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
)
BLS_API_URL: Final = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
TREASURY_SOURCE_ID: Final = "official:us_treasury:yield_curve"
BLS_SOURCE_ID: Final = "official:bls:public_data"
MAX_OFFICIAL_RESPONSE_BYTES: Final = 2 * 1024 * 1024

MacroSectionId = Literal[
    "macro.rates",
    "macro.currency",
    "macro.volatility",
    "macro.commodities",
    "macro.liquidity",
    "macro.growth_inflation",
]
ChangeMode = Literal["percentage_point", "percent"]


@dataclass(frozen=True, slots=True)
class FredSeriesSpec:
    series_id: str
    metric: str
    section_id: MacroSectionId
    unit: str
    currency: str | None
    change_mode: ChangeMode
    lookback_days: int = LOOKBACK_DAYS
    baseline_max_lag_days: int = BASELINE_MAX_LAG_DAYS
    max_age_days: int | None = None
    change_label: str = "30일 변화"


FRED_SERIES: Final = (
    FredSeriesSpec("VIXCLS", "VIX 종가", "macro.volatility", "index_point", None, "percent"),
    FredSeriesSpec(
        "DCOILWTICO",
        "WTI 현물 가격",
        "macro.commodities",
        "usd_per_barrel",
        "USD",
        "percent",
    ),
    FredSeriesSpec(
        "DCOILBRENTEU",
        "브렌트유 현물 가격",
        "macro.commodities",
        "usd_per_barrel",
        "USD",
        "percent",
    ),
    FredSeriesSpec(
        "DFF",
        "미국 실효 연방기금금리",
        "macro.rates",
        "percent",
        None,
        "percentage_point",
    ),
    FredSeriesSpec(
        "DGS2",
        "미국 국채 2년물 금리",
        "macro.rates",
        "percent",
        None,
        "percentage_point",
    ),
    FredSeriesSpec(
        "DGS3",
        "미국 국채 3년물 금리",
        "macro.rates",
        "percent",
        None,
        "percentage_point",
    ),
    FredSeriesSpec(
        "DGS10",
        "미국 국채 10년물 금리",
        "macro.rates",
        "percent",
        None,
        "percentage_point",
    ),
    FredSeriesSpec(
        "T10Y2Y",
        "미국 국채 10년물과 2년물 금리차",
        "macro.rates",
        "percentage_point",
        None,
        "percentage_point",
    ),
    FredSeriesSpec(
        "DTWEXBGS",
        "미 연준 광의 달러지수",
        "macro.currency",
        "index_point",
        None,
        "percent",
        max_age_days=14,
    ),
    FredSeriesSpec(
        "CBBTCUSD",
        "비트코인 미국 달러 가격",
        "macro.liquidity",
        "usd_per_bitcoin",
        "USD",
        "percent",
    ),
    FredSeriesSpec(
        "WALCL",
        "미 연준 총자산",
        "macro.liquidity",
        "million_usd",
        "USD",
        "percent",
        baseline_max_lag_days=14,
        max_age_days=14,
    ),
    FredSeriesSpec(
        "RRPONTSYD",
        "미 연준 역레포 잔액",
        "macro.liquidity",
        "billion_usd",
        "USD",
        "percent",
    ),
    FredSeriesSpec(
        "DEXKOUS",
        "원·달러 환율",
        "macro.currency",
        "krw_per_usd",
        None,
        "percent",
        max_age_days=14,
    ),
    FredSeriesSpec(
        "CPIAUCSL",
        "미국 소비자물가지수",
        "macro.growth_inflation",
        "index_1982_1984_100",
        None,
        "percent",
        lookback_days=365,
        baseline_max_lag_days=45,
        max_age_days=75,
        change_label="12개월 변화",
    ),
    FredSeriesSpec(
        "CPILFESL",
        "미국 근원 소비자물가지수",
        "macro.growth_inflation",
        "index_1982_1984_100",
        None,
        "percent",
        lookback_days=365,
        baseline_max_lag_days=45,
        max_age_days=75,
        change_label="12개월 변화",
    ),
    FredSeriesSpec(
        "UNRATE",
        "미국 실업률",
        "macro.growth_inflation",
        "percent",
        None,
        "percentage_point",
        baseline_max_lag_days=35,
        max_age_days=75,
        change_label="1개월 변화",
    ),
    FredSeriesSpec(
        "INDPRO",
        "미국 산업생산지수",
        "macro.growth_inflation",
        "index_2017_100",
        None,
        "percent",
        lookback_days=365,
        baseline_max_lag_days=45,
        max_age_days=75,
        change_label="12개월 변화",
    ),
)
FRED_SERIES_IDS: Final = tuple(spec.series_id for spec in FRED_SERIES)

SECTION_TITLES: Final[Mapping[MacroSectionId, str]] = {
    "macro.rates": "금리와 수익률 곡선",
    "macro.currency": "달러와 원화 환율",
    "macro.volatility": "시장 변동성",
    "macro.commodities": "원유 가격",
    "macro.liquidity": "유동성과 위험 선호",
    "macro.growth_inflation": "미국 성장과 물가",
}
SECTION_ORDER: Final = tuple(SECTION_TITLES)


class MacroContextError(RuntimeError):
    """공식 거시 자료 요청이나 해석에 실패했을 때 발생한다."""


@dataclass(frozen=True, slots=True)
class MacroContextResult:
    sources: tuple[SourceRef, ...]
    facts: tuple[Fact, ...]
    sections: tuple[ResearchSection, ...]
    stale_fact_ids: tuple[str, ...] = ()
    future_section_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Observation:
    observed_on: date
    value: float


@dataclass(frozen=True, slots=True)
class _SeriesResult:
    facts: tuple[Fact, ...]
    data_gaps: tuple[str, ...]
    stale_fact_ids: tuple[str, ...]
    blocking_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _OfficialSeriesSpec:
    series_id: str
    source_id: str
    fact_prefix: str
    metric: str
    unit: str
    currency: str | None
    change_mode: ChangeMode
    lookback_days: int
    baseline_max_lag_days: int
    max_age_days: int
    change_label: str
    lookback_months: int | None = None


_TREASURY_SPECS: Final = (
    _OfficialSeriesSpec(
        "2y",
        TREASURY_SOURCE_ID,
        "macro:treasury:2y",
        "미국 국채 2년물 금리",
        "percent",
        None,
        "percentage_point",
        30,
        7,
        7,
        "30일 변화",
    ),
    _OfficialSeriesSpec(
        "3y",
        TREASURY_SOURCE_ID,
        "macro:treasury:3y",
        "미국 국채 3년물 금리",
        "percent",
        None,
        "percentage_point",
        30,
        7,
        7,
        "30일 변화",
    ),
    _OfficialSeriesSpec(
        "10y",
        TREASURY_SOURCE_ID,
        "macro:treasury:10y",
        "미국 국채 10년물 금리",
        "percent",
        None,
        "percentage_point",
        30,
        7,
        7,
        "30일 변화",
    ),
    _OfficialSeriesSpec(
        "10y2y",
        TREASURY_SOURCE_ID,
        "macro:treasury:10y2y",
        "미국 국채 10년물과 2년물 금리차",
        "percentage_point",
        None,
        "percentage_point",
        30,
        7,
        7,
        "30일 변화",
    ),
)
_BLS_SPECS: Final = (
    _OfficialSeriesSpec(
        "CUSR0000SA0",
        BLS_SOURCE_ID,
        "macro:bls:cpi",
        "미국 소비자물가지수",
        "index_1982_1984_100",
        None,
        "percent",
        365,
        45,
        75,
        "12개월 변화",
        lookback_months=12,
    ),
    _OfficialSeriesSpec(
        "CUSR0000SA0L1E",
        BLS_SOURCE_ID,
        "macro:bls:core_cpi",
        "미국 근원 소비자물가지수",
        "index_1982_1984_100",
        None,
        "percent",
        365,
        45,
        75,
        "12개월 변화",
        lookback_months=12,
    ),
    _OfficialSeriesSpec(
        "LNS14000000",
        BLS_SOURCE_ID,
        "macro:bls:unemployment",
        "미국 실업률",
        "percent",
        None,
        "percentage_point",
        31,
        7,
        75,
        "1개월 변화",
        lookback_months=1,
    ),
)


class OfficialMacroContextClient:
    """미국 재무부와 노동통계국 원자료만 사용해 공통 거시 입력을 만든다."""

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

    async def fetch(self) -> MacroContextResult:
        """권리 확인된 두 공식 원공급원을 병렬 조회하고 미구성 축은 차단한다."""

        collected_at = self._aware_now()
        if self.client is not None:
            results = await self._fetch_responses(self.client, collected_at.year)
        else:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                results = await self._fetch_responses(client, collected_at.year)

        treasury_responses = tuple(
            result
            for result in results[:2]
            if isinstance(result, httpx.Response)
        )
        treasury_errors = tuple(
            _safe_provider_error("미국 재무부", result)
            for result in results[:2]
            if isinstance(result, BaseException)
        )
        bls_response = results[2] if isinstance(results[2], httpx.Response) else None
        bls_error = (
            _safe_provider_error("미국 노동통계국", results[2])
            if isinstance(results[2], BaseException)
            else None
        )

        sources: list[SourceRef] = []
        facts: list[Fact] = []
        stale_fact_ids: list[str] = []
        sections: list[ResearchSection] = []

        treasury_observations: dict[str, tuple[_Observation, ...]] = {
            spec.series_id: () for spec in _TREASURY_SPECS
        }
        treasury_gaps: list[str] = []
        treasury_blocks = list(treasury_errors)
        if treasury_responses:
            try:
                treasury_observations = _merge_treasury_observations(
                    tuple(
                        _parse_treasury_xml(response.content, collected_at.date())
                        for response in treasury_responses
                    )
                )
                sources.append(
                    SourceRef(
                        source_id=TREASURY_SOURCE_ID,
                        name="미국 재무부 국채 금리",
                        tier=SourceTier.OFFICIAL,
                        url=AnyHttpUrl(TREASURY_XML_URL),
                        retrieved_at=collected_at,
                        content_checksum=hashlib.sha256(
                            b"\0".join(response.content for response in treasury_responses)
                        ).hexdigest(),
                    )
                )
            except MacroContextError as exc:
                treasury_blocks.append(str(exc))
        for spec in _TREASURY_SPECS:
            series_result = _build_official_series(
                spec,
                treasury_observations[spec.series_id],
                collected_at,
            )
            facts.extend(series_result.facts)
            stale_fact_ids.extend(series_result.stale_fact_ids)
            treasury_gaps.extend(series_result.data_gaps)
            treasury_blocks.extend(series_result.blocking_reasons)
        sections.append(
            _build_section(
                "macro.rates",
                [fact.fact_id for fact in facts if fact.source_id == TREASURY_SOURCE_ID],
                treasury_gaps,
                treasury_blocks,
            )
        )

        bls_observations: dict[str, tuple[_Observation, ...]] = {
            spec.series_id: () for spec in _BLS_SPECS
        }
        bls_gaps: list[str] = []
        bls_blocks = [bls_error] if bls_error is not None else []
        if bls_response is not None:
            try:
                bls_observations = _parse_bls_json(bls_response.content, collected_at.date())
                sources.append(
                    SourceRef(
                        source_id=BLS_SOURCE_ID,
                        name="미국 노동통계국 공개 자료",
                        tier=SourceTier.OFFICIAL,
                        url=AnyHttpUrl(BLS_API_URL),
                        retrieved_at=collected_at,
                        content_checksum=hashlib.sha256(bls_response.content).hexdigest(),
                    )
                )
            except MacroContextError as exc:
                bls_blocks.append(str(exc))
        growth_fact_ids: list[str] = []
        for spec in _BLS_SPECS:
            series_result = _build_official_series(
                spec,
                bls_observations[spec.series_id],
                collected_at,
            )
            facts.extend(series_result.facts)
            growth_fact_ids.extend(fact.fact_id for fact in series_result.facts)
            stale_fact_ids.extend(series_result.stale_fact_ids)
            bls_gaps.extend(series_result.data_gaps)
            bls_blocks.extend(series_result.blocking_reasons)
        sections.extend(
            (
                _build_section(
                    "macro.growth_inflation",
                    growth_fact_ids,
                    bls_gaps,
                    bls_blocks,
                ),
                _unavailable_macro_section(
                    "macro.currency",
                    "연준 이사회 환율 원자료 어댑터가 아직 구성되지 않았습니다.",
                ),
                _unavailable_macro_section(
                    "macro.volatility",
                    "생성형 AI 사용 권리가 확인된 VIX 공급원이 구성되지 않았습니다.",
                ),
                _unavailable_macro_section(
                    "macro.commodities",
                    "생성형 AI 사용 권리가 확인된 원유 공급원이 구성되지 않았습니다.",
                ),
                _unavailable_macro_section(
                    "macro.liquidity",
                    "연준 이사회 유동성 원자료 어댑터가 아직 구성되지 않았습니다.",
                ),
            )
        )
        section_by_id = {section.section_id: section for section in sections}
        return MacroContextResult(
            sources=tuple(sources),
            facts=tuple(facts),
            sections=tuple(section_by_id[section_id] for section_id in SECTION_ORDER),
            stale_fact_ids=tuple(dict.fromkeys(stale_fact_ids)),
        )

    async def _fetch_responses(
        self,
        client: httpx.AsyncClient,
        current_year: int,
    ) -> tuple[httpx.Response | BaseException, ...]:
        headers = {
            "Accept": "application/xml, application/json",
            "User-Agent": "investment-office/0.1",
        }
        treasury_start_year = current_year - 1
        bls_start_year = current_year - 2
        requests = (
            self._get_treasury(client, current_year, headers),
            self._get_treasury(client, treasury_start_year, headers),
            self._get_bls(client, bls_start_year, current_year, headers),
        )
        return tuple(await asyncio.gather(*requests, return_exceptions=True))

    async def _get_treasury(
        self,
        client: httpx.AsyncClient,
        year: int,
        headers: Mapping[str, str],
    ) -> httpx.Response:
        response = await client.get(
            TREASURY_XML_URL,
            params={
                "data": "daily_treasury_yield_curve",
                "field_tdr_date_value": str(year),
            },
            headers=headers,
            timeout=self.timeout_seconds,
        )
        return _validate_official_response(response, "미국 재무부")

    async def _get_bls(
        self,
        client: httpx.AsyncClient,
        start_year: int,
        end_year: int,
        headers: Mapping[str, str],
    ) -> httpx.Response:
        response = await client.post(
            BLS_API_URL,
            json={
                "seriesid": [spec.series_id for spec in _BLS_SPECS],
                "startyear": str(start_year),
                "endyear": str(end_year),
            },
            headers=headers,
            timeout=self.timeout_seconds,
        )
        return _validate_official_response(response, "미국 노동통계국")

    def _aware_now(self) -> datetime:
        now = self._now_factory()
        if now.tzinfo is None or now.utcoffset() is None:
            raise MacroContextError("거시 자료 수집 시각에는 시간대 정보가 필요합니다.")
        return now.astimezone(UTC)


class FredMacroContextClient:
    """공식 FRED CSV 한 건으로 공통 거시 자료를 비동기로 조회한다."""

    def __init__(
        self,
        timeout_seconds: float = 20.0,
        client: httpx.AsyncClient | None = None,
        *,
        now_factory: Callable[[], datetime] | None = None,
        max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    ) -> None:
        if isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds는 0보다 커야 합니다.")
        if isinstance(max_age_days, bool) or max_age_days < 1:
            raise ValueError("max_age_days는 1 이상이어야 합니다.")
        self.timeout_seconds = float(timeout_seconds)
        self.client = client
        self._now_factory = now_factory or (lambda: datetime.now(UTC))
        self._max_age = timedelta(days=max_age_days)

    async def fetch(self) -> MacroContextResult:
        """모든 지정 계열을 한 요청으로 읽어 최신값과 30일 변화를 만든다."""

        raise MacroContextError(
            "FRED 약관이 생성형 AI 연계와 저장·캐시를 금지하므로 이 수집기는 비활성화됐습니다."
        )

        responses = await self._get_all()
        collected_at = self._aware_now()
        observations = _merge_observation_sets(
            tuple(
                _parse_fred_content(response.content, collected_at.date())
                for response in responses
            )
        )
        source = SourceRef(
            source_id=FRED_SOURCE_ID,
            name="Federal Reserve Economic Data",
            tier=SourceTier.OFFICIAL,
            url=AnyHttpUrl(FRED_CSV_URL),
            retrieved_at=collected_at,
            content_checksum=hashlib.sha256(
                b"\0".join(response.content for response in responses)
            ).hexdigest(),
        )

        facts: list[Fact] = []
        stale_fact_ids: list[str] = []
        section_fact_ids: dict[MacroSectionId, list[str]] = {
            section_id: [] for section_id in SECTION_ORDER
        }
        section_gaps: dict[MacroSectionId, list[str]] = {
            section_id: [] for section_id in SECTION_ORDER
        }
        section_blocks: dict[MacroSectionId, list[str]] = {
            section_id: [] for section_id in SECTION_ORDER
        }

        for spec in FRED_SERIES:
            result = self._build_series(spec, observations[spec.series_id], collected_at)
            facts.extend(result.facts)
            stale_fact_ids.extend(result.stale_fact_ids)
            section_fact_ids[spec.section_id].extend(fact.fact_id for fact in result.facts)
            section_gaps[spec.section_id].extend(result.data_gaps)
            section_blocks[spec.section_id].extend(result.blocking_reasons)

        sections = tuple(
            _build_section(
                section_id,
                section_fact_ids[section_id],
                section_gaps[section_id],
                section_blocks[section_id],
            )
            for section_id in SECTION_ORDER
        )
        return MacroContextResult(
            sources=(source,),
            facts=tuple(facts),
            sections=sections,
            stale_fact_ids=tuple(stale_fact_ids),
        )

    async def _get_all(self) -> tuple[httpx.Response, ...]:
        chunks = tuple(
            FRED_SERIES_IDS[index : index + FRED_REQUEST_CHUNK_SIZE]
            for index in range(0, len(FRED_SERIES_IDS), FRED_REQUEST_CHUNK_SIZE)
        )
        headers = {
            "Accept": "text/csv",
            "User-Agent": "investment-office/0.1",
        }
        try:
            if self.client is not None:
                responses = await asyncio.gather(
                    *(
                        self.client.get(
                            FRED_CSV_URL,
                            params={"id": ",".join(chunk)},
                            headers=headers,
                            timeout=self.timeout_seconds,
                        )
                        for chunk in chunks
                    )
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    responses = await asyncio.gather(
                        *(
                            client.get(
                                FRED_CSV_URL,
                                params={"id": ",".join(chunk)},
                                headers=headers,
                            )
                            for chunk in chunks
                        )
                    )
            for response in responses:
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MacroContextError(f"FRED 거시 자료 요청이 실패했습니다. {exc}") from exc
        return tuple(responses)

    def _aware_now(self) -> datetime:
        now = self._now_factory()
        if now.tzinfo is None or now.utcoffset() is None:
            raise MacroContextError("거시 자료 수집 시각에는 시간대 정보가 필요합니다.")
        return now.astimezone(UTC)

    def _build_series(
        self,
        spec: FredSeriesSpec,
        observations: tuple[_Observation, ...],
        collected_at: datetime,
    ) -> _SeriesResult:
        if not observations:
            return _SeriesResult(
                facts=(),
                data_gaps=(f"{spec.series_id} 최신 유효값이 없습니다.",),
                stale_fact_ids=(),
                blocking_reasons=(),
            )

        latest = observations[-1]
        level_fact = _build_fact(spec, latest, collected_at, kind="level")
        facts = [level_fact]
        data_gaps: list[str] = []
        max_age = (
            timedelta(days=spec.max_age_days)
            if spec.max_age_days is not None
            else self._max_age
        )
        stale = collected_at - _at_utc_midnight(latest.observed_on) > max_age

        baseline = _find_baseline(
            observations,
            latest.observed_on,
            lookback_days=spec.lookback_days,
            max_lag_days=spec.baseline_max_lag_days,
        )
        if baseline is None:
            data_gaps.append(
                f"{spec.series_id}의 유효한 {spec.change_label} 기준값이 없습니다."
            )
        else:
            change = _calculate_change(spec, latest.value, baseline.value)
            if change is None:
                data_gaps.append(
                    f"{spec.series_id}의 {spec.change_label} 기준값이 0입니다."
                )
            else:
                facts.append(
                    _build_fact(
                        spec,
                        _Observation(latest.observed_on, change),
                        collected_at,
                        kind="change",
                    )
                )

        fact_ids = tuple(fact.fact_id for fact in facts)
        if not stale:
            return _SeriesResult(tuple(facts), tuple(data_gaps), (), ())
        age_days = (collected_at.date() - latest.observed_on).days
        return _SeriesResult(
            facts=tuple(facts),
            data_gaps=tuple(data_gaps),
            stale_fact_ids=fact_ids,
            blocking_reasons=(
                f"{spec.series_id} 최신값이 {age_days}일 전 자료여서 허용 수명을 초과했습니다.",
            ),
        )


def _validate_official_response(
    response: httpx.Response,
    provider_name: str,
) -> httpx.Response:
    try:
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise MacroContextError(
            f"{provider_name} 응답 상태가 올바르지 않습니다."
        ) from exc
    if len(response.content) > MAX_OFFICIAL_RESPONSE_BYTES:
        raise MacroContextError(f"{provider_name} 응답이 허용 크기를 초과했습니다.")
    return response


def _safe_provider_error(provider_name: str, error: BaseException) -> str:
    if isinstance(error, MacroContextError):
        return str(error)
    if isinstance(error, httpx.TimeoutException):
        return f"{provider_name} 요청이 시간 제한을 초과했습니다."
    if isinstance(error, httpx.HTTPError):
        return f"{provider_name} 네트워크 요청에 실패했습니다."
    return f"{provider_name} 자료를 안전하게 해석하지 못했습니다."


def _parse_treasury_xml(
    content: bytes,
    cutoff_date: date,
) -> dict[str, tuple[_Observation, ...]]:
    if len(content) > MAX_OFFICIAL_RESPONSE_BYTES:
        raise MacroContextError("미국 재무부 응답이 허용 크기를 초과했습니다.")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise MacroContextError("미국 재무부 XML을 읽을 수 없습니다.") from exc

    values: dict[str, dict[date, float]] = {
        spec.series_id: {} for spec in _TREASURY_SPECS
    }
    for properties in root.iter():
        if _xml_local_name(properties.tag) != "properties":
            continue
        row = {
            _xml_local_name(child.tag): (child.text or "").strip()
            for child in properties
        }
        observed_on = _parse_date_prefix(row.get("NEW_DATE"))
        if observed_on is None or observed_on > cutoff_date:
            continue
        two_year = _parse_number(row.get("BC_2YEAR"))
        three_year = _parse_number(row.get("BC_3YEAR"))
        ten_year = _parse_number(row.get("BC_10YEAR"))
        if two_year is not None:
            values["2y"][observed_on] = two_year
        if three_year is not None:
            values["3y"][observed_on] = three_year
        if ten_year is not None:
            values["10y"][observed_on] = ten_year
        if two_year is not None and ten_year is not None:
            values["10y2y"][observed_on] = round(ten_year - two_year, 6)

    return {
        series_id: tuple(
            _Observation(observed_on, value)
            for observed_on, value in sorted(series_values.items())
        )
        for series_id, series_values in values.items()
    }


def _merge_treasury_observations(
    observation_sets: tuple[dict[str, tuple[_Observation, ...]], ...],
) -> dict[str, tuple[_Observation, ...]]:
    merged: dict[str, dict[date, float]] = {
        spec.series_id: {} for spec in _TREASURY_SPECS
    }
    for observations_by_series in observation_sets:
        for series_id, observations in observations_by_series.items():
            for observation in observations:
                merged[series_id][observation.observed_on] = observation.value
    return {
        series_id: tuple(
            _Observation(observed_on, value)
            for observed_on, value in sorted(series_values.items())
        )
        for series_id, series_values in merged.items()
    }


def _parse_bls_json(
    content: bytes,
    cutoff_date: date,
) -> dict[str, tuple[_Observation, ...]]:
    if len(content) > MAX_OFFICIAL_RESPONSE_BYTES:
        raise MacroContextError("미국 노동통계국 응답이 허용 크기를 초과했습니다.")
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MacroContextError("미국 노동통계국 JSON을 읽을 수 없습니다.") from exc
    if not isinstance(payload, dict) or payload.get("status") != "REQUEST_SUCCEEDED":
        raise MacroContextError("미국 노동통계국이 성공 상태를 반환하지 않았습니다.")
    results = payload.get("Results")
    raw_series = results.get("series") if isinstance(results, dict) else None
    if not isinstance(raw_series, list):
        raise MacroContextError("미국 노동통계국 응답에 시계열 목록이 없습니다.")

    values: dict[str, dict[date, float]] = {
        spec.series_id: {} for spec in _BLS_SPECS
    }
    for series in raw_series:
        if not isinstance(series, dict):
            continue
        series_id = series.get("seriesID")
        if not isinstance(series_id, str) or series_id not in values:
            continue
        raw_data = series.get("data")
        if not isinstance(raw_data, list):
            continue
        for item in raw_data:
            if not isinstance(item, dict):
                continue
            year = item.get("year")
            period = item.get("period")
            value = _parse_number(item.get("value") if isinstance(item.get("value"), str) else None)
            if not (
                isinstance(year, str)
                and isinstance(period, str)
                and len(period) == 3
                and period.startswith("M")
                and period[1:].isdigit()
                and value is not None
            ):
                continue
            month = int(period[1:])
            if not 1 <= month <= 12:
                continue
            try:
                observed_on = date(int(year), month, 1)
            except ValueError:
                continue
            if observed_on <= cutoff_date:
                values[series_id][observed_on] = value
    return {
        series_id: tuple(
            _Observation(observed_on, value)
            for observed_on, value in sorted(series_values.items())
        )
        for series_id, series_values in values.items()
    }


def _build_official_series(
    spec: _OfficialSeriesSpec,
    observations: tuple[_Observation, ...],
    collected_at: datetime,
) -> _SeriesResult:
    if not observations:
        return _SeriesResult(
            facts=(),
            data_gaps=(f"{spec.metric} 최신 유효값이 없습니다.",),
            stale_fact_ids=(),
            blocking_reasons=(),
        )
    latest = observations[-1]
    facts = [
        _build_official_fact(spec, latest, collected_at, kind="level")
    ]
    data_gaps: list[str] = []
    baseline = (
        _find_monthly_baseline(
            observations,
            latest.observed_on,
            months=spec.lookback_months,
        )
        if spec.lookback_months is not None
        else _find_baseline(
            observations,
            latest.observed_on,
            lookback_days=spec.lookback_days,
            max_lag_days=spec.baseline_max_lag_days,
        )
    )
    if baseline is None:
        data_gaps.append(f"{spec.metric}의 유효한 {spec.change_label} 기준값이 없습니다.")
    else:
        change = _calculate_official_change(spec, latest.value, baseline.value)
        if change is None:
            data_gaps.append(f"{spec.metric}의 {spec.change_label} 기준값이 0입니다.")
        else:
            facts.append(
                _build_official_fact(
                    spec,
                    _Observation(latest.observed_on, change),
                    collected_at,
                    kind="change",
                )
            )
    fact_ids = tuple(fact.fact_id for fact in facts)
    age_days = (collected_at.date() - latest.observed_on).days
    if age_days <= spec.max_age_days:
        return _SeriesResult(tuple(facts), tuple(data_gaps), (), ())
    return _SeriesResult(
        facts=tuple(facts),
        data_gaps=tuple(data_gaps),
        stale_fact_ids=fact_ids,
        blocking_reasons=(
            f"{spec.metric} 최신값이 {age_days}일 전 자료여서 허용 수명을 초과했습니다.",
        ),
    )


def _calculate_official_change(
    spec: _OfficialSeriesSpec,
    latest_value: float,
    baseline_value: float,
) -> float | None:
    if spec.change_mode == "percentage_point":
        return round(latest_value - baseline_value, 6)
    if baseline_value == 0:
        return None
    return round((latest_value / baseline_value - 1) * 100, 6)


def _build_official_fact(
    spec: _OfficialSeriesSpec,
    observation: _Observation,
    collected_at: datetime,
    *,
    kind: Literal["level", "change"],
) -> Fact:
    is_change = kind == "change"
    return Fact(
        fact_id=(
            f"{spec.fact_prefix}:change_{spec.lookback_days}d"
            if is_change
            else f"{spec.fact_prefix}:level"
        ),
        source_id=spec.source_id,
        metric=f"{spec.metric} {spec.change_label}" if is_change else spec.metric,
        value=observation.value,
        unit=(
            "percentage_point"
            if is_change and spec.change_mode == "percentage_point"
            else "percent"
            if is_change
            else spec.unit
        ),
        currency=None if is_change else spec.currency,
        observed_at=_at_utc_midnight(observation.observed_on),
        published_at=collected_at,
        collected_at=collected_at,
        publication_time_basis=PublicationTimeBasis.RETRIEVAL_TIME_PROXY,
    )


def _unavailable_macro_section(
    section_id: MacroSectionId,
    reason: str,
) -> ResearchSection:
    return ResearchSection(
        section_id=section_id,
        title=SECTION_TITLES[section_id],
        status=SectionStatus.UNAVAILABLE,
        required=True,
        blocking_reasons=(reason,),
    )


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_date_prefix(raw: str | None) -> date | None:
    if raw is None or len(raw) < 10:
        return None
    return _parse_date(raw[:10])


def build_ecos_unavailable_section(api_key: str | None) -> ResearchSection | None:
    """ECOS 키가 없을 때 한국 고유 거시 구역을 명시적으로 사용 불가 처리한다."""

    if api_key is not None and api_key.strip():
        return None
    return ResearchSection(
        section_id="macro.kr.ecos",
        title="한국 고유 거시 지표",
        status=SectionStatus.UNAVAILABLE,
        required=True,
        blocking_reasons=("한국은행 ECOS API 키가 없어 한국 고유 거시 자료를 수집할 수 없습니다.",),
    )


def _parse_fred_csv(
    content: str,
    cutoff_date: date,
) -> dict[str, tuple[_Observation, ...]]:
    reader = csv.DictReader(io.StringIO(content))
    fieldnames = set(reader.fieldnames or ())
    date_field = "observation_date" if "observation_date" in fieldnames else "DATE"
    if date_field not in fieldnames:
        raise MacroContextError("FRED CSV에 관측일 열이 없습니다.")

    parsed: dict[str, dict[date, float]] = {series_id: {} for series_id in FRED_SERIES_IDS}
    for row in reader:
        observed_on = _parse_date(row.get(date_field))
        if observed_on is None or observed_on > cutoff_date:
            continue
        for series_id in FRED_SERIES_IDS:
            value = _parse_number(row.get(series_id))
            if value is not None:
                parsed[series_id][observed_on] = value

    return {
        series_id: tuple(
            _Observation(observed_on, value) for observed_on, value in sorted(series_values.items())
        )
        for series_id, series_values in parsed.items()
    }


def _parse_fred_content(
    content: bytes,
    cutoff_date: date,
) -> dict[str, tuple[_Observation, ...]]:
    """단일 CSV와 여러 빈도별 CSV가 담긴 공식 ZIP 응답을 동일하게 읽는다."""

    if len(content) > MAX_FRED_ARCHIVE_BYTES:
        raise MacroContextError("FRED 응답이 허용 크기를 초과했습니다.")
    if not zipfile.is_zipfile(io.BytesIO(content)):
        try:
            decoded = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise MacroContextError("FRED CSV 문자 인코딩을 읽을 수 없습니다.") from exc
        return _parse_fred_csv(decoded, cutoff_date)

    merged: dict[str, dict[date, float]] = {
        series_id: {} for series_id in FRED_SERIES_IDS
    }
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = [
                member
                for member in archive.infolist()
                if not member.is_dir() and member.filename.casefold().endswith(".csv")
            ]
            if not members:
                raise MacroContextError("FRED ZIP 응답에 CSV 파일이 없습니다.")
            if sum(member.file_size for member in members) > MAX_FRED_UNCOMPRESSED_BYTES:
                raise MacroContextError("FRED ZIP 압축 해제 크기가 허용 범위를 초과했습니다.")
            for member in members:
                try:
                    decoded = archive.read(member).decode("utf-8-sig")
                except UnicodeDecodeError as exc:
                    raise MacroContextError(
                        "FRED ZIP 안의 CSV 문자 인코딩을 읽을 수 없습니다."
                    ) from exc
                parsed = _parse_fred_csv(decoded, cutoff_date)
                for series_id, observations in parsed.items():
                    for observation in observations:
                        merged[series_id][observation.observed_on] = observation.value
    except zipfile.BadZipFile as exc:
        raise MacroContextError("FRED ZIP 응답을 읽을 수 없습니다.") from exc

    return {
        series_id: tuple(
            _Observation(observed_on, value)
            for observed_on, value in sorted(series_values.items())
        )
        for series_id, series_values in merged.items()
    }


def _merge_observation_sets(
    observation_sets: tuple[dict[str, tuple[_Observation, ...]], ...],
) -> dict[str, tuple[_Observation, ...]]:
    merged: dict[str, dict[date, float]] = {
        series_id: {} for series_id in FRED_SERIES_IDS
    }
    for observations_by_series in observation_sets:
        for series_id, observations in observations_by_series.items():
            for observation in observations:
                merged[series_id][observation.observed_on] = observation.value
    return {
        series_id: tuple(
            _Observation(observed_on, value)
            for observed_on, value in sorted(series_values.items())
        )
        for series_id, series_values in merged.items()
    }


def _parse_date(raw: str | None) -> date | None:
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return None


def _parse_number(raw: str | None) -> float | None:
    if raw is None:
        return None
    normalized = raw.strip()
    if not normalized or normalized == ".":
        return None
    try:
        value = float(normalized)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _find_baseline(
    observations: tuple[_Observation, ...],
    latest_date: date,
    *,
    lookback_days: int,
    max_lag_days: int,
) -> _Observation | None:
    target = latest_date - timedelta(days=lookback_days)
    earliest = target - timedelta(days=max_lag_days)
    candidates = [
        observation for observation in observations if earliest <= observation.observed_on <= target
    ]
    return candidates[-1] if candidates else None


def _find_monthly_baseline(
    observations: tuple[_Observation, ...],
    latest_date: date,
    *,
    months: int,
) -> _Observation | None:
    month_index = latest_date.year * 12 + latest_date.month - 1 - months
    target_year, zero_based_month = divmod(month_index, 12)
    target_month = zero_based_month + 1
    candidates = [
        observation
        for observation in observations
        if observation.observed_on.year == target_year
        and observation.observed_on.month == target_month
    ]
    return candidates[-1] if candidates else None


def _calculate_change(
    spec: FredSeriesSpec,
    latest_value: float,
    baseline_value: float,
) -> float | None:
    if spec.change_mode == "percentage_point":
        return round(latest_value - baseline_value, 6)
    if baseline_value == 0:
        return None
    return round((latest_value / baseline_value - 1) * 100, 6)


def _build_fact(
    spec: FredSeriesSpec,
    observation: _Observation,
    collected_at: datetime,
    *,
    kind: Literal["level", "change"],
) -> Fact:
    is_change = kind == "change"
    fact_kind = f"change_{spec.lookback_days}d" if is_change else "level"
    change_unit = "percentage_point" if spec.change_mode == "percentage_point" else "percent"
    return Fact(
        fact_id=f"macro:fred:{spec.series_id.casefold()}:{fact_kind}",
        source_id=FRED_SOURCE_ID,
        metric=f"{spec.metric} {spec.change_label}" if is_change else spec.metric,
        value=observation.value,
        unit=change_unit if is_change else spec.unit,
        currency=None if is_change else spec.currency,
        observed_at=_at_utc_midnight(observation.observed_on),
        published_at=_at_utc_midnight(observation.observed_on),
        collected_at=collected_at,
        publication_time_basis=PublicationTimeBasis.OBSERVATION_DATE_PROXY,
    )


def _build_section(
    section_id: MacroSectionId,
    fact_ids: list[str],
    data_gaps: list[str],
    blocking_reasons: list[str],
) -> ResearchSection:
    fact_ids = list(dict.fromkeys(fact_ids))
    data_gaps = list(dict.fromkeys(data_gaps))
    blocking_reasons = list(dict.fromkeys(blocking_reasons))
    if blocking_reasons:
        status = SectionStatus.BLOCKED
    elif data_gaps and fact_ids:
        status = SectionStatus.PARTIAL
    elif data_gaps:
        status = SectionStatus.BLOCKED
        blocking_reasons = [
            f"{SECTION_TITLES[section_id]}의 핵심 지표를 하나도 확보하지 못했습니다."
        ]
    else:
        status = SectionStatus.COMPLETE
    return ResearchSection(
        section_id=section_id,
        title=SECTION_TITLES[section_id],
        status=status,
        required=True,
        fact_ids=tuple(fact_ids),
        data_gaps=tuple(data_gaps),
        blocking_reasons=tuple(blocking_reasons),
    )


def _at_utc_midnight(observed_on: date) -> datetime:
    return datetime.combine(observed_on, datetime.min.time(), tzinfo=UTC)
