# 시장 스냅샷과 의장 결론으로 자본금 독립형 위험 한도를 결정한다
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from investment_office.services.market_data import EODSnapshot

Stance = Literal["bullish", "neutral", "bearish"]
RiskAction = Literal["size_position", "watch", "avoid"]


class RiskInputError(ValueError):
    """의장 결론 또는 시장 스냅샷이 위험 산정 계약과 맞지 않을 때 발생한다."""


class RiskPolicy(BaseModel):
    """Dollar capital과 무관한 위험 단위 및 기술 지표 제한 정책."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    risk_unit_pct: float = Field(default=0.25, gt=0, le=100)
    max_risk_units: float = Field(default=1.0, gt=0, le=10)
    max_position_pct: float = Field(default=5.0, ge=0, le=100)
    gap_position_cap_pct: float = Field(default=1.0, ge=0, le=100)
    minimum_confidence: float = Field(default=0.55, ge=0, le=1)
    full_risk_confidence: float = Field(default=0.85, ge=0, le=1)
    medium_risk_confidence: float = Field(default=0.70, ge=0, le=1)
    entry_atr_below: float = Field(default=0.25, ge=0, le=10)
    entry_atr_above: float = Field(default=0.10, ge=0, le=10)
    stop_atr_multiple: float = Field(default=1.5, gt=0, le=20)
    minimum_reward_risk: float = Field(default=2.0, gt=0, le=20)
    elevated_volatility_pct: float = Field(default=35.0, ge=0)
    high_volatility_pct: float = Field(default=50.0, ge=0)
    maximum_volatility_pct: float = Field(default=80.0, gt=0)

    @model_validator(mode="after")
    def validate_policy_relationships(self) -> RiskPolicy:
        if self.gap_position_cap_pct > self.max_position_pct:
            raise ValueError("gap_position_cap_pct는 max_position_pct 이하여야 합니다.")
        if not (
            self.minimum_confidence <= self.medium_risk_confidence <= self.full_risk_confidence
        ):
            raise ValueError("신뢰도 임계값은 minimum, medium, full 순이어야 합니다.")
        if not (
            self.elevated_volatility_pct < self.high_volatility_pct < self.maximum_volatility_pct
        ):
            raise ValueError("변동성 임계값은 elevated, high, maximum 순이어야 합니다.")
        return self


class RiskAssessment(BaseModel):
    """Human approval 전에 적용할 가격 계획과 최대 위험 노출."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    stance: Stance
    confidence: float = Field(ge=0, le=1)
    action: RiskAction
    eligible: bool
    risk_unit_pct: float = Field(gt=0, le=100)
    max_risk_units: float = Field(gt=0, le=10)
    applied_risk_units: float = Field(ge=0, le=10)
    position_cap_pct: float = Field(ge=0, le=100)
    entry_low: float | None = Field(default=None, gt=0)
    entry_high: float | None = Field(default=None, gt=0)
    stop_invalidation: float | None = Field(default=None, gt=0)
    target_price: float | None = Field(default=None, gt=0)
    reward_risk_ratio: float | None = Field(default=None, gt=0)
    stop_distance_pct: float | None = Field(default=None, gt=0)
    warnings: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)


def assess_risk(
    snapshot: EODSnapshot,
    chairman_result: Mapping[str, object] | BaseModel,
    policy: RiskPolicy | None = None,
) -> RiskAssessment:
    """Return a deterministic, capital-independent risk assessment."""

    active_policy = policy or RiskPolicy()
    chairman = _chairman_mapping(chairman_result)
    stance = _stance(chairman.get("stance"))
    confidence = _confidence(chairman.get("confidence"))
    _validate_ticker(chairman.get("ticker"), snapshot.ticker)
    chairman_gaps = _string_list(chairman.get("data_gaps"), "data_gaps")
    chairman_risks = _string_list(chairman.get("risks"), "risks")
    invalidations = _string_list(chairman.get("invalidations"), "invalidations")

    data_gaps = list(dict.fromkeys([*snapshot.data_gaps, *chairman_gaps]))
    warnings = [
        *(f"의장 위험: {risk}" for risk in chairman_risks),
        *(f"의장 무효화 조건: {condition}" for condition in invalidations),
    ]

    if stance != "bullish":
        action: RiskAction = "avoid" if stance == "bearish" else "watch"
        warnings.append(
            "의장 결론이 약세라 신규 포지션을 허용하지 않습니다."
            if stance == "bearish"
            else "의장 결론이 중립이라 신규 포지션을 허용하지 않습니다."
        )
        return _blocked(snapshot, stance, confidence, action, active_policy, warnings, data_gaps)

    if confidence < active_policy.minimum_confidence:
        warnings.append(
            f"의장 신뢰도 {confidence:.2f}가 최소값 "
            f"{active_policy.minimum_confidence:.2f}보다 낮습니다."
        )
        return _blocked(snapshot, stance, confidence, "watch", active_policy, warnings, data_gaps)

    if snapshot.atr_14 is None:
        data_gaps.append("ATR14가 없어 손절 무효화 가격을 계산할 수 없습니다.")
    if snapshot.volatility_20d_pct is None:
        data_gaps.append("20거래일 변동성이 없어 포지션 한도를 계산할 수 없습니다.")
    data_gaps = list(dict.fromkeys(data_gaps))
    if snapshot.atr_14 is None or snapshot.volatility_20d_pct is None:
        warnings.append("핵심 위험 지표가 누락되어 신규 포지션을 차단합니다.")
        return _blocked(snapshot, stance, confidence, "watch", active_policy, warnings, data_gaps)

    if snapshot.volatility_20d_pct >= active_policy.maximum_volatility_pct:
        warnings.append(
            f"연환산 변동성 {snapshot.volatility_20d_pct:.2f}%가 최대 허용값 "
            f"{active_policy.maximum_volatility_pct:.2f}% 이상입니다."
        )
        return _blocked(snapshot, stance, confidence, "avoid", active_policy, warnings, data_gaps)

    atr = snapshot.atr_14
    entry_low = snapshot.current_close - atr * active_policy.entry_atr_below
    entry_high = snapshot.current_close + atr * active_policy.entry_atr_above
    reference_entry = (entry_low + entry_high) / 2
    stop = entry_low - atr * active_policy.stop_atr_multiple
    if entry_low <= 0 or stop <= 0:
        warnings.append("ATR 대비 가격이 낮아 양수인 진입·손절 가격을 만들 수 없습니다.")
        return _blocked(snapshot, stance, confidence, "avoid", active_policy, warnings, data_gaps)

    stop_distance_pct = (reference_entry - stop) / reference_entry * 100
    if stop_distance_pct <= 0:
        raise RiskInputError("손절 거리는 0보다 커야 합니다.")

    applied_risk_units = _risk_units(confidence, active_policy)
    risk_budget_pct = active_policy.risk_unit_pct * applied_risk_units
    risk_based_position_pct = risk_budget_pct / stop_distance_pct * 100
    position_cap = min(active_policy.max_position_pct, risk_based_position_pct)

    volatility = snapshot.volatility_20d_pct
    if volatility >= active_policy.high_volatility_pct:
        position_cap *= 0.5
        warnings.append("높은 변동성으로 계산된 포지션 한도를 50% 축소했습니다.")
    elif volatility >= active_policy.elevated_volatility_pct:
        position_cap *= 0.75
        warnings.append("상승한 변동성으로 계산된 포지션 한도를 25% 축소했습니다.")

    if snapshot.sma_200 is None:
        warnings.append("SMA200이 없어 장기 추세 필터를 적용하지 못했습니다.")
    elif snapshot.current_close < snapshot.sma_200:
        position_cap *= 0.5
        warnings.append("현재가가 SMA200 아래라 포지션 한도를 50% 축소했습니다.")

    if snapshot.rsi_14 is None:
        warnings.append("RSI14가 없어 과열 필터를 적용하지 못했습니다.")
    elif snapshot.rsi_14 > 70:
        position_cap *= 0.75
        warnings.append("RSI14가 70을 넘어 포지션 한도를 25% 축소했습니다.")

    if data_gaps:
        position_cap = min(position_cap, active_policy.gap_position_cap_pct)
        warnings.append(
            "데이터 공백이 있어 포지션 한도를 "
            f"{active_policy.gap_position_cap_pct:.2f}%로 제한했습니다."
        )

    target = reference_entry + (reference_entry - stop) * active_policy.minimum_reward_risk
    reward_risk = (target - reference_entry) / (reference_entry - stop)
    return RiskAssessment(
        ticker=snapshot.ticker,
        stance=stance,
        confidence=confidence,
        action="size_position",
        eligible=True,
        risk_unit_pct=active_policy.risk_unit_pct,
        max_risk_units=active_policy.max_risk_units,
        applied_risk_units=_rounded(applied_risk_units),
        position_cap_pct=_rounded(position_cap),
        entry_low=_rounded(entry_low),
        entry_high=_rounded(entry_high),
        stop_invalidation=_rounded(stop),
        target_price=_rounded(target),
        reward_risk_ratio=_rounded(reward_risk),
        stop_distance_pct=_rounded(stop_distance_pct),
        warnings=list(dict.fromkeys(warnings)),
        data_gaps=data_gaps,
    )


def _blocked(
    snapshot: EODSnapshot,
    stance: Stance,
    confidence: float,
    action: RiskAction,
    policy: RiskPolicy,
    warnings: list[str],
    data_gaps: list[str],
) -> RiskAssessment:
    return RiskAssessment(
        ticker=snapshot.ticker,
        stance=stance,
        confidence=confidence,
        action=action,
        eligible=False,
        risk_unit_pct=policy.risk_unit_pct,
        max_risk_units=policy.max_risk_units,
        applied_risk_units=0.0,
        position_cap_pct=0.0,
        warnings=list(dict.fromkeys(warnings)),
        data_gaps=list(dict.fromkeys(data_gaps)),
    )


def _risk_units(confidence: float, policy: RiskPolicy) -> float:
    if confidence >= policy.full_risk_confidence:
        multiplier = 1.0
    elif confidence >= policy.medium_risk_confidence:
        multiplier = 0.7
    else:
        multiplier = 0.4
    return policy.max_risk_units * multiplier


def _chairman_mapping(value: Mapping[str, object] | BaseModel) -> Mapping[str, object]:
    if isinstance(value, BaseModel):
        dumped: object = value.model_dump(mode="python")
        return cast(Mapping[str, object], dumped)
    return value


def _stance(value: object) -> Stance:
    if value not in {"bullish", "neutral", "bearish"}:
        raise RiskInputError(
            "chairman_result.stance는 bullish, neutral, bearish 중 하나여야 합니다."
        )
    return cast(Stance, value)


def _confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RiskInputError("chairman_result.confidence는 0부터 1 사이 숫자여야 합니다.")
    confidence = float(value)
    if not 0 <= confidence <= 1:
        raise RiskInputError("chairman_result.confidence는 0부터 1 사이 숫자여야 합니다.")
    return confidence


def _validate_ticker(value: object, expected: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or value.strip().upper().replace(".", "-") != expected:
        raise RiskInputError("chairman_result.ticker가 시장 스냅샷 티커와 다릅니다.")


def _string_list(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise RiskInputError(f"chairman_result.{field}는 문자열 배열이어야 합니다.")
    resolved: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise RiskInputError(
                f"chairman_result.{field}는 비어 있지 않은 문자열 배열이어야 합니다."
            )
        resolved.append(item.strip())
    return resolved


def _rounded(value: float) -> float:
    return round(value, 6)
