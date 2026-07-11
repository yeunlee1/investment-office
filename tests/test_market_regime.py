# 거시 사실의 축별 국면 분류와 보수적 노출 상한을 시험한다
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from investment_office.services.market_regime import (
    MarketRegimeEvaluator,
    MarketRegimePolicy,
    RegimeState,
)
from investment_office.services.research_contracts import Fact, MarketId

OBSERVED_AT = datetime(2026, 7, 10, tzinfo=UTC)
PUBLISHED_AT = OBSERVED_AT + timedelta(hours=1)
COLLECTED_AT = PUBLISHED_AT + timedelta(minutes=1)

SIGNALS = {
    "treasury_2y": ("미국 국채 2년물 금리", "percent", 4.0),
    "treasury_3y": ("미국 국채 3년물 금리", "percent", 4.1),
    "treasury_10y": ("미국 국채 10년물 금리", "percent", 4.8),
    "treasury_10y_change": (
        "미국 국채 10년물 금리 30일 변화",
        "percentage_point",
        -0.1,
    ),
    "curve_10y2y": (
        "미국 국채 10년물과 2년물 금리차",
        "percentage_point",
        0.8,
    ),
    "broad_dollar_level": ("미 연준 광의 달러지수", "index_point", 115.0),
    "broad_dollar_change": ("미 연준 광의 달러지수 30일 변화", "percent", -2.0),
    "usdk_rw_level": ("원·달러 환율", "krw_per_usd", 1300.0),
    "usdk_rw_change": ("원·달러 환율 30일 변화", "percent", -2.0),
    "vix_level": ("VIX 종가", "index_point", 15.0),
    "vix_change": ("VIX 종가 30일 변화", "percent", -10.0),
    "wti_level": ("WTI 현물 가격", "usd_per_barrel", 70.0),
    "wti_change": ("WTI 현물 가격 30일 변화", "percent", 2.0),
    "brent_level": ("브렌트유 현물 가격", "usd_per_barrel", 75.0),
    "brent_change": ("브렌트유 현물 가격 30일 변화", "percent", 2.0),
    "bitcoin_level": ("비트코인 미국 달러 가격", "usd_per_bitcoin", 60_000.0),
    "bitcoin_change": ("비트코인 미국 달러 가격 30일 변화", "percent", 15.0),
}


def _facts(**overrides: float | str) -> tuple[Fact, ...]:
    facts: list[Fact] = []
    for name, (metric, unit, default_value) in SIGNALS.items():
        value = overrides.get(name, default_value)
        if value == "missing":
            continue
        facts.append(
            Fact(
                fact_id=f"test:macro:{name}",
                source_id="official:test:macro",
                metric=metric,
                value=value,
                unit=unit,
                observed_at=OBSERVED_AT,
                published_at=PUBLISHED_AT,
                collected_at=COLLECTED_AT,
            )
        )
    return tuple(facts)


@pytest.mark.parametrize("market", [MarketId.US, MarketId.KR])
def test_favorable_axes_remain_separate_without_a_buy_score(market: MarketId) -> None:
    result = MarketRegimeEvaluator().evaluate(market=market, facts=_facts())

    assert result.regime.rates is RegimeState.FAVORABLE
    assert result.regime.currency is RegimeState.FAVORABLE
    assert result.regime.volatility is RegimeState.FAVORABLE
    assert result.regime.commodities is RegimeState.FAVORABLE
    assert result.regime.liquidity is RegimeState.FAVORABLE
    assert result.confidence == 1
    assert result.position_cap_multiplier == 1
    assert not hasattr(result, "recommendation")
    assert not hasattr(result, "score")


def test_korean_market_applies_usdkrw_sensitivity_separately() -> None:
    facts = _facts(broad_dollar_change=-1.5, usdk_rw_change=3.0)
    evaluator = MarketRegimeEvaluator()

    us_result = evaluator.evaluate(market=MarketId.US, facts=facts)
    kr_result = evaluator.evaluate(market=MarketId.KR, facts=facts)

    assert us_result.regime.currency is RegimeState.FAVORABLE
    assert kr_result.regime.currency is RegimeState.ADVERSE
    assert kr_result.position_cap_multiplier == 0.5
    assert "test:macro:usdk_rw_change" not in us_result.evidence_fact_ids
    assert "test:macro:usdk_rw_change" in kr_result.evidence_fact_ids
    assert any("원화 약세" in warning for warning in kr_result.warnings)


def test_missing_required_axis_is_unknown_and_reduces_cap() -> None:
    result = MarketRegimeEvaluator().evaluate(
        market=MarketId.US,
        facts=_facts(brent_change="missing"),
    )

    assert result.regime.commodities is RegimeState.UNKNOWN
    assert result.regime.rates is RegimeState.FAVORABLE
    assert result.confidence == 0.8
    assert result.position_cap_multiplier == 0.5
    assert "test:macro:wti_level" in result.evidence_fact_ids
    assert any("브렌트유 현물 가격 30일 변화" in warning for warning in result.warnings)
    assert any("원자재" in warning for warning in result.warnings)


def test_vix_crisis_and_curve_inversion_apply_the_strictest_cap() -> None:
    result = MarketRegimeEvaluator().evaluate(
        market=MarketId.US,
        facts=_facts(
            treasury_2y=5.0,
            treasury_3y=4.8,
            treasury_10y=4.0,
            curve_10y2y=-1.0,
            vix_level=42.0,
            vix_change=50.0,
        ),
    )

    assert result.regime.rates is RegimeState.ADVERSE
    assert result.regime.volatility is RegimeState.ADVERSE
    assert result.position_cap_multiplier == 0.25
    assert any("금리 역전" in warning for warning in result.warnings)
    assert any("VIX 위기" in warning for warning in result.warnings)
    assert any("VIX 급등" in warning for warning in result.warnings)


def test_missing_explicit_curve_uses_two_and_ten_year_levels() -> None:
    result = MarketRegimeEvaluator().evaluate(
        market=MarketId.US,
        facts=_facts(curve_10y2y="missing"),
    )

    assert result.regime.rates is RegimeState.FAVORABLE
    assert result.confidence == 1
    assert any("개별 금리로 계산" in warning for warning in result.warnings)


def test_policy_thresholds_are_configurable_and_ordered() -> None:
    relaxed = MarketRegimePolicy(
        vix_adverse_min=35,
        vix_crisis_min=50,
        vix_surge_adverse_min_change_pct=40,
    )
    facts = _facts(vix_level=30.0, vix_change=20.0)

    default_result = MarketRegimeEvaluator().evaluate(market=MarketId.US, facts=facts)
    relaxed_result = MarketRegimeEvaluator(relaxed).evaluate(market=MarketId.US, facts=facts)

    assert default_result.regime.volatility is RegimeState.ADVERSE
    assert relaxed_result.regime.volatility is RegimeState.NEUTRAL

    with pytest.raises(ValidationError, match="VIX 기준"):
        MarketRegimePolicy(vix_favorable_max=30, vix_adverse_min=25)


def test_wrong_unit_makes_axis_unknown_instead_of_guessing() -> None:
    facts = list(_facts())
    vix_index = next(index for index, fact in enumerate(facts) if fact.metric == "VIX 종가")
    facts[vix_index] = facts[vix_index].model_copy(update={"unit": "percent"})

    result = MarketRegimeEvaluator().evaluate(market=MarketId.US, facts=facts)

    assert result.regime.volatility is RegimeState.UNKNOWN
    assert result.position_cap_multiplier == 0.5
    assert any("단위가 정책과 다릅니다" in warning for warning in result.warnings)
