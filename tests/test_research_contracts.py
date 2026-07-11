# 미국과 한국 시장 연구 데이터 계약의 검증 규칙을 시험한다
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from investment_office.services.research_contracts import (
    AnalysisInputBundle,
    DataQualityReport,
    Fact,
    InstrumentRef,
    MarketId,
    ResearchSection,
    SectionStatus,
    SourceRef,
    SourceTier,
)

OBSERVED_AT = datetime(2026, 1, 2, 21, 0, tzinfo=UTC)
PUBLISHED_AT = OBSERVED_AT + timedelta(seconds=1)
RETRIEVED_AT = PUBLISHED_AT + timedelta(seconds=1)
COLLECTED_AT = RETRIEVED_AT + timedelta(seconds=1)
GENERATED_AT = COLLECTED_AT + timedelta(seconds=1)
CUTOFF = GENERATED_AT + timedelta(seconds=1)


def _instrument(**overrides: object) -> InstrumentRef:
    values: dict[str, object] = {
        "market": MarketId.US,
        "symbol": "AAPL",
        "name": "Apple",
        "exchange": "NASDAQ",
        "currency": "USD",
    }
    values.update(overrides)
    return InstrumentRef.model_validate(values)


def _source(**overrides: object) -> SourceRef:
    values: dict[str, object] = {
        "source_id": "official:prices",
        "name": "공식 가격 자료",
        "tier": SourceTier.OFFICIAL,
        "url": "https://example.com/prices/aapl",
        "retrieved_at": RETRIEVED_AT,
        "content_checksum": "a" * 64,
    }
    values.update(overrides)
    return SourceRef.model_validate(values)


def _fact(**overrides: object) -> Fact:
    values: dict[str, object] = {
        "fact_id": "price:close",
        "source_id": "official:prices",
        "metric": "종가",
        "value": 210.5,
        "unit": "price",
        "currency": "usd",
        "observed_at": OBSERVED_AT,
        "published_at": PUBLISHED_AT,
        "collected_at": COLLECTED_AT,
        "instrument": _instrument(),
    }
    values.update(overrides)
    return Fact.model_validate(values)


def _section(**overrides: object) -> ResearchSection:
    values: dict[str, object] = {
        "section_id": "market.price",
        "title": "시장 가격",
        "status": SectionStatus.COMPLETE,
        "fact_ids": ("price:close",),
    }
    values.update(overrides)
    return ResearchSection.model_validate(values)


def _quality(**overrides: object) -> DataQualityReport:
    values: dict[str, object] = {
        "generated_at": GENERATED_AT,
        "analysis_eligible": True,
    }
    values.update(overrides)
    return DataQualityReport.model_validate(values)


def _bundle(**overrides: object) -> AnalysisInputBundle:
    values: dict[str, object] = {
        "schema_version": "1.0",
        "cutoff": CUTOFF,
        "market_session": date(2026, 1, 2),
        "instrument": _instrument(),
        "sources": (_source(),),
        "facts": (_fact(),),
        "sections": (_section(),),
        "quality": _quality(),
    }
    values.update(overrides)
    return AnalysisInputBundle.model_validate(values)


def test_valid_bundle_round_trips_without_losing_contract_types() -> None:
    bundle = _bundle()

    restored = AnalysisInputBundle.model_validate_json(bundle.model_dump_json())

    assert restored == bundle
    assert restored.facts[0].currency == "USD"
    assert restored.instrument.market is MarketId.US


def test_market_specific_symbols_and_currencies_are_normalized() -> None:
    us = _instrument(symbol=" brk.b ", currency="usd")
    kr = _instrument(
        market=MarketId.KR,
        symbol="005930",
        name="삼성전자",
        exchange="KRX",
        currency="krw",
    )

    assert us.symbol == "BRK.B"
    assert us.currency == "USD"
    assert kr.symbol == "005930"
    assert kr.currency == "KRW"


@pytest.mark.parametrize(
    ("market", "symbol", "currency"),
    [
        (MarketId.US, "005930", "USD"),
        (MarketId.US, "AAPL", "KRW"),
        (MarketId.KR, "5930", "KRW"),
        (MarketId.KR, "005930", "USD"),
    ],
)
def test_market_specific_symbol_or_currency_mismatch_is_rejected(
    market: MarketId,
    symbol: str,
    currency: str,
) -> None:
    with pytest.raises(ValidationError):
        _instrument(market=market, symbol=symbol, currency=currency)


def test_fact_rejects_impossible_timestamp_order() -> None:
    with pytest.raises(ValidationError, match="published_at"):
        _fact(published_at=OBSERVED_AT - timedelta(seconds=1))

    with pytest.raises(ValidationError, match="collected_at"):
        _fact(collected_at=PUBLISHED_AT - timedelta(seconds=1))


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": SectionStatus.COMPLETE, "fact_ids": ()},
        {"status": SectionStatus.PARTIAL, "data_gaps": ()},
        {
            "status": SectionStatus.UNAVAILABLE,
            "fact_ids": ("price:close",),
            "blocking_reasons": ("수집 실패",),
        },
        {"status": SectionStatus.BLOCKED, "blocking_reasons": ()},
    ],
)
def test_section_status_requires_consistent_evidence(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _section(**overrides)


def test_bundle_rejects_unknown_source_and_fact_references() -> None:
    with pytest.raises(ValidationError, match="알 수 없는 출처"):
        _bundle(facts=(_fact(source_id="unknown:source"),))

    with pytest.raises(ValidationError, match="알 수 없는 사실"):
        _bundle(sections=(_section(fact_ids=("unknown:fact",)),))


def test_bundle_rejects_unknown_quality_references() -> None:
    quality = _quality(stale_fact_ids=("unknown:fact",))

    with pytest.raises(ValidationError, match="stale_fact_ids"):
        _bundle(quality=quality)


def test_bundle_blocks_future_information() -> None:
    future_source = _source(retrieved_at=CUTOFF + timedelta(seconds=1))

    with pytest.raises(ValidationError, match="cutoff"):
        _bundle(sources=(future_source,))

    with pytest.raises(ValidationError, match="market_session"):
        _bundle(market_session=date(2026, 1, 3))


def test_required_incomplete_section_must_be_reported_as_blocked() -> None:
    section = _section(
        status=SectionStatus.PARTIAL,
        data_gaps=("거래량 누락",),
    )
    quality = _quality(
        analysis_eligible=False,
        blocking_reasons=("필수 가격 자료가 불완전합니다.",),
    )

    with pytest.raises(ValidationError, match="필수 미완료 구역"):
        _bundle(sections=(section,), quality=quality)

    blocked = quality.model_copy(update={"blocked_section_ids": ("market.price",)})
    bundle = _bundle(sections=(section,), quality=blocked)
    assert bundle.quality.analysis_eligible is False


def test_contracts_reject_extra_fields_and_duplicate_identifiers() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        InstrumentRef.model_validate(
            {
                "market": MarketId.US,
                "symbol": "AAPL",
                "exchange": "NASDAQ",
                "currency": "USD",
                "unexpected": True,
            }
        )

    with pytest.raises(ValidationError, match="중복 식별자"):
        _bundle(sources=(_source(), _source()))
