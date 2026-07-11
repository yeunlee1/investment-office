# 미국과 한국의 거시 문맥과 시장 국면을 실패 격리형 개요로 조립한다
from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from investment_office.services.ecos_context import ECOS_SECTION_ID
from investment_office.services.macro_context import (
    SECTION_TITLES,
    MacroContextResult,
)
from investment_office.services.market_regime import (
    MarketRegime,
    MarketRegimeAssessment,
    MarketRegimeEvaluator,
    RegimeState,
)
from investment_office.services.research_contracts import (
    Fact,
    MarketId,
    ResearchSection,
    SectionStatus,
)

COMMON_SECTION_IDS = tuple(SECTION_TITLES)
MARKET_LABELS = {
    MarketId.US: "미국 시장",
    MarketId.KR: "한국 시장",
}


class MacroContextProvider(Protocol):
    """ResearchPipeline의 시장별 거시 문맥 조회 계약."""

    async def get_macro_context(
        self,
        market: MarketId | None = None,
    ) -> MacroContextResult: ...


class MarketOverviewDataQuality(BaseModel):
    """시장 개요에서 필요한 거시 자료 품질 요약."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    macro_eligible: bool
    blocking_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    stale_fact_ids: tuple[str, ...] = ()
    blocked_section_ids: tuple[str, ...] = ()


class CommonMacroOverview(BaseModel):
    """두 시장이 공유하는 FRED 거시 사실과 구역."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ready", "degraded"]
    facts: tuple[Fact, ...] = ()
    sections: tuple[ResearchSection, ...] = ()
    warnings: tuple[str, ...] = ()


class MarketOverviewEntry(BaseModel):
    """단일 시장의 국면과 자료 품질."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    market: MarketId
    label: str
    regime: MarketRegime
    confidence: float = Field(ge=0, le=1)
    position_cap_multiplier: float = Field(ge=0, le=1)
    warnings: tuple[str, ...] = ()
    data_quality: MarketOverviewDataQuality


class MarketOverviewMarkets(BaseModel):
    """API의 고정된 미국·한국 시장 키."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    us: MarketOverviewEntry
    kr: MarketOverviewEntry


class MarketOverview(BaseModel):
    """시장 관제 화면이 한 번에 소비하는 직렬화 가능한 응답."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    generated_at: AwareDatetime
    common: CommonMacroOverview
    markets: MarketOverviewMarkets


@dataclass(frozen=True, slots=True)
class _MacroFetch:
    result: MacroContextResult | None
    failure: str | None = None


class MarketOverviewService:
    """시장별 거시 조회를 병렬 실행하고 한 시장의 실패를 격리한다."""

    def __init__(
        self,
        pipeline: MacroContextProvider,
        *,
        regime_evaluator: MarketRegimeEvaluator | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.regime_evaluator = regime_evaluator or MarketRegimeEvaluator()
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    async def build(self) -> MarketOverview:
        """미국과 한국 문맥을 동시에 조회하고 독립적인 결과로 만든다."""

        us_fetch, kr_fetch = await asyncio.gather(
            self._fetch_market(MarketId.US),
            self._fetch_market(MarketId.KR),
        )
        generated_at = _aware_utc(self._now_factory())
        return MarketOverview(
            generated_at=generated_at,
            common=_build_common(us_fetch, kr_fetch),
            markets=MarketOverviewMarkets(
                us=self._build_market_entry(MarketId.US, us_fetch),
                kr=self._build_market_entry(MarketId.KR, kr_fetch),
            ),
        )

    async def _fetch_market(self, market: MarketId) -> _MacroFetch:
        try:
            return _MacroFetch(result=await self.pipeline.get_macro_context(market))
        except Exception as exc:
            return _MacroFetch(
                result=None,
                failure=(
                    f"{MARKET_LABELS[market]} 거시 자료 수집이 실패했습니다. {type(exc).__name__}."
                ),
            )

    def _build_market_entry(
        self,
        market: MarketId,
        fetched: _MacroFetch,
    ) -> MarketOverviewEntry:
        if fetched.result is None:
            failure = fetched.failure or f"{MARKET_LABELS[market]} 거시 자료가 없습니다."
            assessment = _evaluate_regime(self.regime_evaluator, market, ())
            quality = _failed_quality(market, failure)
        else:
            assessment = _evaluate_regime(
                self.regime_evaluator,
                market,
                fetched.result.facts,
            )
            quality = _build_quality(fetched.result, market)

        return MarketOverviewEntry(
            market=market,
            label=MARKET_LABELS[market],
            regime=assessment.regime,
            confidence=assessment.confidence,
            position_cap_multiplier=assessment.position_cap_multiplier,
            warnings=_unique(
                (
                    *(assessment.warnings),
                    *(quality.warnings),
                    *(quality.blocking_reasons),
                )
            ),
            data_quality=quality,
        )


def _build_common(us_fetch: _MacroFetch, kr_fetch: _MacroFetch) -> CommonMacroOverview:
    source_result = us_fetch.result or kr_fetch.result
    if source_result is None:
        failures = _unique(
            failure for failure in (us_fetch.failure, kr_fetch.failure) if failure is not None
        )
        return CommonMacroOverview(
            status="degraded",
            warnings=failures or ("공통 FRED 거시 자료를 수집하지 못했습니다.",),
        )

    common_sections = tuple(
        section for section in source_result.sections if section.section_id in COMMON_SECTION_IDS
    )
    common_fact_ids = {fact_id for section in common_sections for fact_id in section.fact_ids}
    common_facts = tuple(fact for fact in source_result.facts if fact.fact_id in common_fact_ids)
    common_result = MacroContextResult(
        sources=source_result.sources,
        facts=common_facts,
        sections=common_sections,
        stale_fact_ids=tuple(
            fact_id for fact_id in source_result.stale_fact_ids if fact_id in common_fact_ids
        ),
        future_section_ids=tuple(
            section_id
            for section_id in source_result.future_section_ids
            if section_id in COMMON_SECTION_IDS
        ),
    )
    quality = _build_quality(common_result, MarketId.US)
    return CommonMacroOverview(
        status="ready" if quality.macro_eligible else "degraded",
        facts=common_facts,
        sections=common_sections,
        warnings=_unique((*quality.warnings, *quality.blocking_reasons)),
    )


def _build_quality(
    result: MacroContextResult,
    market: MarketId,
) -> MarketOverviewDataQuality:
    sections = {
        section.section_id: section
        for section in result.sections
        if section.section_id.startswith("macro.")
    }
    expected_section_ids = _expected_section_ids(market)
    blocked_section_ids: list[str] = []
    for section_id in expected_section_ids:
        section = sections.get(section_id)
        if section is None or section.status is not SectionStatus.COMPLETE:
            blocked_section_ids.append(section_id)
    blocked_section_ids.extend(
        section.section_id
        for section in sections.values()
        if section.required
        and section.status is not SectionStatus.COMPLETE
        and section.section_id not in blocked_section_ids
    )
    blocked_section_ids.extend(
        section_id
        for section_id in result.future_section_ids
        if section_id not in blocked_section_ids
    )

    blocking_reasons: list[str] = []
    warnings: list[str] = []
    for section_id in blocked_section_ids:
        section = sections.get(section_id)
        if section is None:
            blocking_reasons.append(f"필수 거시 구역 {section_id}을 수집하지 못했습니다.")
            continue
        if section.blocking_reasons:
            blocking_reasons.extend(section.blocking_reasons)
        else:
            blocking_reasons.append(f"필수 거시 구역 {section.title}이 완전하지 않습니다.")
        warnings.extend(section.data_gaps)

    for section in sections.values():
        if section.section_id in blocked_section_ids:
            continue
        if section.status is not SectionStatus.COMPLETE:
            warnings.extend(section.data_gaps or section.blocking_reasons)

    stale_fact_ids = _unique(result.stale_fact_ids)
    if stale_fact_ids:
        blocking_reasons.append("허용 수명을 넘은 거시 사실이 있어 신규 분석을 차단합니다.")
    eligible = not blocked_section_ids and not stale_fact_ids
    if not eligible and not blocking_reasons:
        blocking_reasons.append("필수 거시 자료 품질 조건을 충족하지 못했습니다.")
    return MarketOverviewDataQuality(
        macro_eligible=eligible,
        blocking_reasons=_unique(blocking_reasons),
        warnings=_unique(warnings),
        stale_fact_ids=stale_fact_ids,
        blocked_section_ids=_unique(blocked_section_ids),
    )


def _failed_quality(market: MarketId, failure: str) -> MarketOverviewDataQuality:
    return MarketOverviewDataQuality(
        macro_eligible=False,
        blocking_reasons=(failure,),
        blocked_section_ids=_expected_section_ids(market),
    )


def _evaluate_regime(
    evaluator: MarketRegimeEvaluator,
    market: MarketId,
    facts: Sequence[Fact],
) -> MarketRegimeAssessment:
    try:
        return evaluator.evaluate(market=market, facts=facts)
    except Exception as exc:
        return MarketRegimeAssessment(
            market=market,
            regime=MarketRegime(
                rates=RegimeState.UNKNOWN,
                currency=RegimeState.UNKNOWN,
                volatility=RegimeState.UNKNOWN,
                commodities=RegimeState.UNKNOWN,
                liquidity=RegimeState.UNKNOWN,
            ),
            confidence=0,
            evidence_fact_ids=(),
            warnings=(f"시장 국면 평가가 실패했습니다. {type(exc).__name__}.",),
            position_cap_multiplier=0.25,
        )


def _expected_section_ids(market: MarketId) -> tuple[str, ...]:
    if market is MarketId.KR:
        return (*COMMON_SECTION_IDS, ECOS_SECTION_ID)
    return COMMON_SECTION_IDS


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("시장 개요 생성 시각에는 시간대 정보가 필요합니다.")
    return value.astimezone(UTC)


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))
