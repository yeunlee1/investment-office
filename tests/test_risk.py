# 의장 결론과 시장 지표에 따른 자본금 독립형 위험 한도를 검증한다
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import BaseModel

from investment_office.services.market_data import EODSnapshot
from investment_office.services.risk import RiskInputError, RiskPolicy, assess_risk


def _snapshot(**overrides: object) -> EODSnapshot:
    values: dict[str, object] = {
        "ticker": "AAPL",
        "exchange": "NMS",
        "currency": "USD",
        "timezone": "America/New_York",
        "as_of_date": date(2026, 1, 2),
        "source_url": "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
        "fetched_at": datetime(2026, 1, 3, tzinfo=UTC),
        "observations": 260,
        "current_close": 100.0,
        "previous_close": 99.0,
        "return_1d_pct": 1.0101,
        "return_5d_pct": 4.0,
        "return_20d_pct": 8.0,
        "return_60d_pct": 15.0,
        "sma_20": 97.0,
        "sma_50": 94.0,
        "sma_200": 80.0,
        "rsi_14": 60.0,
        "atr_14": 4.0,
        "volatility_20d_pct": 25.0,
        "high_52_week": 110.0,
        "low_52_week": 65.0,
        "average_volume_20d": 1_500_000.0,
        "data_gaps": [],
    }
    values.update(overrides)
    return EODSnapshot.model_validate(values)


def _chairman(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "ticker": "AAPL",
        "stance": "bullish",
        "confidence": 0.9,
        "risks": [],
        "data_gaps": [],
        "invalidations": [],
    }
    values.update(overrides)
    return values


def test_bullish_result_produces_deterministic_capital_independent_plan() -> None:
    result = assess_risk(_snapshot(), _chairman())

    assert result.eligible is True
    assert result.action == "size_position"
    assert result.risk_unit_pct == 0.25
    assert result.max_risk_units == 1.0
    assert result.applied_risk_units == 1.0
    assert result.entry_low == 99.0
    assert result.entry_high == 100.4
    assert result.stop_invalidation == 93.0
    assert result.stop_distance_pct == pytest.approx(6.72016, abs=1e-6)
    assert result.position_cap_pct == pytest.approx(3.720149, abs=1e-6)
    assert result.target_price == pytest.approx(113.1)
    assert result.reward_risk_ratio == 2.0
    dumped = result.model_dump(mode="json")
    assert "capital" not in dumped
    assert "shares" not in dumped


@pytest.mark.parametrize(
    ("stance", "action"),
    [("neutral", "watch"), ("bearish", "avoid")],
)
def test_non_bullish_chairman_blocks_new_position(stance: str, action: str) -> None:
    result = assess_risk(_snapshot(), _chairman(stance=stance))

    assert result.eligible is False
    assert result.action == action
    assert result.position_cap_pct == 0.0
    assert result.entry_low is None
    assert result.stop_invalidation is None
    assert result.target_price is None


@pytest.mark.parametrize(
    ("field", "gap_text"),
    [("atr_14", "ATR14"), ("volatility_20d_pct", "20거래일 변동성")],
)
def test_missing_core_risk_metric_blocks_position(field: str, gap_text: str) -> None:
    result = assess_risk(_snapshot(**{field: None}), _chairman())

    assert result.eligible is False
    assert result.position_cap_pct == 0.0
    assert any(gap_text in gap for gap in result.data_gaps)
    assert any("핵심 위험 지표" in warning for warning in result.warnings)


def test_any_declared_data_gap_caps_position() -> None:
    result = assess_risk(
        _snapshot(),
        _chairman(data_gaps=["실적 발표 일정이 확인되지 않았습니다."]),
    )

    assert result.eligible is True
    assert result.position_cap_pct == 1.0
    assert any("데이터 공백" in warning for warning in result.warnings)


def test_high_volatility_and_below_long_term_average_reduce_cap() -> None:
    result = assess_risk(
        _snapshot(volatility_20d_pct=55.0, sma_200=120.0),
        _chairman(),
    )

    assert result.eligible is True
    assert result.position_cap_pct == pytest.approx(0.930037, abs=1e-6)
    assert any("높은 변동성" in warning for warning in result.warnings)
    assert any("SMA200 아래" in warning for warning in result.warnings)


def test_extreme_volatility_blocks_position() -> None:
    result = assess_risk(_snapshot(volatility_20d_pct=80.0), _chairman())

    assert result.eligible is False
    assert result.action == "avoid"
    assert result.position_cap_pct == 0.0
    assert any("최대 허용값" in warning for warning in result.warnings)


def test_chairman_risks_and_invalidations_are_preserved_as_warnings() -> None:
    result = assess_risk(
        _snapshot(),
        _chairman(
            risks=["수요 둔화"],
            invalidations=["가이던스 하향"],
        ),
    )

    assert "의장 위험: 수요 둔화" in result.warnings
    assert "의장 무효화 조건: 가이던스 하향" in result.warnings


class _ChairmanModel(BaseModel):
    ticker: str
    stance: str
    confidence: float
    risks: list[str]
    data_gaps: list[str]
    invalidations: list[str]


def test_accepts_pydantic_chairman_result() -> None:
    chairman = _ChairmanModel.model_validate(_chairman())

    assert assess_risk(_snapshot(), chairman).eligible is True


@pytest.mark.parametrize(
    "chairman",
    [
        _chairman(stance="maybe"),
        _chairman(confidence=1.1),
        _chairman(ticker="MSFT"),
    ],
)
def test_rejects_invalid_chairman_result(chairman: dict[str, object]) -> None:
    with pytest.raises(RiskInputError):
        assess_risk(_snapshot(), chairman)


def test_policy_rejects_inverted_thresholds() -> None:
    with pytest.raises(ValueError):
        RiskPolicy(elevated_volatility_pct=60, high_volatility_pct=50)
