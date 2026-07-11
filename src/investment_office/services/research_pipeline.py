# 가격·거시·공식 회사 자료를 실패 격리형 분석 입력 번들로 조립한다
from __future__ import annotations

import asyncio
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from urllib.parse import urlparse

from pydantic import AnyHttpUrl

from investment_office.services.company_research import (
    FUNDAMENTAL_SECTION_ID,
    OFFICIAL_DISCLOSURE_METADATA_GAP,
    OFFICIAL_DISCLOSURE_METADATA_UNITS,
    OFFICIAL_NEWS_SECTION_ID,
    CompanyResearchResult,
    OfficialCompanyResearchClient,
    calculate_valuation_metrics,
)
from investment_office.services.ecos_context import (
    EcosContextResult,
    EcosMacroContextClient,
)
from investment_office.services.macro_context import (
    SECTION_TITLES,
    MacroContextResult,
    OfficialMacroContextClient,
    build_ecos_unavailable_section,
)
from investment_office.services.market_data import EODSnapshot
from investment_office.services.market_regime import (
    MarketRegime,
    MarketRegimeAssessment,
    MarketRegimeEvaluator,
    RegimeState,
)
from investment_office.services.research_contracts import (
    AnalysisInputBundle,
    DataQualityReport,
    Fact,
    FactValue,
    InstrumentRef,
    MarketId,
    PublicationTimeBasis,
    ResearchSection,
    SectionStatus,
    SourceRef,
    SourceTier,
)

PRICE_CORE_SECTION_ID = "market.price.core"
PRICE_TECHNICAL_SECTION_ID = "market.price.technical"
VALUATION_SECTION_ID = "company.valuation"
INDEPENDENT_NEWS_SECTION_ID = "company.independent_news"
INTEGRITY_SECTION_ID = "pipeline.integrity"
COMMON_REQUIRED_MACRO_SECTION_IDS = tuple(SECTION_TITLES)
KR_REQUIRED_MACRO_SECTION_ID = "macro.kr.ecos"


class MacroCollector(Protocol):
    async def fetch(self) -> MacroContextResult: ...


class CompanyCollector(Protocol):
    async def fetch(
        self,
        instrument: InstrumentRef,
        *,
        cutoff: datetime,
        business_year: int | None = None,
        report_code: str = "11011",
    ) -> CompanyResearchResult: ...


class EcosCollector(Protocol):
    async def fetch(self) -> EcosContextResult: ...


class RegimeEvaluator(Protocol):
    def evaluate(
        self,
        *,
        market: MarketId | str,
        facts: Sequence[Fact],
    ) -> MarketRegimeAssessment: ...


@dataclass(frozen=True, slots=True)
class ResearchPipelineResult:
    """검증된 연구 번들과 에이전트가 바로 소비할 사실 목록."""

    bundle: AnalysisInputBundle
    regime: MarketRegimeAssessment
    fundamentals: list[dict[str, object]]
    news: list[dict[str, object]]
    macro: list[dict[str, object]]
    observation_cutoff: datetime


@dataclass(frozen=True, slots=True)
class _CollectedPart:
    sources: tuple[SourceRef, ...]
    facts: tuple[Fact, ...]
    sections: tuple[ResearchSection, ...]
    stale_fact_ids: tuple[str, ...] = ()
    missing_required_sections: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _MergedResearch:
    sources: tuple[SourceRef, ...]
    facts: tuple[Fact, ...]
    sections: tuple[ResearchSection, ...]
    integrity_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ValuationInput:
    value: float | None
    fact: Fact | None
    is_proxy: bool = False


class ResearchPipeline:
    """서로 독립적인 자료 공급원을 병렬 수집하고 품질 차단을 한곳에서 적용한다."""

    def __init__(
        self,
        *,
        macro_client: MacroCollector | OfficialMacroContextClient,
        company_client: CompanyCollector | OfficialCompanyResearchClient,
        ecos_client: EcosCollector | EcosMacroContextClient | None = None,
        regime_evaluator: RegimeEvaluator | MarketRegimeEvaluator | None = None,
        ecos_api_key: str | None = None,
        now_factory: Callable[[], datetime] | None = None,
        price_max_age_days: int = 7,
        fundamental_max_age_days: int = 180,
        disclosure_max_age_days: int = 120,
        macro_cache_ttl_seconds: float = 14_400,
    ) -> None:
        if isinstance(price_max_age_days, bool) or price_max_age_days < 1:
            raise ValueError("price_max_age_days는 1 이상이어야 합니다.")
        if isinstance(macro_cache_ttl_seconds, bool) or macro_cache_ttl_seconds <= 0:
            raise ValueError("macro_cache_ttl_seconds는 0보다 커야 합니다.")
        if isinstance(fundamental_max_age_days, bool) or fundamental_max_age_days < 1:
            raise ValueError("fundamental_max_age_days는 1 이상이어야 합니다.")
        if isinstance(disclosure_max_age_days, bool) or disclosure_max_age_days < 1:
            raise ValueError("disclosure_max_age_days는 1 이상이어야 합니다.")
        self.macro_client = macro_client
        self.company_client = company_client
        self.regime_evaluator = regime_evaluator or MarketRegimeEvaluator()
        self.ecos_api_key = ecos_api_key
        self.ecos_client = ecos_client or (
            EcosMacroContextClient(ecos_api_key) if ecos_api_key and ecos_api_key.strip() else None
        )
        self._now_factory = now_factory or (lambda: datetime.now(UTC))
        self._price_max_age = timedelta(days=price_max_age_days)
        self._fundamental_max_age = timedelta(days=fundamental_max_age_days)
        self._disclosure_max_age = timedelta(days=disclosure_max_age_days)
        self._macro_cache_ttl = timedelta(seconds=float(macro_cache_ttl_seconds))
        self._macro_cache: MacroContextResult | None = None
        self._macro_cached_at: datetime | None = None
        self._macro_lock = asyncio.Lock()
        self._ecos_cache: EcosContextResult | None = None
        self._ecos_cached_at: datetime | None = None
        self._ecos_lock = asyncio.Lock()

    async def collect(
        self,
        instrument: InstrumentRef,
        snapshot: EODSnapshot,
        *,
        as_of: datetime | None = None,
        cutoff: datetime | None = None,
    ) -> ResearchPipelineResult:
        """관측 경계는 공급원에 전달하고 번들 경계는 실제 수집 완료 시각으로 잡는다."""

        requested_at = _require_aware(as_of or self._now_factory(), "as_of")
        observation_cutoff = _require_aware(cutoff or requested_at, "cutoff")
        has_explicit_observation_cutoff = cutoff is not None
        if snapshot.as_of_date > observation_cutoff.date():
            raise ValueError("시장 스냅샷 거래일은 관측 cutoff보다 늦을 수 없습니다.")

        macro_result, company_result = await asyncio.gather(
            self.get_macro_context(instrument.market),
            self._collect_company(instrument, observation_cutoff),
        )
        collection_finished_at = _require_aware(self._now_factory(), "수집 완료 시각")
        if not has_explicit_observation_cutoff:
            observation_cutoff = collection_finished_at
        macro_result = _restrict_macro_to_observation_cutoff(
            macro_result,
            observation_cutoff,
        )
        company_result = _restrict_company_to_observation_cutoff(
            company_result,
            observation_cutoff,
        )

        bundle_cutoff = _collection_cutoff(
            requested_at,
            collection_finished_at,
            snapshot,
            macro_result,
            company_result,
        )
        price_part = _build_price_part(
            instrument,
            snapshot,
            cutoff=bundle_cutoff,
            max_age=self._price_max_age,
        )
        macro_part = _macro_part(macro_result, instrument.market)
        company_part = _company_part(
            company_result,
            cutoff=observation_cutoff,
            fundamental_max_age=self._fundamental_max_age,
            disclosure_max_age=self._disclosure_max_age,
        )
        valuation_part = _build_valuation_part(
            instrument,
            snapshot,
            company_part,
        )
        independent_news_part = _independent_news_part()
        parts = (
            price_part,
            macro_part,
            company_part,
            valuation_part,
            independent_news_part,
        )
        merged = _merge_research(parts, instrument, bundle_cutoff)
        stale_fact_ids = _unique(
            fact_id
            for part in parts
            for fact_id in part.stale_fact_ids
            if any(fact.fact_id == fact_id for fact in merged.facts)
        )
        missing_required = _unique(
            section_id
            for part in parts
            for section_id in part.missing_required_sections
            if all(section.section_id != section_id for section in merged.sections)
        )
        quality = _build_quality(
            merged.sections,
            stale_fact_ids=stale_fact_ids,
            missing_required_sections=missing_required,
            generated_at=bundle_cutoff,
        )
        bundle = AnalysisInputBundle(
            cutoff=bundle_cutoff,
            market_session=snapshot.as_of_date,
            instrument=instrument,
            sources=merged.sources,
            facts=merged.facts,
            sections=merged.sections,
            quality=quality,
        )
        excluded_regime_fact_ids = {
            *bundle.quality.stale_fact_ids,
            *bundle.quality.blocked_fact_ids,
        }
        regime = _evaluate_regime(
            self.regime_evaluator,
            instrument.market,
            tuple(
                fact
                for fact in bundle.facts
                if fact.fact_id not in excluded_regime_fact_ids
            ),
        )
        source_by_id = {source.source_id: source for source in bundle.sources}
        fact_by_id = {fact.fact_id: fact for fact in bundle.facts}

        return ResearchPipelineResult(
            bundle=bundle,
            regime=regime,
            fundamentals=_agent_facts(
                bundle.sections,
                fact_by_id,
                source_by_id,
                {FUNDAMENTAL_SECTION_ID, VALUATION_SECTION_ID},
            ),
            news=_agent_facts(
                bundle.sections,
                fact_by_id,
                source_by_id,
                {OFFICIAL_NEWS_SECTION_ID, INDEPENDENT_NEWS_SECTION_ID},
                excluded_units=OFFICIAL_DISCLOSURE_METADATA_UNITS,
            ),
            macro=_agent_facts(
                bundle.sections,
                fact_by_id,
                source_by_id,
                {
                    section.section_id
                    for section in bundle.sections
                    if section.section_id.startswith("macro.")
                },
            ),
            observation_cutoff=observation_cutoff,
        )

    async def get_macro_context(self, market: MarketId | None = None) -> MacroContextResult:
        """4시간 캐시와 단일화를 적용해 공통 거시 자료를 시장별 보완 구역과 반환한다."""

        common_task = self._get_common_macro_context()
        if market is not MarketId.KR:
            return await common_task
        common, ecos = await asyncio.gather(common_task, self._get_ecos_context())
        return MacroContextResult(
            sources=(*common.sources, *ecos.sources),
            facts=(*common.facts, *ecos.facts),
            sections=(*common.sections, *ecos.sections),
            stale_fact_ids=_unique((*common.stale_fact_ids, *ecos.stale_fact_ids)),
            future_section_ids=common.future_section_ids,
        )

    async def _get_common_macro_context(self) -> MacroContextResult:
        now = _require_aware(self._now_factory(), "공통 거시 캐시 확인 시각")
        cached = self._valid_macro_cache(now)
        if cached is None:
            async with self._macro_lock:
                now = _require_aware(self._now_factory(), "공통 거시 캐시 확인 시각")
                cached = self._valid_macro_cache(now)
                if cached is None:
                    cached = await self._fetch_macro_uncached()
                    self._macro_cache = cached
                    self._macro_cached_at = _require_aware(
                        self._now_factory(), "공통 거시 캐시 저장 시각"
                    )
        return cached

    async def _get_ecos_context(self) -> EcosContextResult:
        if self.ecos_client is None:
            section = build_ecos_unavailable_section(self.ecos_api_key)
            if section is None:
                section = ResearchSection(
                    section_id="macro.kr.ecos",
                    title="한국 고유 거시 지표",
                    status=SectionStatus.UNAVAILABLE,
                    required=True,
                    blocking_reasons=("ECOS 수집기가 구성되지 않았습니다.",),
                )
            return EcosContextResult((), (), (section,))

        now = _require_aware(self._now_factory(), "ECOS 캐시 확인 시각")
        cached = self._valid_ecos_cache(now)
        if cached is None:
            async with self._ecos_lock:
                now = _require_aware(self._now_factory(), "ECOS 캐시 확인 시각")
                cached = self._valid_ecos_cache(now)
                if cached is None:
                    cached = await self._fetch_ecos_uncached()
                    self._ecos_cache = cached
                    self._ecos_cached_at = _require_aware(
                        self._now_factory(), "ECOS 캐시 저장 시각"
                    )
        return cached

    def _valid_macro_cache(self, now: datetime) -> MacroContextResult | None:
        if self._macro_cache is None or self._macro_cached_at is None:
            return None
        age = now - self._macro_cached_at
        if age < timedelta(0) or age >= self._macro_cache_ttl:
            return None
        return self._macro_cache

    def _valid_ecos_cache(self, now: datetime) -> EcosContextResult | None:
        if self._ecos_cache is None or self._ecos_cached_at is None:
            return None
        age = now - self._ecos_cached_at
        if age < timedelta(0) or age >= self._macro_cache_ttl:
            return None
        return self._ecos_cache

    async def _fetch_macro_uncached(self) -> MacroContextResult:
        try:
            return await self.macro_client.fetch()
        except Exception as exc:
            reason = _failure_reason("공통 공식 거시 자료", exc)
            return MacroContextResult(
                sources=(),
                facts=(),
                sections=tuple(
                    ResearchSection(
                        section_id=section_id,
                        title=title,
                        status=SectionStatus.UNAVAILABLE,
                        required=True,
                        blocking_reasons=(reason,),
                    )
                    for section_id, title in SECTION_TITLES.items()
                ),
                future_section_ids=(),
            )

    async def _fetch_ecos_uncached(self) -> EcosContextResult:
        if self.ecos_client is None:
            raise RuntimeError("ECOS 수집기가 구성되지 않았습니다.")
        try:
            return await self.ecos_client.fetch()
        except Exception as exc:
            reason = _failure_reason("한국은행 ECOS 거시 자료", exc)
            return EcosContextResult(
                sources=(),
                facts=(),
                sections=(
                    ResearchSection(
                        section_id="macro.kr.ecos",
                        title="한국 고유 거시 지표",
                        status=SectionStatus.UNAVAILABLE,
                        required=True,
                        blocking_reasons=(reason,),
                    ),
                ),
            )

    async def _collect_company(
        self,
        instrument: InstrumentRef,
        observation_cutoff: datetime,
    ) -> CompanyResearchResult:
        try:
            return await self.company_client.fetch(instrument, cutoff=observation_cutoff)
        except Exception as exc:
            reason = _failure_reason("공식 회사 자료", exc)
            return CompanyResearchResult(
                sources=(),
                facts=(),
                sections=(
                    ResearchSection(
                        section_id=FUNDAMENTAL_SECTION_ID,
                        title="공식 재무제표",
                        status=SectionStatus.UNAVAILABLE,
                        blocking_reasons=(reason,),
                    ),
                    ResearchSection(
                        section_id=OFFICIAL_NEWS_SECTION_ID,
                        title="공식 공시 이벤트",
                        status=SectionStatus.UNAVAILABLE,
                        blocking_reasons=(reason,),
                    ),
                ),
            )


def _collection_cutoff(
    requested_at: datetime,
    finished_at: datetime,
    snapshot: EODSnapshot,
    macro_result: MacroContextResult,
    company_result: CompanyResearchResult,
) -> datetime:
    timestamps = [requested_at, finished_at, _require_aware(snapshot.fetched_at, "가격 수집 시각")]
    timestamps.extend(source.retrieved_at for source in macro_result.sources)
    timestamps.extend(source.retrieved_at for source in company_result.sources)
    timestamps.extend(fact.collected_at for fact in macro_result.facts)
    timestamps.extend(fact.collected_at for fact in company_result.facts)
    return max(timestamp.astimezone(UTC) for timestamp in timestamps)


def _restrict_macro_to_observation_cutoff(
    result: MacroContextResult,
    observation_cutoff: datetime,
) -> MacroContextResult:
    retained_facts = tuple(
        fact
        for fact in result.facts
        if fact.observed_at <= observation_cutoff
        and fact.published_at <= observation_cutoff
    )
    retained_ids = {fact.fact_id for fact in retained_facts}
    removed_ids = {fact.fact_id for fact in result.facts} - retained_ids
    if not removed_ids:
        return result

    sections: list[ResearchSection] = []
    for section in result.sections:
        retained_section_ids = tuple(
            fact_id for fact_id in section.fact_ids if fact_id in retained_ids
        )
        removed_section_ids = set(section.fact_ids) - set(retained_section_ids)
        if not removed_section_ids:
            sections.append(section)
            continue
        gap = "관측 cutoff 이후의 거시 사실을 미래 정보로 제외했습니다."
        if not retained_section_ids:
            sections.append(
                ResearchSection(
                    section_id=section.section_id,
                    title=section.title,
                    status=SectionStatus.BLOCKED,
                    required=section.required,
                    data_gaps=_unique((*section.data_gaps, gap)),
                    blocking_reasons=_unique(
                        (*section.blocking_reasons, "관측 경계 이전의 거시 사실이 없습니다.")
                    ),
                )
            )
            continue
        sections.append(
            ResearchSection(
                section_id=section.section_id,
                title=section.title,
                status=(
                    SectionStatus.BLOCKED
                    if section.status is SectionStatus.BLOCKED
                    else SectionStatus.PARTIAL
                ),
                required=section.required,
                fact_ids=retained_section_ids,
                data_gaps=_unique((*section.data_gaps, gap)),
                blocking_reasons=section.blocking_reasons,
            )
        )
    return MacroContextResult(
        sources=result.sources,
        facts=retained_facts,
        sections=tuple(sections),
        stale_fact_ids=tuple(
            fact_id for fact_id in result.stale_fact_ids if fact_id in retained_ids
        ),
        future_section_ids=result.future_section_ids,
    )


def _restrict_company_to_observation_cutoff(
    result: CompanyResearchResult,
    observation_cutoff: datetime,
) -> CompanyResearchResult:
    retained_facts = tuple(
        fact
        for fact in result.facts
        if fact.observed_at <= observation_cutoff and fact.published_at <= observation_cutoff
    )
    retained_ids = {fact.fact_id for fact in retained_facts}
    removed_ids = {fact.fact_id for fact in result.facts} - retained_ids
    if not removed_ids:
        return result

    sections: list[ResearchSection] = []
    for section in result.sections:
        retained_section_ids = tuple(
            fact_id for fact_id in section.fact_ids if fact_id in retained_ids
        )
        removed_section_ids = set(section.fact_ids) - set(retained_section_ids)
        if not removed_section_ids:
            sections.append(section)
            continue
        gap = "관측 cutoff 이후에 공개된 회사 사실을 미래 정보로 제외했습니다."
        if not retained_section_ids:
            sections.append(
                ResearchSection(
                    section_id=section.section_id,
                    title=section.title,
                    status=SectionStatus.BLOCKED,
                    required=section.required,
                    data_gaps=_unique((*section.data_gaps, gap)),
                    blocking_reasons=_unique(
                        (*section.blocking_reasons, "관측 경계 이전의 회사 사실이 없습니다.")
                    ),
                )
            )
            continue
        sections.append(
            ResearchSection(
                section_id=section.section_id,
                title=section.title,
                status=SectionStatus.BLOCKED,
                required=section.required,
                fact_ids=retained_section_ids,
                data_gaps=_unique((*section.data_gaps, gap)),
                blocking_reasons=_unique(
                    (*section.blocking_reasons, "미래 회사 사실을 제외해 필수 근거가 불완전합니다.")
                ),
            )
        )
    return CompanyResearchResult(
        sources=result.sources,
        facts=retained_facts,
        sections=tuple(sections),
    )


def _build_price_part(
    instrument: InstrumentRef,
    snapshot: EODSnapshot,
    *,
    cutoff: datetime,
    max_age: timedelta,
) -> _CollectedPart:
    mismatch = _snapshot_mismatch(instrument, snapshot)
    if mismatch is not None:
        return _CollectedPart(
            sources=(),
            facts=(),
            sections=(
                ResearchSection(
                    section_id=PRICE_CORE_SECTION_ID,
                    title="가격과 핵심 위험 지표",
                    status=SectionStatus.BLOCKED,
                    blocking_reasons=(mismatch,),
                ),
                _optional_unavailable_section(
                    PRICE_TECHNICAL_SECTION_ID,
                    "선택 기술 지표와 공급원 한계",
                    mismatch,
                ),
            ),
        )

    try:
        observed_at = _snapshot_observed_at(snapshot)
        retrieved_at = _require_aware(snapshot.fetched_at, "가격 수집 시각")
        if observed_at > retrieved_at:
            raise ValueError("가격 관측 시각이 수집 시각보다 늦습니다.")
        source = _price_source(instrument, snapshot, retrieved_at)
    except (TypeError, ValueError) as exc:
        reason = f"가격 스냅샷 시각 또는 출처가 올바르지 않습니다. {exc}"
        return _CollectedPart(
            sources=(),
            facts=(),
            sections=(
                ResearchSection(
                    section_id=PRICE_CORE_SECTION_ID,
                    title="가격과 핵심 위험 지표",
                    status=SectionStatus.BLOCKED,
                    blocking_reasons=(reason,),
                ),
                _optional_unavailable_section(
                    PRICE_TECHNICAL_SECTION_ID,
                    "선택 기술 지표와 공급원 한계",
                    reason,
                ),
            ),
        )

    prefix = f"market.price:{instrument.market.value}:{_symbol_slug(instrument.symbol)}"
    core_specs: tuple[tuple[str, str, FactValue | None, str, str | None], ...] = (
        (
            "current_close",
            "현재 종가",
            snapshot.current_close,
            "currency_per_share",
            instrument.currency,
        ),
        (
            "previous_close",
            "직전 종가",
            snapshot.previous_close,
            "currency_per_share",
            instrument.currency,
        ),
        ("return_1d_pct", "1거래일 수익률", snapshot.return_1d_pct, "percent", None),
        ("atr_14", "ATR14", snapshot.atr_14, "currency_per_share", instrument.currency),
        (
            "volatility_20d_pct",
            "20거래일 연환산 변동성",
            snapshot.volatility_20d_pct,
            "percent",
            None,
        ),
        ("observations", "유효 일봉 수", snapshot.observations, "count", None),
    )
    optional_specs: tuple[tuple[str, str, FactValue | None, str, str | None], ...] = (
        ("return_5d_pct", "5거래일 수익률", snapshot.return_5d_pct, "percent", None),
        ("return_20d_pct", "20거래일 수익률", snapshot.return_20d_pct, "percent", None),
        ("return_60d_pct", "60거래일 수익률", snapshot.return_60d_pct, "percent", None),
        ("sma_20", "20일 단순이동평균", snapshot.sma_20, "currency_per_share", instrument.currency),
        ("sma_50", "50일 단순이동평균", snapshot.sma_50, "currency_per_share", instrument.currency),
        (
            "sma_200",
            "200일 단순이동평균",
            snapshot.sma_200,
            "currency_per_share",
            instrument.currency,
        ),
        ("rsi_14", "RSI14", snapshot.rsi_14, "index_point", None),
        (
            "high_52_week",
            "52주 고가",
            snapshot.high_52_week,
            "currency_per_share",
            instrument.currency,
        ),
        (
            "low_52_week",
            "52주 저가",
            snapshot.low_52_week,
            "currency_per_share",
            instrument.currency,
        ),
        ("average_volume_20d", "20거래일 평균 거래량", snapshot.average_volume_20d, "shares", None),
    )
    core_facts = _price_facts(prefix, source, instrument, observed_at, core_specs)
    optional_facts = _price_facts(prefix, source, instrument, observed_at, optional_specs)

    core_gaps: list[str] = []
    if snapshot.atr_14 is None:
        core_gaps.append("ATR14가 없어 손절 무효화 가격을 계산할 수 없습니다.")
    if snapshot.volatility_20d_pct is None:
        core_gaps.append("20거래일 변동성이 없어 포지션 한도를 계산할 수 없습니다.")
    if snapshot.observations < 21:
        core_gaps.append("핵심 위험 계산에 필요한 유효 일봉 21개를 확보하지 못했습니다.")

    optional_gaps = list(snapshot.data_gaps)
    present_optional_ids = {fact.fact_id.rsplit(":", maxsplit=1)[-1] for fact in optional_facts}
    for key, title, _, _, _ in optional_specs:
        if key not in present_optional_ids:
            optional_gaps.append(f"{title}을 계산할 입력 이력이 부족합니다.")

    core_section = _evidence_section(
        PRICE_CORE_SECTION_ID,
        "가격과 핵심 위험 지표",
        core_facts,
        _unique(core_gaps),
        required=True,
    )
    optional_section = _evidence_section(
        PRICE_TECHNICAL_SECTION_ID,
        "선택 기술 지표와 공급원 한계",
        optional_facts,
        _unique(optional_gaps),
        required=False,
    )
    stale = cutoff - observed_at > max_age
    stale_ids = tuple(fact.fact_id for fact in (*core_facts, *optional_facts)) if stale else ()
    if stale:
        age_days = (cutoff.date() - observed_at.date()).days
        core_section = ResearchSection(
            section_id=PRICE_CORE_SECTION_ID,
            title="가격과 핵심 위험 지표",
            status=SectionStatus.BLOCKED,
            required=True,
            fact_ids=tuple(fact.fact_id for fact in core_facts),
            data_gaps=core_section.data_gaps,
            blocking_reasons=(f"가격 최신 거래일이 {age_days}일 전이라 허용 수명을 초과했습니다.",),
        )
    return _CollectedPart(
        sources=(source,),
        facts=(*core_facts, *optional_facts),
        sections=(core_section, optional_section),
        stale_fact_ids=stale_ids,
    )


def _price_facts(
    prefix: str,
    source: SourceRef,
    instrument: InstrumentRef,
    observed_at: datetime,
    specs: Sequence[tuple[str, str, FactValue | None, str, str | None]],
) -> tuple[Fact, ...]:
    facts: list[Fact] = []
    for key, metric, value, unit, currency in specs:
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, float) and not math.isfinite(value):
            continue
        facts.append(
            Fact(
                fact_id=f"{prefix}:{key}",
                source_id=source.source_id,
                metric=metric,
                value=value,
                unit=unit,
                currency=currency,
                observed_at=observed_at,
                published_at=source.retrieved_at,
                collected_at=source.retrieved_at,
                publication_time_basis=PublicationTimeBasis.RETRIEVAL_TIME_PROXY,
                instrument=instrument,
            )
        )
    return tuple(facts)


def _price_source(
    instrument: InstrumentRef,
    snapshot: EODSnapshot,
    retrieved_at: datetime,
) -> SourceRef:
    parsed = urlparse(snapshot.source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("가격 source_url은 HTTP 또는 HTTPS 주소여야 합니다.")
    host = parsed.hostname.casefold() if parsed.hostname else ""
    official = host.endswith("data.go.kr")
    licensed = host == "api.tiingo.com" or host.endswith(".tiingo.com")
    name = (
        "공공데이터포털 국내 주식 일봉"
        if official
        else "Tiingo 조정 일봉"
        if licensed
        else "시장 일봉 가격 대체 공급원"
    )
    return SourceRef(
        source_id=f"market.price:{instrument.market.value}:{_symbol_slug(instrument.symbol)}",
        name=name,
        tier=(
            SourceTier.OFFICIAL
            if official
            else SourceTier.LICENSED
            if licensed
            else SourceTier.FALLBACK
        ),
        url=AnyHttpUrl(snapshot.source_url),
        retrieved_at=retrieved_at,
    )


def _snapshot_observed_at(snapshot: EODSnapshot) -> datetime:
    for attribute in ("last_trade_at", "last_trade", "as_of"):
        value = getattr(snapshot, attribute, None)
        if value is not None:
            return _coerce_observed_at(value, attribute)
    return datetime.combine(snapshot.as_of_date, datetime.min.time(), tzinfo=UTC)


def _coerce_observed_at(value: object, label: str) -> datetime:
    if isinstance(value, datetime):
        return _require_aware(value, label)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed_datetime = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.combine(date.fromisoformat(value), datetime.min.time(), tzinfo=UTC)
            except ValueError as exc:
                raise ValueError(f"{label}을 ISO 날짜 또는 시각으로 해석할 수 없습니다.") from exc
        return _require_aware(parsed_datetime, label)
    raise TypeError(f"{label}은 날짜 또는 시간대가 있는 시각이어야 합니다.")


def _snapshot_mismatch(instrument: InstrumentRef, snapshot: EODSnapshot) -> str | None:
    requested = instrument.symbol.upper().replace("-", ".")
    received = snapshot.ticker.upper().replace("-", ".")
    if requested != received:
        return f"가격 종목이 요청과 다릅니다. {received} != {requested}."
    if snapshot.currency.upper() != instrument.currency:
        return f"가격 통화가 요청과 다릅니다. {snapshot.currency} != {instrument.currency}."
    return None


def _macro_part(
    result: MacroContextResult,
    market: MarketId,
) -> _CollectedPart:
    required_section_ids: list[str] = list(COMMON_REQUIRED_MACRO_SECTION_IDS)
    if market is MarketId.KR:
        required_section_ids.append(KR_REQUIRED_MACRO_SECTION_ID)
    existing_section_ids = {section.section_id for section in result.sections}
    missing_required = tuple(
        section_id
        for section_id in required_section_ids
        if section_id not in existing_section_ids
    )
    sections = tuple(
        section.model_copy(update={"required": True})
        if section.section_id in required_section_ids and not section.required
        else section
        for section in result.sections
    )
    return _CollectedPart(
        sources=result.sources,
        facts=result.facts,
        sections=sections,
        stale_fact_ids=result.stale_fact_ids,
        missing_required_sections=_unique(
            (*result.future_section_ids, *missing_required)
        ),
    )


def _company_part(
    result: CompanyResearchResult,
    *,
    cutoff: datetime,
    fundamental_max_age: timedelta,
    disclosure_max_age: timedelta,
) -> _CollectedPart:
    required_section_ids = (FUNDAMENTAL_SECTION_ID, OFFICIAL_NEWS_SECTION_ID)
    existing_section_ids = {section.section_id for section in result.sections}
    missing_required = tuple(
        section_id for section_id in required_section_ids if section_id not in existing_section_ids
    )
    fact_by_id = {fact.fact_id: fact for fact in result.facts}
    stale_fact_ids: list[str] = []
    sections: list[ResearchSection] = []

    for section in result.sections:
        required = section.required or section.section_id in required_section_ids
        section_facts = tuple(
            fact_by_id[fact_id] for fact_id in section.fact_ids if fact_id in fact_by_id
        )
        status = section.status
        data_gaps = list(section.data_gaps)
        blocking_reasons = list(section.blocking_reasons)

        metadata_only = (
            section.section_id == OFFICIAL_NEWS_SECTION_ID
            and len(section_facts) == len(section.fact_ids)
            and bool(section_facts)
            and all(fact.unit in OFFICIAL_DISCLOSURE_METADATA_UNITS for fact in section_facts)
        )
        if metadata_only:
            if status is SectionStatus.COMPLETE:
                status = SectionStatus.PARTIAL
            data_gaps.append(OFFICIAL_DISCLOSURE_METADATA_GAP)
            blocking_reasons.append(
                "공시 메타데이터만으로 공식 뉴스 근거가 충족되었다고 판단할 수 없습니다."
            )

        max_age = (
            fundamental_max_age
            if section.section_id == FUNDAMENTAL_SECTION_ID
            else disclosure_max_age
            if section.section_id == OFFICIAL_NEWS_SECTION_ID
            else None
        )
        section_stale_ids = tuple(
            fact.fact_id
            for fact in section_facts
            if max_age is not None
            and (
                cutoff - fact.observed_at > max_age
                or cutoff - fact.published_at > max_age
            )
        )
        if section_stale_ids:
            assert max_age is not None
            stale_fact_ids.extend(section_stale_ids)
            status = SectionStatus.BLOCKED
            blocking_reasons.append(
                f"{section.title} 사실이 허용 수명 {max_age.days}일을 넘어 "
                "현재 투자 판단에 사용할 수 없습니다."
            )

        sections.append(
            ResearchSection(
                section_id=section.section_id,
                title=section.title,
                status=status,
                required=required,
                fact_ids=section.fact_ids,
                data_gaps=_unique(data_gaps),
                blocking_reasons=_unique(blocking_reasons),
            )
        )

    return _CollectedPart(
        sources=result.sources,
        facts=result.facts,
        sections=tuple(sections),
        stale_fact_ids=_unique(stale_fact_ids),
        missing_required_sections=missing_required,
    )


def _build_valuation_part(
    instrument: InstrumentRef,
    snapshot: EODSnapshot,
    company_part: _CollectedPart,
) -> _CollectedPart:
    input_aliases = {
        "shares_outstanding": ("발행주식수",),
        "ttm_net_income": ("TTM 순이익", "최근 공시 기준 순이익"),
        "average_equity": ("평균자본", "최근 공시 기준 자본"),
        "average_assets": ("평균자산", "최근 공시 기준 자산"),
        "book_equity": ("장부자본", "최근 공시 기준 자본"),
    }
    inputs = {
        input_name: _valuation_input(
            company_part.facts,
            aliases,
            excluded_fact_ids=company_part.stale_fact_ids,
        )
        for input_name, aliases in input_aliases.items()
    }
    metrics = calculate_valuation_metrics(
        price=snapshot.current_close,
        shares_outstanding=inputs["shares_outstanding"].value,
        ttm_net_income=inputs["ttm_net_income"].value,
        average_equity=inputs["average_equity"].value,
        average_assets=inputs["average_assets"].value,
        book_equity=inputs["book_equity"].value,
    )
    metric_specs = (
        ("per", "PER", metrics.per, ("shares_outstanding", "ttm_net_income"), "ratio"),
        ("roe", "ROE", metrics.roe_pct, ("ttm_net_income", "average_equity"), "percent"),
        ("roa", "ROA", metrics.roa_pct, ("ttm_net_income", "average_assets"), "percent"),
        ("pbr", "PBR", metrics.pbr, ("shares_outstanding", "book_equity"), "ratio"),
    )
    facts: list[Fact] = []
    gaps = list(metrics.data_gaps)
    for key, metric, value, required_inputs, unit in metric_specs:
        if value is None:
            continue
        if metric in {"ROE", "ROA"} and any(
            inputs[input_name].is_proxy for input_name in required_inputs
        ):
            gaps.append(
                f"{metric}는 TTM·평균잔액 입력 대신 최근 공시 순이익과 "
                "기말잔액을 사용한 참고 비율입니다."
            )
        lineage = tuple(
            item.fact
            for input_name in required_inputs
            if (item := inputs[input_name]).fact is not None
        )
        source_ids = {fact.source_id for fact in lineage}
        uses_price = key in {"per", "pbr"}
        if uses_price or len(lineage) != len(required_inputs) or len(source_ids) != 1:
            gaps.append(f"{metric} 입력의 다중 원천 계보를 현재 사실 계약으로 표현할 수 없습니다.")
            continue
        source_id = next(iter(source_ids))
        facts.append(
            Fact(
                fact_id=(
                    f"company.valuation:{instrument.market.value}:"
                    f"{_symbol_slug(instrument.symbol)}:{key}"
                ),
                source_id=source_id,
                metric=metric,
                value=round(value, 6),
                unit=unit,
                observed_at=max(fact.observed_at for fact in lineage),
                published_at=max(fact.published_at for fact in lineage),
                collected_at=max(fact.collected_at for fact in lineage),
                instrument=instrument,
            )
        )
    section = _evidence_section(
        VALUATION_SECTION_ID,
        "검증 가능한 밸류에이션 비율",
        tuple(facts),
        _unique(gaps),
        required=False,
    )
    return _CollectedPart((), tuple(facts), (section,))


def _valuation_input(
    facts: Sequence[Fact],
    metrics: Sequence[str],
    *,
    excluded_fact_ids: Sequence[str] = (),
) -> _ValuationInput:
    excluded = set(excluded_fact_ids)
    for index, metric in enumerate(metrics):
        matches = [fact for fact in facts if fact.metric == metric and fact.fact_id not in excluded]
        if not matches:
            continue
        fact = max(matches, key=lambda item: (item.observed_at, item.published_at, item.revision))
        value = fact.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return _ValuationInput(None, fact, index > 0)
        numeric = float(value)
        return _ValuationInput(
            numeric if math.isfinite(numeric) else None,
            fact,
            index > 0,
        )
    return _ValuationInput(None, None)


def _independent_news_part() -> _CollectedPart:
    return _CollectedPart(
        sources=(),
        facts=(),
        sections=(
            _optional_unavailable_section(
                INDEPENDENT_NEWS_SECTION_ID,
                "독립 언론 뉴스",
                "검증 가능한 독립 언론 뉴스 공급원이 아직 연결되지 않았습니다.",
                required=True,
            ),
        ),
    )


def _merge_research(
    parts: Sequence[_CollectedPart],
    instrument: InstrumentRef,
    cutoff: datetime,
) -> _MergedResearch:
    integrity: list[str] = []
    sources = _deduplicate_models(
        (source for part in parts for source in part.sources),
        "source_id",
        "출처",
        integrity,
    )
    source_by_id = {source.source_id: source for source in sources}

    raw_facts = _deduplicate_models(
        (fact for part in parts for fact in part.facts),
        "fact_id",
        "사실",
        integrity,
    )
    facts: list[Fact] = []
    for fact in raw_facts:
        source = source_by_id.get(fact.source_id)
        if source is None:
            integrity.append(f"사실 {fact.fact_id}가 존재하지 않는 출처를 참조합니다.")
            continue
        if fact.collected_at < source.retrieved_at or fact.collected_at > cutoff:
            integrity.append(f"사실 {fact.fact_id}의 수집 시각이 번들 경계와 맞지 않습니다.")
            continue
        if fact.instrument is not None and fact.instrument != instrument:
            integrity.append(f"사실 {fact.fact_id}의 종목 식별자가 요청 종목과 다릅니다.")
            continue
        facts.append(fact)
    fact_ids = {fact.fact_id for fact in facts}

    raw_sections = _deduplicate_models(
        (section for part in parts for section in part.sections),
        "section_id",
        "구역",
        integrity,
    )
    sections: list[ResearchSection] = []
    for section in raw_sections:
        unknown = tuple(fact_id for fact_id in section.fact_ids if fact_id not in fact_ids)
        if not unknown:
            sections.append(section)
            continue
        integrity.append(
            f"구역 {section.section_id}가 제거된 사실을 참조합니다. {', '.join(unknown)}."
        )
        known = tuple(fact_id for fact_id in section.fact_ids if fact_id in fact_ids)
        sections.append(
            ResearchSection(
                section_id=section.section_id,
                title=section.title,
                status=SectionStatus.BLOCKED,
                required=section.required,
                fact_ids=known,
                data_gaps=section.data_gaps,
                blocking_reasons=_unique(
                    (*section.blocking_reasons, "참조 무결성 검증에 실패했습니다.")
                ),
            )
        )
    if integrity:
        section_id = INTEGRITY_SECTION_ID
        existing_ids = {section.section_id for section in sections}
        suffix = 2
        while section_id in existing_ids:
            section_id = f"{INTEGRITY_SECTION_ID}.{suffix}"
            suffix += 1
        sections.append(
            ResearchSection(
                section_id=section_id,
                title="연구 번들 참조 무결성",
                status=SectionStatus.BLOCKED,
                required=True,
                blocking_reasons=_unique(integrity),
            )
        )
    return _MergedResearch(tuple(sources), tuple(facts), tuple(sections), _unique(integrity))


def _deduplicate_models[T](
    values: Iterable[T],
    identifier_field: str,
    label: str,
    integrity: list[str],
) -> list[T]:
    resolved: dict[str, T] = {}
    for value in values:
        identifier = getattr(value, identifier_field)
        existing = resolved.get(identifier)
        if existing is None:
            resolved[identifier] = value
        elif existing != value:
            integrity.append(f"{label} 식별자 {identifier}가 서로 다른 값으로 중복되었습니다.")
    return list(resolved.values())


def _build_quality(
    sections: Sequence[ResearchSection],
    *,
    stale_fact_ids: tuple[str, ...],
    missing_required_sections: tuple[str, ...],
    generated_at: datetime,
) -> DataQualityReport:
    blocked_sections = tuple(
        section.section_id
        for section in sections
        if section.required and section.status is not SectionStatus.COMPLETE
    )
    reasons: list[str] = []
    warnings: list[str] = []
    for section in sections:
        if section.required and section.status is not SectionStatus.COMPLETE:
            if section.blocking_reasons:
                reasons.extend(section.blocking_reasons)
            else:
                reasons.append(f"필수 구역 {section.title}이 완전하지 않습니다.")
            warnings.extend(section.data_gaps)
        elif section.status is not SectionStatus.COMPLETE:
            warnings.extend(section.data_gaps or section.blocking_reasons)
    if stale_fact_ids:
        reasons.append("허용 수명을 넘은 사실이 있어 신규 투자 판단을 차단합니다.")
    if missing_required_sections:
        reasons.append(
            "아직 수집하지 못한 필수 연구 구역이 있습니다. "
            + ", ".join(missing_required_sections)
            + "."
        )
    eligible = not blocked_sections and not stale_fact_ids and not missing_required_sections
    if not eligible and not reasons:
        reasons.append("필수 연구 자료 품질 조건을 충족하지 못했습니다.")
    return DataQualityReport(
        generated_at=generated_at,
        analysis_eligible=eligible,
        blocking_reasons=_unique(reasons),
        warnings=_unique(warnings),
        stale_fact_ids=stale_fact_ids,
        blocked_fact_ids=stale_fact_ids,
        blocked_section_ids=blocked_sections,
        missing_required_sections=missing_required_sections,
    )


def _evaluate_regime(
    evaluator: RegimeEvaluator | MarketRegimeEvaluator,
    market: MarketId,
    facts: Sequence[Fact],
) -> MarketRegimeAssessment:
    try:
        return evaluator.evaluate(market=market, facts=facts)
    except Exception as exc:
        reason = _failure_reason("시장 국면 평가", exc)
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
            warnings=(reason,),
            position_cap_multiplier=0.25,
        )


def _agent_facts(
    sections: Sequence[ResearchSection],
    fact_by_id: Mapping[str, Fact],
    source_by_id: Mapping[str, SourceRef],
    section_ids: set[str],
    *,
    excluded_units: frozenset[str] = frozenset(),
) -> list[dict[str, object]]:
    selected_ids = _unique(
        fact_id
        for section in sections
        if section.section_id in section_ids
        for fact_id in section.fact_ids
    )
    output: list[dict[str, object]] = []
    for fact_id in selected_ids:
        fact = fact_by_id.get(fact_id)
        if fact is None or fact.unit in excluded_units:
            continue
        source = source_by_id[fact.source_id]
        payload = fact.model_dump(mode="json")
        payload["source_name"] = source.name
        payload["source_url"] = str(source.url)
        output.append(payload)
    return output


def _evidence_section(
    section_id: str,
    title: str,
    facts: tuple[Fact, ...],
    gaps: tuple[str, ...],
    *,
    required: bool,
) -> ResearchSection:
    fact_ids = tuple(fact.fact_id for fact in facts)
    if fact_ids and gaps:
        return ResearchSection(
            section_id=section_id,
            title=title,
            status=SectionStatus.PARTIAL,
            required=required,
            fact_ids=fact_ids,
            data_gaps=gaps,
        )
    if fact_ids:
        return ResearchSection(
            section_id=section_id,
            title=title,
            status=SectionStatus.COMPLETE,
            required=required,
            fact_ids=fact_ids,
        )
    return _optional_unavailable_section(
        section_id,
        title,
        gaps[0] if gaps else "사용할 수 있는 사실을 확보하지 못했습니다.",
        required=required,
        additional_reasons=gaps[1:],
    )


def _optional_unavailable_section(
    section_id: str,
    title: str,
    reason: str,
    *,
    required: bool = False,
    additional_reasons: tuple[str, ...] = (),
) -> ResearchSection:
    return ResearchSection(
        section_id=section_id,
        title=title,
        status=SectionStatus.UNAVAILABLE,
        required=required,
        blocking_reasons=_unique((reason, *additional_reasons)),
    )


def _failure_reason(label: str, exc: Exception) -> str:
    return f"{label} 수집 또는 변환이 실패했습니다. {type(exc).__name__}."


def _symbol_slug(symbol: str) -> str:
    return symbol.casefold().replace("-", ".")


def _require_aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label}에는 시간대 정보가 필요합니다.")
    return value.astimezone(UTC)


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))
