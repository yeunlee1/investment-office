# 공통 거시 지표를 FRED에서 수집하고 연구 계약으로 정규화한다
from __future__ import annotations

import csv
import hashlib
import io
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final, Literal

import httpx
from pydantic import AnyHttpUrl

from investment_office.services.research_contracts import (
    Fact,
    ResearchSection,
    SectionStatus,
    SourceRef,
    SourceTier,
)

FRED_CSV_URL: Final = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_SOURCE_ID: Final = "official:fred:macro"
FUTURE_GROWTH_INFLATION_SECTION_ID: Final = "macro.growth_inflation"
LOOKBACK_DAYS: Final = 30
BASELINE_MAX_LAG_DAYS: Final = 7
DEFAULT_MAX_AGE_DAYS: Final = 7

MacroSectionId = Literal[
    "macro.rates",
    "macro.currency",
    "macro.volatility",
    "macro.commodities",
    "macro.liquidity",
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
        "percent",
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
        "DEXKOUS",
        "원·달러 환율",
        "macro.currency",
        "krw_per_usd",
        None,
        "percent",
    ),
)
FRED_SERIES_IDS: Final = tuple(spec.series_id for spec in FRED_SERIES)

SECTION_TITLES: Final[Mapping[MacroSectionId, str]] = {
    "macro.rates": "금리와 수익률 곡선",
    "macro.currency": "달러와 원화 환율",
    "macro.volatility": "시장 변동성",
    "macro.commodities": "원유 가격",
    "macro.liquidity": "유동성과 위험 선호",
}
SECTION_ORDER: Final = tuple(SECTION_TITLES)


class MacroContextError(RuntimeError):
    """FRED 거시 자료 요청이나 해석에 실패했을 때 발생한다."""


@dataclass(frozen=True, slots=True)
class MacroContextResult:
    sources: tuple[SourceRef, ...]
    facts: tuple[Fact, ...]
    sections: tuple[ResearchSection, ...]
    stale_fact_ids: tuple[str, ...] = ()
    future_section_ids: tuple[str, ...] = (FUTURE_GROWTH_INFLATION_SECTION_ID,)


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

        response = await self._get()
        collected_at = self._aware_now()
        observations = _parse_fred_csv(response.text, collected_at.date())
        source = SourceRef(
            source_id=FRED_SOURCE_ID,
            name="Federal Reserve Economic Data",
            tier=SourceTier.OFFICIAL,
            url=AnyHttpUrl(str(response.request.url)),
            retrieved_at=collected_at,
            content_checksum=hashlib.sha256(response.content).hexdigest(),
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

    async def _get(self) -> httpx.Response:
        params = {"id": ",".join(FRED_SERIES_IDS)}
        headers = {
            "Accept": "text/csv",
            "User-Agent": "investment-office/0.1",
        }
        try:
            if self.client is not None:
                response = await self.client.get(
                    FRED_CSV_URL,
                    params=params,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.get(
                        FRED_CSV_URL,
                        params=params,
                        headers=headers,
                    )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MacroContextError(f"FRED 거시 자료 요청이 실패했습니다. {exc}") from exc
        return response

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
        stale = collected_at - _at_utc_midnight(latest.observed_on) > self._max_age

        baseline = _find_baseline(observations, latest.observed_on)
        if baseline is None:
            data_gaps.append(f"{spec.series_id}의 유효한 30일 전 기준값이 없습니다.")
        else:
            change = _calculate_change(spec, latest.value, baseline.value)
            if change is None:
                data_gaps.append(f"{spec.series_id}의 30일 변화율 기준값이 0입니다.")
            else:
                facts.append(
                    _build_fact(
                        spec,
                        _Observation(latest.observed_on, change),
                        collected_at,
                        kind="change_30d",
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
) -> _Observation | None:
    target = latest_date - timedelta(days=LOOKBACK_DAYS)
    earliest = target - timedelta(days=BASELINE_MAX_LAG_DAYS)
    candidates = [
        observation for observation in observations if earliest <= observation.observed_on <= target
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
    kind: Literal["level", "change_30d"],
) -> Fact:
    is_change = kind == "change_30d"
    change_unit = "percentage_point" if spec.change_mode == "percentage_point" else "percent"
    return Fact(
        fact_id=f"macro:fred:{spec.series_id.casefold()}:{kind}",
        source_id=FRED_SOURCE_ID,
        metric=f"{spec.metric} 30일 변화" if is_change else spec.metric,
        value=observation.value,
        unit=change_unit if is_change else spec.unit,
        currency=None if is_change else spec.currency,
        observed_at=_at_utc_midnight(observation.observed_on),
        published_at=collected_at,
        collected_at=collected_at,
    )


def _build_section(
    section_id: MacroSectionId,
    fact_ids: list[str],
    data_gaps: list[str],
    blocking_reasons: list[str],
) -> ResearchSection:
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
