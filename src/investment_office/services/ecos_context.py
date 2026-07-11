# 한국은행 ECOS의 한국 고유 거시 지표를 검증된 코드로 수집한다
from __future__ import annotations

import asyncio
import hashlib
import math
import re
from calendar import monthrange
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final, Literal
from urllib.parse import quote

import httpx
from pydantic import AnyHttpUrl

from investment_office.services.research_contracts import (
    Fact,
    ResearchSection,
    SectionStatus,
    SourceRef,
    SourceTier,
)

ECOS_OPEN_API_URL: Final = "https://ecos.bok.or.kr/api/"
ECOS_STATISTIC_SEARCH_URL: Final = "https://ecos.bok.or.kr/api/StatisticSearch"
ECOS_STATISTIC_ITEM_LIST_URL: Final = "https://ecos.bok.or.kr/api/StatisticItemList"
ECOS_SOURCE_ID: Final = "official:bok-ecos:macro:kr"
ECOS_SECTION_ID: Final = "macro.kr.ecos"
DEFAULT_DAILY_MAX_AGE_DAYS: Final = 7
DEFAULT_MONTHLY_MAX_AGE_DAYS: Final = 70
_API_KEY_PATTERN: Final = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_ERROR_CODE_PATTERN: Final = re.compile(r"^[A-Z]+-\d+$")

Cycle = Literal["D", "M"]


@dataclass(frozen=True, slots=True)
class EcosSeriesSpec:
    slug: str
    stat_code: str
    item_code: str
    cycle: Cycle
    metric: str
    unit: str
    currency: str | None
    lookback_days: int


# 아래 코드는 ECOS StatisticItemList와 StatisticSearch 양쪽에서 확인한 값만 사용한다.
ECOS_SERIES: Final = (
    EcosSeriesSpec(
        slug="base_rate",
        stat_code="722Y001",
        item_code="0101000",
        cycle="D",
        metric="한국은행 기준금리",
        unit="percent",
        currency=None,
        lookback_days=45,
    ),
    EcosSeriesSpec(
        slug="kr_gov_3y",
        stat_code="817Y002",
        item_code="010200000",
        cycle="D",
        metric="한국 국고채 3년물 금리",
        unit="percent",
        currency=None,
        lookback_days=45,
    ),
    EcosSeriesSpec(
        slug="kr_gov_10y",
        stat_code="817Y002",
        item_code="010210000",
        cycle="D",
        metric="한국 국고채 10년물 금리",
        unit="percent",
        currency=None,
        lookback_days=45,
    ),
    EcosSeriesSpec(
        slug="usd_krw",
        stat_code="731Y001",
        item_code="0000001",
        cycle="D",
        metric="원·미국달러 매매기준율",
        unit="krw_per_usd",
        currency="KRW",
        lookback_days=45,
    ),
    EcosSeriesSpec(
        slug="cpi",
        stat_code="901Y009",
        item_code="0",
        cycle="M",
        metric="한국 소비자물가지수 총지수",
        unit="index_2020_100",
        currency=None,
        lookback_days=550,
    ),
)


@dataclass(frozen=True, slots=True)
class EcosContextResult:
    sources: tuple[SourceRef, ...]
    facts: tuple[Fact, ...]
    sections: tuple[ResearchSection, ...]
    stale_fact_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Observation:
    observed_on: date
    value: float


@dataclass(frozen=True, slots=True)
class _SeriesFetch:
    fact: Fact | None
    content: bytes
    blocking_reason: str | None
    stale_fact_id: str | None = None


class EcosMacroContextClient:
    """공식 ECOS API에서 한국 고유 거시 지표를 비동기로 수집한다."""

    def __init__(
        self,
        api_key: str | None,
        timeout_seconds: float = 20.0,
        client: httpx.AsyncClient | None = None,
        *,
        now_factory: Callable[[], datetime] | None = None,
        daily_max_age_days: int = DEFAULT_DAILY_MAX_AGE_DAYS,
        monthly_max_age_days: int = DEFAULT_MONTHLY_MAX_AGE_DAYS,
    ) -> None:
        if isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds는 0보다 커야 합니다.")
        if isinstance(daily_max_age_days, bool) or daily_max_age_days < 1:
            raise ValueError("daily_max_age_days는 1 이상이어야 합니다.")
        if isinstance(monthly_max_age_days, bool) or monthly_max_age_days < 1:
            raise ValueError("monthly_max_age_days는 1 이상이어야 합니다.")
        self.api_key = api_key
        self.timeout_seconds = float(timeout_seconds)
        self.client = client
        self._now_factory = now_factory or (lambda: datetime.now(UTC))
        self._daily_max_age = timedelta(days=daily_max_age_days)
        self._monthly_max_age = timedelta(days=monthly_max_age_days)

    async def fetch(self) -> EcosContextResult:
        """인증과 응답 품질을 확인하고 하나의 필수 한국 거시 구역을 반환한다."""

        collected_at = self._aware_now()
        api_key = self.api_key.strip() if self.api_key is not None else ""
        if not api_key:
            return _empty_result(
                status=SectionStatus.UNAVAILABLE,
                reason="한국은행 ECOS API 키가 없어 한국 고유 거시 자료를 수집할 수 없습니다.",
            )
        if _API_KEY_PATTERN.fullmatch(api_key) is None:
            return _empty_result(
                status=SectionStatus.BLOCKED,
                reason="한국은행 ECOS API 키 형식이 유효하지 않아 요청을 차단했습니다.",
            )

        if self.client is not None:
            series_results = await self._fetch_all(self.client, api_key, collected_at)
        else:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                series_results = await self._fetch_all(client, api_key, collected_at)
        return _assemble_result(series_results, collected_at)

    async def _fetch_all(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        collected_at: datetime,
    ) -> tuple[_SeriesFetch, ...]:
        return tuple(
            await asyncio.gather(
                *(
                    self._fetch_series(client, api_key, spec, collected_at)
                    for spec in ECOS_SERIES
                )
            )
        )

    async def _fetch_series(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        spec: EcosSeriesSpec,
        collected_at: datetime,
    ) -> _SeriesFetch:
        start, end = _request_period(spec, collected_at.date())
        url = "/".join(
            (
                ECOS_STATISTIC_SEARCH_URL,
                quote(api_key, safe=""),
                "json",
                "kr",
                "1",
                "100",
                spec.stat_code,
                spec.cycle,
                start,
                end,
                spec.item_code,
                "",
            )
        )
        try:
            response = await client.get(
                url,
                headers={"Accept": "application/json", "User-Agent": "investment-office/0.1"},
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError:
            return _failed_series(spec, f"{spec.metric} 요청 중 네트워크 오류가 발생했습니다.")

        if response.status_code < 200 or response.status_code >= 300:
            return _failed_series(
                spec,
                f"{spec.metric} 요청이 HTTP {response.status_code} 상태로 실패했습니다.",
            )
        try:
            payload: Any = response.json()
        except ValueError:
            return _failed_series(spec, f"{spec.metric} 응답이 유효한 JSON이 아닙니다.")

        logical_error = _logical_error_code(payload)
        if logical_error is not None:
            return _failed_series(
                spec,
                f"{spec.metric} 조회가 ECOS 논리 오류 {logical_error}로 거절되었습니다.",
            )
        observation = _latest_observation(payload, spec, collected_at.date())
        if observation is None:
            return _failed_series(
                spec,
                f"{spec.metric} 응답에서 검증 가능한 최신값을 찾지 못했습니다.",
            )

        fact = Fact(
            fact_id=f"macro:ecos:{spec.slug}:level",
            source_id=ECOS_SOURCE_ID,
            metric=spec.metric,
            value=observation.value,
            unit=spec.unit,
            currency=spec.currency,
            observed_at=_at_utc_midnight(observation.observed_on),
            published_at=collected_at,
            collected_at=collected_at,
        )
        max_age = self._monthly_max_age if spec.cycle == "M" else self._daily_max_age
        age = collected_at - fact.observed_at
        if age <= max_age:
            return _SeriesFetch(fact=fact, content=response.content, blocking_reason=None)
        age_days = (collected_at.date() - observation.observed_on).days
        return _SeriesFetch(
            fact=fact,
            content=response.content,
            blocking_reason=(
                f"{spec.metric} 최신값이 {age_days}일 전 자료여서 허용 수명을 초과했습니다."
            ),
            stale_fact_id=fact.fact_id,
        )

    def _aware_now(self) -> datetime:
        now = self._now_factory()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("ECOS 자료 수집 시각에는 시간대 정보가 필요합니다.")
        return now.astimezone(UTC)


def _assemble_result(
    series_results: tuple[_SeriesFetch, ...],
    collected_at: datetime,
) -> EcosContextResult:
    facts = tuple(result.fact for result in series_results if result.fact is not None)
    reasons = _unique(
        tuple(
            result.blocking_reason
            for result in series_results
            if result.blocking_reason is not None
        )
    )
    stale_fact_ids = tuple(
        result.stale_fact_id
        for result in series_results
        if result.stale_fact_id is not None
    )
    sources: tuple[SourceRef, ...] = ()
    if facts:
        checksum_input = b"".join(result.content for result in series_results if result.fact)
        sources = (
            SourceRef(
                source_id=ECOS_SOURCE_ID,
                name="한국은행 경제통계시스템 ECOS",
                tier=SourceTier.OFFICIAL,
                url=AnyHttpUrl(ECOS_OPEN_API_URL),
                retrieved_at=collected_at,
                content_checksum=hashlib.sha256(checksum_input).hexdigest(),
            ),
        )
    section = ResearchSection(
        section_id=ECOS_SECTION_ID,
        title="한국 고유 거시 지표",
        status=SectionStatus.BLOCKED if reasons else SectionStatus.COMPLETE,
        required=True,
        fact_ids=tuple(fact.fact_id for fact in facts),
        data_gaps=reasons,
        blocking_reasons=reasons,
    )
    return EcosContextResult(
        sources=sources,
        facts=facts,
        sections=(section,),
        stale_fact_ids=stale_fact_ids,
    )


def _empty_result(*, status: SectionStatus, reason: str) -> EcosContextResult:
    return EcosContextResult(
        sources=(),
        facts=(),
        sections=(
            ResearchSection(
                section_id=ECOS_SECTION_ID,
                title="한국 고유 거시 지표",
                status=status,
                required=True,
                blocking_reasons=(reason,),
            ),
        ),
    )


def _failed_series(spec: EcosSeriesSpec, reason: str) -> _SeriesFetch:
    return _SeriesFetch(
        fact=None,
        content=b"",
        blocking_reason=f"{spec.stat_code}/{spec.item_code} 자료 공백. {reason}",
    )


def _request_period(spec: EcosSeriesSpec, cutoff: date) -> tuple[str, str]:
    start = cutoff - timedelta(days=spec.lookback_days)
    if spec.cycle == "D":
        return start.strftime("%Y%m%d"), cutoff.strftime("%Y%m%d")
    return start.strftime("%Y%m"), cutoff.strftime("%Y%m")


def _logical_error_code(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return "UNKNOWN"
    result = payload.get("RESULT")
    if not isinstance(result, dict):
        return None
    raw_code = result.get("CODE")
    if not isinstance(raw_code, str) or _ERROR_CODE_PATTERN.fullmatch(raw_code) is None:
        return "UNKNOWN"
    return raw_code


def _latest_observation(
    payload: Any,
    spec: EcosSeriesSpec,
    cutoff: date,
) -> _Observation | None:
    if not isinstance(payload, dict):
        return None
    root = payload.get("StatisticSearch")
    if not isinstance(root, dict):
        return None
    rows = root.get("row")
    if not isinstance(rows, list):
        return None

    observations: list[_Observation] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("STAT_CODE") != spec.stat_code or row.get("ITEM_CODE1") != spec.item_code:
            continue
        observed_on = _parse_period(row.get("TIME"), spec.cycle)
        value = _parse_number(row.get("DATA_VALUE"))
        if observed_on is None or observed_on > cutoff or value is None:
            continue
        observations.append(_Observation(observed_on=observed_on, value=value))
    return max(observations, key=lambda observation: observation.observed_on, default=None)


def _parse_period(raw: Any, cycle: Cycle) -> date | None:
    if not isinstance(raw, str):
        return None
    try:
        if cycle == "D" and len(raw) == 8:
            return datetime.strptime(raw, "%Y%m%d").date()
        if cycle == "M" and len(raw) == 6:
            year = int(raw[:4])
            month = int(raw[4:])
            return date(year, month, monthrange(year, month)[1])
    except ValueError:
        return None
    return None


def _parse_number(raw: Any) -> float | None:
    if not isinstance(raw, (str, int, float)) or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _at_utc_midnight(observed_on: date) -> datetime:
    return datetime.combine(observed_on, datetime.min.time(), tzinfo=UTC)
