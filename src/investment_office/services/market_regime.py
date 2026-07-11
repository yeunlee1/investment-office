# 거시 사실을 축별 시장 국면과 보수적 포지션 상한으로 평가한다
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from investment_office.services.research_contracts import Fact, MarketId


class RegimeState(StrEnum):
    """각 거시 축의 방향을 다른 축과 섞지 않고 표현한다."""

    FAVORABLE = "favorable"
    NEUTRAL = "neutral"
    ADVERSE = "adverse"
    UNKNOWN = "unknown"


class MarketRegime(BaseModel):
    """시장 전체를 구성하는 독립적인 다섯 거시 축."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rates: RegimeState
    currency: RegimeState
    volatility: RegimeState
    commodities: RegimeState
    liquidity: RegimeState


class MarketRegimeAssessment(BaseModel):
    """추천을 만들지 않고 시장 국면과 위험 노출 상한만 반환한다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    market: MarketId
    regime: MarketRegime
    confidence: float = Field(ge=0, le=1)
    evidence_fact_ids: tuple[str, ...]
    warnings: tuple[str, ...]
    position_cap_multiplier: float = Field(ge=0, le=1)


class MarketRegimePolicy(BaseModel):
    """시장 국면과 포지션 상한에 사용하는 명시적 결정 규칙."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    curve_inversion_max_pp: float = 0.0
    curve_favorable_min_pp: float = 0.5
    ten_year_adverse_min_pct: float = 5.0
    ten_year_rise_adverse_min_pp: float = 0.35
    ten_year_rise_favorable_max_pp: float = 0.2

    broad_dollar_favorable_max_change_pct: float = -1.0
    broad_dollar_adverse_min_change_pct: float = 2.0
    usdk_rw_favorable_max_change_pct: float = -1.0
    usdk_rw_adverse_min_change_pct: float = 2.0
    usdk_rw_adverse_min_level: float = 1450.0

    vix_favorable_max: float = 18.0
    vix_adverse_min: float = 25.0
    vix_crisis_min: float = 40.0
    vix_surge_adverse_min_change_pct: float = 30.0

    oil_favorable_min_usd: float = 50.0
    oil_favorable_max_usd: float = 90.0
    oil_stable_max_abs_change_pct: float = 5.0
    oil_adverse_min_usd: float = 100.0
    oil_surge_adverse_min_change_pct: float = 15.0
    oil_collapse_adverse_max_change_pct: float = -20.0

    bitcoin_favorable_min_change_pct: float = 10.0
    bitcoin_adverse_max_change_pct: float = -15.0

    one_unknown_axis_cap: float = Field(default=0.5, ge=0, le=1)
    multiple_unknown_axes_cap: float = Field(default=0.25, ge=0, le=1)
    curve_inversion_cap: float = Field(default=0.65, ge=0, le=1)
    rates_stress_cap: float = Field(default=0.65, ge=0, le=1)
    broad_dollar_stress_cap: float = Field(default=0.75, ge=0, le=1)
    krw_stress_cap: float = Field(default=0.5, ge=0, le=1)
    vix_stress_cap: float = Field(default=0.5, ge=0, le=1)
    vix_crisis_cap: float = Field(default=0.25, ge=0, le=1)
    oil_stress_cap: float = Field(default=0.75, ge=0, le=1)
    liquidity_stress_cap: float = Field(default=0.75, ge=0, le=1)

    @model_validator(mode="after")
    def validate_threshold_order(self) -> Self:
        if self.curve_inversion_max_pp >= self.curve_favorable_min_pp:
            raise ValueError("우호적 장단기 금리차는 역전 기준보다 커야 합니다.")
        if not self.vix_favorable_max < self.vix_adverse_min < self.vix_crisis_min:
            raise ValueError("VIX 기준은 우호, 불리, 위기 순서로 증가해야 합니다.")
        if not self.oil_favorable_min_usd < self.oil_favorable_max_usd:
            raise ValueError("우호적 유가 하한은 상한보다 작아야 합니다.")
        if self.oil_favorable_max_usd >= self.oil_adverse_min_usd:
            raise ValueError("불리한 유가 기준은 우호적 유가 상한보다 커야 합니다.")
        if self.multiple_unknown_axes_cap > self.one_unknown_axis_cap:
            raise ValueError("다중 미확인 축 상한은 단일 미확인 축 상한보다 클 수 없습니다.")
        if self.vix_crisis_cap > self.vix_stress_cap:
            raise ValueError("VIX 위기 상한은 스트레스 상한보다 클 수 없습니다.")
        return self


DEFAULT_MARKET_REGIME_POLICY: Final = MarketRegimePolicy()


@dataclass(frozen=True, slots=True)
class _SignalSpec:
    metric: str
    unit: str


@dataclass(frozen=True, slots=True)
class _NumericFact:
    fact: Fact
    value: float


@dataclass(frozen=True, slots=True)
class _AxisEvaluation:
    state: RegimeState
    evidence: tuple[_NumericFact, ...]
    warnings: tuple[str, ...] = ()
    risk_flags: frozenset[str] = frozenset()


_SIGNALS: Final = {
    "vix_level": _SignalSpec("VIX 종가", "index_point"),
    "vix_change": _SignalSpec("VIX 종가 30일 변화", "percent"),
    "treasury_2y": _SignalSpec("미국 국채 2년물 금리", "percent"),
    "treasury_3y": _SignalSpec("미국 국채 3년물 금리", "percent"),
    "treasury_10y": _SignalSpec("미국 국채 10년물 금리", "percent"),
    "treasury_10y_change": _SignalSpec(
        "미국 국채 10년물 금리 30일 변화", "percentage_point"
    ),
    "curve_10y2y": _SignalSpec(
        "미국 국채 10년물과 2년물 금리차", "percentage_point"
    ),
    "broad_dollar_level": _SignalSpec("미 연준 광의 달러지수", "index_point"),
    "broad_dollar_change": _SignalSpec("미 연준 광의 달러지수 30일 변화", "percent"),
    "usdk_rw_level": _SignalSpec("원·달러 환율", "krw_per_usd"),
    "usdk_rw_change": _SignalSpec("원·달러 환율 30일 변화", "percent"),
    "wti_level": _SignalSpec("WTI 현물 가격", "usd_per_barrel"),
    "wti_change": _SignalSpec("WTI 현물 가격 30일 변화", "percent"),
    "brent_level": _SignalSpec("브렌트유 현물 가격", "usd_per_barrel"),
    "brent_change": _SignalSpec("브렌트유 현물 가격 30일 변화", "percent"),
    "bitcoin_level": _SignalSpec("비트코인 미국 달러 가격", "usd_per_bitcoin"),
    "bitcoin_change": _SignalSpec("비트코인 미국 달러 가격 30일 변화", "percent"),
}

_AXIS_NAMES: Final = {
    "rates": "금리",
    "currency": "통화",
    "volatility": "변동성",
    "commodities": "원자재",
    "liquidity": "유동성",
}


class _FactIndex:
    def __init__(self, facts: Sequence[Fact]) -> None:
        by_metric: dict[str, list[Fact]] = {}
        for fact in facts:
            by_metric.setdefault(fact.metric, []).append(fact)
        self._facts = {
            metric: max(
                matches,
                key=lambda item: (
                    item.observed_at,
                    item.published_at,
                    item.collected_at,
                    item.revision,
                    item.fact_id,
                ),
            )
            for metric, matches in by_metric.items()
        }

    def resolve(self, signal_name: str) -> tuple[_NumericFact | None, str | None]:
        spec = _SIGNALS[signal_name]
        fact = self._facts.get(spec.metric)
        if fact is None:
            return None, f"거시 지표가 없습니다. {spec.metric}."
        if fact.unit != spec.unit:
            return None, (
                f"거시 지표 단위가 정책과 다릅니다. {spec.metric}은 "
                f"{spec.unit}이어야 하지만 {fact.unit}입니다."
            )
        value = _finite_number(fact.value)
        if value is None:
            return None, f"거시 지표가 유한한 숫자가 아닙니다. {spec.metric}."
        return _NumericFact(fact=fact, value=value), None


class MarketRegimeEvaluator:
    """검증된 거시 사실만으로 축별 국면과 보수적 노출 상한을 산출한다."""

    def __init__(self, policy: MarketRegimePolicy = DEFAULT_MARKET_REGIME_POLICY) -> None:
        self.policy = policy

    def evaluate(
        self,
        *,
        market: MarketId | str,
        facts: Sequence[Fact],
    ) -> MarketRegimeAssessment:
        """방향성 종합 점수 없이 다섯 축을 독립적으로 평가한다."""

        resolved_market = market if isinstance(market, MarketId) else MarketId(market)
        index = _FactIndex(facts)
        evaluations = {
            "rates": self._evaluate_rates(index),
            "currency": self._evaluate_currency(index, resolved_market),
            "volatility": self._evaluate_volatility(index),
            "commodities": self._evaluate_commodities(index),
            "liquidity": self._evaluate_liquidity(index),
        }
        regime = MarketRegime(
            rates=evaluations["rates"].state,
            currency=evaluations["currency"].state,
            volatility=evaluations["volatility"].state,
            commodities=evaluations["commodities"].state,
            liquidity=evaluations["liquidity"].state,
        )
        known_axes = sum(
            evaluation.state is not RegimeState.UNKNOWN for evaluation in evaluations.values()
        )
        flags = frozenset(
            flag for evaluation in evaluations.values() for flag in evaluation.risk_flags
        )
        position_cap, cap_warnings = self._position_cap(evaluations, flags)
        evidence_ids = _unique(
            item.fact.fact_id
            for evaluation in evaluations.values()
            for item in evaluation.evidence
        )
        warnings = _unique(
            warning
            for evaluation in evaluations.values()
            for warning in evaluation.warnings
        ) + cap_warnings
        return MarketRegimeAssessment(
            market=resolved_market,
            regime=regime,
            confidence=round(known_axes / len(evaluations), 2),
            evidence_fact_ids=evidence_ids,
            warnings=_unique(warnings),
            position_cap_multiplier=position_cap,
        )

    def _evaluate_rates(self, index: _FactIndex) -> _AxisEvaluation:
        required, missing, warnings = _resolve_required(
            index,
            ("treasury_2y", "treasury_3y", "treasury_10y"),
        )
        if missing:
            return _unknown_axis(required, warnings)

        two_year, three_year, ten_year = required
        curve_fact, curve_warning = index.resolve("curve_10y2y")
        ten_year_change, change_warning = index.resolve("treasury_10y_change")
        evidence = list(required)
        if curve_fact is None:
            curve = ten_year.value - two_year.value
            warnings.append(
                "공식 2년·10년 금리차가 없어 같은 시점의 개별 금리로 계산했습니다."
            )
        else:
            curve = curve_fact.value
            evidence.append(curve_fact)
        if ten_year_change is not None:
            evidence.append(ten_year_change)
        elif change_warning is not None:
            warnings.append(change_warning)
        if curve_warning is not None and curve_fact is None:
            warnings.append(curve_warning)

        ten_three_curve = ten_year.value - three_year.value
        inverted = (
            curve <= self.policy.curve_inversion_max_pp
            or ten_three_curve <= self.policy.curve_inversion_max_pp
        )
        high_long_rate = ten_year.value >= self.policy.ten_year_adverse_min_pct
        sharp_rise = (
            ten_year_change is not None
            and ten_year_change.value >= self.policy.ten_year_rise_adverse_min_pp
        )
        flags: set[str] = set()
        if inverted:
            flags.add("curve_inverted")
        if high_long_rate or sharp_rise:
            flags.add("rates_stress")

        if inverted or high_long_rate or sharp_rise:
            state = RegimeState.ADVERSE
        elif (
            curve >= self.policy.curve_favorable_min_pp
            and ten_three_curve > self.policy.curve_inversion_max_pp
            and (
                ten_year_change is None
                or ten_year_change.value <= self.policy.ten_year_rise_favorable_max_pp
            )
        ):
            state = RegimeState.FAVORABLE
        else:
            state = RegimeState.NEUTRAL
        return _AxisEvaluation(state, tuple(evidence), tuple(warnings), frozenset(flags))

    def _evaluate_currency(
        self,
        index: _FactIndex,
        market: MarketId,
    ) -> _AxisEvaluation:
        names = ["broad_dollar_level", "broad_dollar_change"]
        if market is MarketId.KR:
            names.extend(("usdk_rw_level", "usdk_rw_change"))
        required, missing, warnings = _resolve_required(index, tuple(names))
        if missing:
            return _unknown_axis(required, warnings)

        values = dict(zip(names, required, strict=True))
        dollar_change = values["broad_dollar_change"].value
        flags: set[str] = set()
        if dollar_change >= self.policy.broad_dollar_adverse_min_change_pct:
            flags.add("broad_dollar_stress")

        if market is MarketId.US:
            if "broad_dollar_stress" in flags:
                state = RegimeState.ADVERSE
            elif dollar_change <= self.policy.broad_dollar_favorable_max_change_pct:
                state = RegimeState.FAVORABLE
            else:
                state = RegimeState.NEUTRAL
            return _AxisEvaluation(state, required, tuple(warnings), frozenset(flags))

        krw_level = values["usdk_rw_level"].value
        krw_change = values["usdk_rw_change"].value
        krw_stress = (
            krw_level >= self.policy.usdk_rw_adverse_min_level
            or krw_change >= self.policy.usdk_rw_adverse_min_change_pct
        )
        if krw_stress:
            flags.add("krw_stress")
        if flags:
            state = RegimeState.ADVERSE
        elif (
            dollar_change <= 0
            and krw_change <= self.policy.usdk_rw_favorable_max_change_pct
        ):
            state = RegimeState.FAVORABLE
        else:
            state = RegimeState.NEUTRAL
        return _AxisEvaluation(state, required, tuple(warnings), frozenset(flags))

    def _evaluate_volatility(self, index: _FactIndex) -> _AxisEvaluation:
        required, missing, warnings = _resolve_required(index, ("vix_level", "vix_change"))
        if missing:
            return _unknown_axis(required, warnings)
        level, change = required
        flags: set[str] = set()
        if level.value >= self.policy.vix_adverse_min:
            flags.add("vix_stress")
        if level.value >= self.policy.vix_crisis_min:
            flags.add("vix_crisis")
        if change.value >= self.policy.vix_surge_adverse_min_change_pct:
            flags.add("vix_surge")
        if flags:
            state = RegimeState.ADVERSE
        elif level.value <= self.policy.vix_favorable_max and change.value <= 0:
            state = RegimeState.FAVORABLE
        else:
            state = RegimeState.NEUTRAL
        return _AxisEvaluation(state, required, tuple(warnings), frozenset(flags))

    def _evaluate_commodities(self, index: _FactIndex) -> _AxisEvaluation:
        required, missing, warnings = _resolve_required(
            index,
            ("wti_level", "wti_change", "brent_level", "brent_change"),
        )
        if missing:
            return _unknown_axis(required, warnings)
        wti_level, wti_change, brent_level, brent_change = required
        levels = (wti_level.value, brent_level.value)
        changes = (wti_change.value, brent_change.value)
        stressed = (
            max(levels) >= self.policy.oil_adverse_min_usd
            or max(changes) >= self.policy.oil_surge_adverse_min_change_pct
            or min(changes) <= self.policy.oil_collapse_adverse_max_change_pct
        )
        if stressed:
            state = RegimeState.ADVERSE
            flags = frozenset({"oil_stress"})
        elif (
            all(
                self.policy.oil_favorable_min_usd
                <= value
                <= self.policy.oil_favorable_max_usd
                for value in levels
            )
            and max(abs(value) for value in changes)
            <= self.policy.oil_stable_max_abs_change_pct
        ):
            state = RegimeState.FAVORABLE
            flags = frozenset()
        else:
            state = RegimeState.NEUTRAL
            flags = frozenset()
        return _AxisEvaluation(state, required, tuple(warnings), flags)

    def _evaluate_liquidity(self, index: _FactIndex) -> _AxisEvaluation:
        required, missing, warnings = _resolve_required(
            index, ("bitcoin_level", "bitcoin_change")
        )
        if missing:
            return _unknown_axis(required, warnings)
        _, change = required
        if change.value <= self.policy.bitcoin_adverse_max_change_pct:
            state = RegimeState.ADVERSE
            flags = frozenset({"liquidity_stress"})
        elif change.value >= self.policy.bitcoin_favorable_min_change_pct:
            state = RegimeState.FAVORABLE
            flags = frozenset()
        else:
            state = RegimeState.NEUTRAL
            flags = frozenset()
        return _AxisEvaluation(state, required, tuple(warnings), flags)

    def _position_cap(
        self,
        evaluations: dict[str, _AxisEvaluation],
        flags: frozenset[str],
    ) -> tuple[float, tuple[str, ...]]:
        candidates: list[tuple[float, str]] = [(1.0, "")]
        unknown_axes = [
            _AXIS_NAMES[name]
            for name, evaluation in evaluations.items()
            if evaluation.state is RegimeState.UNKNOWN
        ]
        if len(unknown_axes) == 1:
            candidates.append(
                (
                    self.policy.one_unknown_axis_cap,
                    "필수 자료를 확인하지 못한 축이 있어 노출 상한을 낮췄습니다. "
                    f"{unknown_axes[0]}.",
                )
            )
        elif len(unknown_axes) > 1:
            candidates.append(
                (
                    self.policy.multiple_unknown_axes_cap,
                    "둘 이상의 필수 거시 축을 확인하지 못해 노출 상한을 크게 낮췄습니다. "
                    + ", ".join(unknown_axes)
                    + ".",
                )
            )

        flag_caps = {
            "curve_inverted": (
                self.policy.curve_inversion_cap,
                "장단기 금리 역전으로 노출 상한을 낮췄습니다.",
            ),
            "rates_stress": (
                self.policy.rates_stress_cap,
                "장기 금리 수준 또는 상승 속도가 높아 노출 상한을 낮췄습니다.",
            ),
            "broad_dollar_stress": (
                self.policy.broad_dollar_stress_cap,
                "광의 달러 강세로 노출 상한을 낮췄습니다.",
            ),
            "krw_stress": (
                self.policy.krw_stress_cap,
                "원화 약세 스트레스로 한국 시장 노출 상한을 낮췄습니다.",
            ),
            "vix_stress": (
                self.policy.vix_stress_cap,
                "VIX 스트레스로 노출 상한을 낮췄습니다.",
            ),
            "vix_crisis": (
                self.policy.vix_crisis_cap,
                "VIX 위기 구간으로 노출 상한을 크게 낮췄습니다.",
            ),
            "vix_surge": (
                self.policy.vix_stress_cap,
                "VIX 급등으로 노출 상한을 낮췄습니다.",
            ),
            "oil_stress": (
                self.policy.oil_stress_cap,
                "유가 충격으로 노출 상한을 낮췄습니다.",
            ),
            "liquidity_stress": (
                self.policy.liquidity_stress_cap,
                "위험 선호 약화로 노출 상한을 낮췄습니다.",
            ),
        }
        candidates.extend(flag_caps[flag] for flag in sorted(flags))
        cap = min(candidate[0] for candidate in candidates)
        warnings = tuple(message for _, message in candidates if message)
        return round(cap, 4), warnings


def _resolve_required(
    index: _FactIndex,
    signal_names: tuple[str, ...],
) -> tuple[tuple[_NumericFact, ...], bool, list[str]]:
    values: list[_NumericFact] = []
    warnings: list[str] = []
    missing = False
    for signal_name in signal_names:
        value, warning = index.resolve(signal_name)
        if value is None:
            missing = True
        else:
            values.append(value)
        if warning is not None:
            warnings.append(warning)
    return tuple(values), missing, warnings


def _unknown_axis(
    evidence: tuple[_NumericFact, ...],
    warnings: list[str],
) -> _AxisEvaluation:
    return _AxisEvaluation(RegimeState.UNKNOWN, evidence, tuple(warnings))


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
