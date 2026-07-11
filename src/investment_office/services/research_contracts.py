# 미국과 한국 시장 연구 입력의 출처, 사실, 품질 계약을 정의한다
from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    AnyHttpUrl,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]
FactValue = str | int | float | bool

US_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")
KR_SYMBOL_PATTERN = re.compile(r"^\d{6}$")


class ResearchContract(BaseModel):
    """알 수 없는 필드를 거부하는 불변 연구 데이터 계약."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class MarketId(StrEnum):
    US = "us"
    KR = "kr"


class InstrumentRef(ResearchContract):
    market: MarketId
    symbol: str = Field(min_length=1, max_length=15)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    exchange: str = Field(min_length=1, max_length=40)
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")

    @field_validator("symbol", "currency", mode="before")
    @classmethod
    def normalize_codes(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @model_validator(mode="after")
    def validate_market_codes(self) -> Self:
        expected_currency = "USD" if self.market is MarketId.US else "KRW"
        if self.currency != expected_currency:
            raise ValueError(f"{self.market.value} 시장 통화는 {expected_currency}여야 합니다.")
        if self.market is MarketId.US and US_SYMBOL_PATTERN.fullmatch(self.symbol) is None:
            raise ValueError("미국 종목 심볼 형식이 올바르지 않습니다.")
        if self.market is MarketId.KR and KR_SYMBOL_PATTERN.fullmatch(self.symbol) is None:
            raise ValueError("한국 종목 심볼은 숫자 여섯 자리여야 합니다.")
        return self


class SourceTier(StrEnum):
    OFFICIAL = "official"
    LICENSED = "licensed"
    SECONDARY = "secondary"
    FALLBACK = "fallback"


class SourceRef(ResearchContract):
    source_id: Identifier
    name: str = Field(min_length=1, max_length=200)
    tier: SourceTier
    url: AnyHttpUrl
    retrieved_at: AwareDatetime
    content_checksum: str | None = Field(default=None, min_length=1, max_length=128)


class Fact(ResearchContract):
    fact_id: Identifier
    source_id: Identifier
    metric: str = Field(min_length=1, max_length=160)
    value: FactValue
    unit: str = Field(min_length=1, max_length=40)
    currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    )
    observed_at: AwareDatetime
    published_at: AwareDatetime
    collected_at: AwareDatetime
    instrument: InstrumentRef | None = None
    revision: int = Field(default=0, ge=0)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        if self.published_at < self.observed_at:
            raise ValueError("published_at은 observed_at보다 빠를 수 없습니다.")
        if self.collected_at < self.published_at:
            raise ValueError("collected_at은 published_at보다 빠를 수 없습니다.")
        return self


class SectionStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"


class ResearchSection(ResearchContract):
    section_id: Identifier
    title: str = Field(min_length=1, max_length=160)
    status: SectionStatus
    required: bool = True
    fact_ids: tuple[Identifier, ...] = ()
    data_gaps: tuple[str, ...] = ()
    blocking_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        _require_unique(self.fact_ids, "fact_ids")
        _require_unique(self.data_gaps, "data_gaps")
        _require_unique(self.blocking_reasons, "blocking_reasons")
        if self.status is SectionStatus.COMPLETE:
            if not self.fact_ids:
                raise ValueError("완료된 연구 구역에는 하나 이상의 사실이 필요합니다.")
            if self.blocking_reasons:
                raise ValueError("완료된 연구 구역에는 차단 사유가 있을 수 없습니다.")
        elif self.status is SectionStatus.PARTIAL:
            if not self.fact_ids or not self.data_gaps:
                raise ValueError("부분 완료 구역에는 사실과 데이터 공백이 모두 필요합니다.")
        elif self.status is SectionStatus.UNAVAILABLE:
            if self.fact_ids:
                raise ValueError("사용 불가 구역은 사실을 참조할 수 없습니다.")
            if not self.blocking_reasons:
                raise ValueError("사용 불가 구역에는 차단 사유가 필요합니다.")
        elif not self.blocking_reasons:
            raise ValueError("차단된 구역에는 차단 사유가 필요합니다.")
        return self


class DataQualityReport(ResearchContract):
    generated_at: AwareDatetime
    analysis_eligible: bool
    blocking_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    stale_fact_ids: tuple[Identifier, ...] = ()
    blocked_fact_ids: tuple[Identifier, ...] = ()
    blocked_section_ids: tuple[Identifier, ...] = ()
    missing_required_sections: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def validate_eligibility(self) -> Self:
        for field_name in (
            "blocking_reasons",
            "warnings",
            "stale_fact_ids",
            "blocked_fact_ids",
            "blocked_section_ids",
            "missing_required_sections",
        ):
            _require_unique(getattr(self, field_name), field_name)
        has_block = bool(
            self.blocking_reasons
            or self.blocked_fact_ids
            or self.blocked_section_ids
            or self.missing_required_sections
        )
        if self.analysis_eligible and has_block:
            raise ValueError("분석 가능 품질 보고서에는 차단 항목이 있을 수 없습니다.")
        if not self.analysis_eligible and not self.blocking_reasons:
            raise ValueError("분석 불가 품질 보고서에는 차단 사유가 필요합니다.")
        return self


class AnalysisInputBundle(ResearchContract):
    schema_version: str = Field(default="1.0", pattern=r"^\d+\.\d+$")
    cutoff: AwareDatetime
    market_session: date
    instrument: InstrumentRef
    sources: tuple[SourceRef, ...] = ()
    facts: tuple[Fact, ...] = ()
    sections: tuple[ResearchSection, ...] = Field(min_length=1)
    quality: DataQualityReport

    @model_validator(mode="after")
    def validate_references_and_cutoff(self) -> Self:
        if self.market_session > self.cutoff.date():
            raise ValueError("market_session은 cutoff 날짜보다 늦을 수 없습니다.")

        source_by_id = _unique_by_id(self.sources, "source_id", "sources")
        fact_by_id = _unique_by_id(self.facts, "fact_id", "facts")
        section_by_id = _unique_by_id(self.sections, "section_id", "sections")

        for source in self.sources:
            if source.retrieved_at > self.cutoff:
                raise ValueError(f"출처 {source.source_id}의 수집 시각이 cutoff보다 늦습니다.")
        for fact in self.facts:
            referenced_source = source_by_id.get(fact.source_id)
            if referenced_source is None:
                raise ValueError(f"사실 {fact.fact_id}가 알 수 없는 출처를 참조합니다.")
            if fact.collected_at < referenced_source.retrieved_at:
                raise ValueError(f"사실 {fact.fact_id}의 수집 시각이 출처 조회보다 빠릅니다.")
            if fact.collected_at > self.cutoff:
                raise ValueError(f"사실 {fact.fact_id}의 수집 시각이 cutoff보다 늦습니다.")

        for section in self.sections:
            unknown_fact_ids = set(section.fact_ids) - fact_by_id.keys()
            if unknown_fact_ids:
                unknown = ", ".join(sorted(unknown_fact_ids))
                raise ValueError(
                    f"구역 {section.section_id}가 알 수 없는 사실을 참조합니다. {unknown}"
                )

        _require_known_refs(self.quality.stale_fact_ids, fact_by_id, "stale_fact_ids")
        _require_known_refs(self.quality.blocked_fact_ids, fact_by_id, "blocked_fact_ids")
        _require_known_refs(
            self.quality.blocked_section_ids,
            section_by_id,
            "blocked_section_ids",
        )
        existing_missing_sections = (
            set(self.quality.missing_required_sections) & section_by_id.keys()
        )
        if existing_missing_sections:
            existing = ", ".join(sorted(existing_missing_sections))
            raise ValueError(f"누락 구역 목록에 이미 존재하는 구역이 있습니다. {existing}")

        required_incomplete = {
            section.section_id
            for section in self.sections
            if section.required and section.status is not SectionStatus.COMPLETE
        }
        unreported = required_incomplete - set(self.quality.blocked_section_ids)
        if unreported:
            missing = ", ".join(sorted(unreported))
            raise ValueError(f"필수 미완료 구역이 품질 보고서에 없습니다. {missing}")
        if self.quality.generated_at > self.cutoff:
            raise ValueError("품질 보고서 생성 시각이 cutoff보다 늦습니다.")
        return self


def _require_unique(values: tuple[str, ...], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name}에는 중복 값이 있을 수 없습니다.")
    if any(not value.strip() for value in values):
        raise ValueError(f"{field_name}에는 빈 문자열이 있을 수 없습니다.")


def _unique_by_id[ModelT: ResearchContract](
    values: tuple[ModelT, ...],
    field_name: str,
    collection_name: str,
) -> dict[str, ModelT]:
    resolved: dict[str, ModelT] = {}
    for value in values:
        identifier = getattr(value, field_name)
        if identifier in resolved:
            raise ValueError(f"{collection_name}에 중복 식별자 {identifier}가 있습니다.")
        resolved[identifier] = value
    return resolved


def _require_known_refs[ModelT: ResearchContract](
    references: tuple[str, ...],
    known: dict[str, ModelT],
    field_name: str,
) -> None:
    unknown = set(references) - known.keys()
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise ValueError(f"{field_name}가 알 수 없는 식별자를 참조합니다. {joined}")
