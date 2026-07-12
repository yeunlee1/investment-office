# 일별 가격·거래량만으로 다섯 차트 방법론을 독립 판정하고 근거 중심 보고서를 만든다
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _ChartContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class _DatedValue(Protocol):
    @property
    def trade_date(self) -> date: ...


class PriceBar(_ChartContract):
    """기업행사를 반영한 하나의 완료 일봉 입력."""

    trade_date: date
    open: float | None = Field(default=None, gt=0)
    high: float | None = Field(default=None, gt=0)
    low: float | None = Field(default=None, gt=0)
    close: float = Field(gt=0)
    volume: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_ohlc(self) -> Self:
        comparable = [value for value in (self.open, self.low, self.close) if value is not None]
        if self.high is not None and self.high < max(comparable):
            raise ValueError("고가는 시가·저가·종가보다 작을 수 없습니다.")
        comparable = [value for value in (self.open, self.high, self.close) if value is not None]
        if self.low is not None and self.low > min(comparable):
            raise ValueError("저가는 시가·고가·종가보다 클 수 없습니다.")
        return self


class ChartState(StrEnum):
    CONSTRUCTIVE = "constructive"
    MIXED = "mixed"
    DEFENSIVE = "defensive"
    INSUFFICIENT_DATA = "insufficient_data"


class SetupMode(StrEnum):
    BREAKOUT = "breakout"
    PULLBACK = "pullback"
    SEPARATE_SIGNALS = "separate_signals"
    NONE = "none"
    INSUFFICIENT_DATA = "insufficient_data"


class LensState(StrEnum):
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    INSUFFICIENT_DATA = "insufficient_data"


class LensMetric(_ChartContract):
    name: str = Field(min_length=1, max_length=80)
    value: bool | int | float | str | None
    unit: str | None = Field(default=None, min_length=1, max_length=40)


class LensAssessment(_ChartContract):
    lens_id: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=120)
    adaptation_notice: str = Field(min_length=1, max_length=500)
    timeframe: str = Field(min_length=1, max_length=80)
    state: LensState
    score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    summary: str = Field(min_length=1, max_length=800)
    metrics: tuple[LensMetric, ...] = ()
    confirmations: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    data_gaps: tuple[str, ...] = ()


class PriceLevel(_ChartContract):
    value: float = Field(gt=0)
    label: str = Field(min_length=1, max_length=160)
    timeframe: str = Field(min_length=1, max_length=40)
    source_lenses: tuple[str, ...] = Field(min_length=1)


class ChartAlignment(_ChartContract):
    daily_trend: LensState
    weekly_trend: LensState
    price_volume_state: LensState
    bullish_lenses: int = Field(ge=0)
    neutral_lenses: int = Field(ge=0)
    bearish_lenses: int = Field(ge=0)
    insufficient_lenses: int = Field(ge=0)
    breakout_ready: bool
    breakout_confirmed: bool
    pullback_ready: bool


class ChartDeskReport(_ChartContract):
    """주문 지시 없이 차트 상태와 상충 근거를 함께 보존하는 보고서."""

    ticker: str = Field(min_length=1, max_length=32)
    methodology_version: str = Field(min_length=1, max_length=60)
    as_of_date: date
    observations: int = Field(ge=0)
    weekly_observations: int = Field(ge=0)
    state: ChartState
    composite_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    setup_mode: SetupMode
    alignment: ChartAlignment
    lenses: tuple[LensAssessment, ...]
    support_levels: tuple[PriceLevel, ...] = ()
    resistance_levels: tuple[PriceLevel, ...] = ()
    invalidation_levels: tuple[PriceLevel, ...] = ()
    confirmations: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    data_gaps: tuple[str, ...] = ()

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value


@dataclass(frozen=True, slots=True)
class ChartProfile:
    version: str = "chart_profile_v1"
    minimum_observations: int = 60
    full_trend_observations: int = 252
    swing_window: int = 3
    structure_lookback: int = 80
    volume_window: int = 50
    volume_confirmation_ratio: float = 1.4
    volume_dry_ratio: float = 0.65
    breakout_lookback: int = 55
    base_lookback: int = 35
    base_max_depth_pct: float = 33.0
    base_min_pullback_pct: float = 3.0
    near_pivot_pct: float = 3.0
    pullback_value_tolerance_pct: float = 3.0
    weinstein_slope_weeks: int = 4
    weinstein_slope_threshold_pct: float = 1.0
    weinstein_flat_threshold_pct: float = 1.0
    maximum_daily_gap_days: int = 14
    maximum_short_window_span_days: int = 120
    recent_year_calendar_days: int = 370
    minimum_recent_year_observations: int = 200
    maximum_full_trend_span_days: int = 400
    maximum_weekly_gap_days: int = 21
    maximum_weekly_window_span_days: int = 300
    elder_minimum_daily_observations: int = 120


@dataclass(frozen=True, slots=True)
class _WeeklyBar:
    trade_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: float | None
    observations: int


chart_profile_v1 = ChartProfile()


def analyze_chart(
    ticker: str,
    as_of_date: date,
    bars: Sequence[PriceBar],
) -> ChartDeskReport:
    """완료 일봉만 사용해 버전 고정 차트 데스크 보고서를 만든다."""

    return _analyze_chart(ticker, as_of_date, bars, chart_profile_v1)


def _analyze_chart(
    ticker: str,
    as_of_date: date,
    bars: Sequence[PriceBar],
    profile: ChartProfile,
) -> ChartDeskReport:
    normalized = sorted(
        (bar for bar in bars if bar.trade_date <= as_of_date),
        key=lambda bar: bar.trade_date,
    )
    dates = [bar.trade_date for bar in normalized]
    if len(dates) != len(set(dates)):
        raise ValueError("같은 거래일의 가격 막대가 중복되었습니다.")

    weekly = _to_weekly_bars(normalized)
    partial_week_excluded = bool(
        normalized and normalized[-1].trade_date.weekday() < 4
    )
    if partial_week_excluded:
        weekly = weekly[:-1]
    lenses = (
        _dow_lens(normalized, profile),
        _wyckoff_lens(normalized, profile),
        _weinstein_lens(weekly, profile),
        _oneil_minervini_lens(normalized, profile),
        _elder_lens(normalized, weekly, profile),
    )
    gaps = [
        "시장 지수 쌍이 없어 정통 Dow 이론의 공동 확인을 수행하지 않았습니다.",
        "산업군 시계열이 없어 산업군 상대 강도를 평가하지 않았습니다.",
        "횡단면 종목군이 없어 상대 강도 순위를 추정하지 않았습니다.",
        "펀더멘털 입력이 없어 CAN SLIM 전체 요건을 판정하지 않았습니다.",
        "장중 데이터가 없어 Elder의 세 번째 진입 화면을 판정하지 않았습니다.",
    ]
    if len(normalized) < profile.minimum_observations:
        gaps.append(
            f"최소 {profile.minimum_observations}개 완료 일봉이 필요하지만 "
            f"{len(normalized)}개만 제공되었습니다."
        )
    if any(bar.trade_date > as_of_date for bar in bars):
        gaps.append("기준일 이후 가격 막대는 미래 정보 유입을 막기 위해 제외했습니다.")
    if partial_week_excluded:
        gaps.append(
            "마지막 거래일이 금요일 전이어서 진행 중인 주봉을 주봉 렌즈에서 제외했습니다."
        )
    largest_daily_gap = _largest_date_gap(normalized)
    if largest_daily_gap > profile.maximum_daily_gap_days:
        gaps.append(
            f"연속 일봉 사이 최대 간격이 {largest_daily_gap}일이라 "
            "거래정지·시계열 누락 가능성이 있습니다."
        )
    missing_fields = {
        name
        for name in ("open", "high", "low", "volume")
        if any(getattr(bar, name) is None for bar in normalized)
    }
    if missing_fields:
        gaps.append(
            "일부 일봉에서 다음 입력이 누락되었습니다: "
            f"{', '.join(sorted(missing_fields))}."
        )

    for lens in lenses:
        gaps.extend(lens.data_gaps)
    gaps = list(dict.fromkeys(gaps))

    available = [lens for lens in lenses if lens.state is not LensState.INSUFFICIENT_DATA]
    if available:
        confidence_weight = sum(lens.confidence for lens in available)
        raw_composite_score = (
            sum(lens.score * lens.confidence for lens in available) / confidence_weight
            if confidence_weight > 0
            else 50.0
        )
        coverage = len(available) / len(lenses)
        composite_score = 50.0 + (raw_composite_score - 50.0) * coverage
        confidence = min(
            0.8,
            sum(lens.confidence for lens in available) / len(lenses),
        )
    else:
        composite_score = 50.0
        confidence = 0.0

    state_counts = {
        state: sum(lens.state is state for lens in lenses)
        for state in LensState
    }
    if len(available) < 3:
        state = ChartState.INSUFFICIENT_DATA
    elif composite_score >= 65 and state_counts[LensState.BEARISH] <= 1:
        state = ChartState.CONSTRUCTIVE
    elif composite_score <= 35 or state_counts[LensState.BEARISH] >= 3:
        state = ChartState.DEFENSIVE
    else:
        state = ChartState.MIXED

    raw_breakout_ready = bool(_metric_value(lenses[3], "돌파 준비"))
    raw_breakout_confirmed = bool(_metric_value(lenses[3], "돌파 확인"))
    raw_pullback_ready = bool(_metric_value(lenses[4], "눌림목 준비"))
    breakout_trend_confirmed = lenses[3].state is LensState.BULLISH
    pullback_trend_confirmed = (
        lenses[4].state is LensState.BULLISH
        and lenses[0].state is not LensState.BEARISH
        and lenses[2].state is not LensState.BEARISH
    )
    breakout_ready = raw_breakout_ready and breakout_trend_confirmed
    breakout_confirmed = raw_breakout_confirmed and breakout_trend_confirmed
    pullback_ready = raw_pullback_ready and pullback_trend_confirmed
    if len(normalized) < profile.minimum_observations or len(available) < 3:
        setup_mode = SetupMode.INSUFFICIENT_DATA
    elif (breakout_ready or breakout_confirmed) and pullback_ready:
        setup_mode = SetupMode.SEPARATE_SIGNALS
    elif breakout_ready or breakout_confirmed:
        setup_mode = SetupMode.BREAKOUT
    elif pullback_ready:
        setup_mode = SetupMode.PULLBACK
    else:
        setup_mode = SetupMode.NONE

    confirmations = tuple(
        dict.fromkeys(
            item
            for lens in lenses
            for item in lens.confirmations
        )
    )[:12]
    lens_contradictions = tuple(
        dict.fromkeys(
            item
            for lens in lenses
            for item in lens.contradictions
        )
    )[:12]
    setup_contradictions: list[str] = []
    if (raw_breakout_ready or raw_breakout_confirmed) and not breakout_trend_confirmed:
        setup_contradictions.append(
            "베이스 신호가 있지만 장기 추세 필터가 상승으로 정렬되지 않아 "
            "돌파 후보에서 제외했습니다."
        )
    if raw_pullback_ready and not pullback_trend_confirmed:
        setup_contradictions.append(
            "단기 눌림목 신호가 있지만 일봉·주봉 추세가 방어적이어서 눌림목 후보에서 제외했습니다."
        )
    contradictions = tuple(
        dict.fromkeys([*setup_contradictions, *lens_contradictions])
    )[:12]
    support, resistance, invalidation = _price_levels(normalized, weekly, lenses)

    return ChartDeskReport(
        ticker=ticker,
        methodology_version=profile.version,
        as_of_date=as_of_date,
        observations=len(normalized),
        weekly_observations=len(weekly),
        state=state,
        composite_score=round(composite_score, 2),
        confidence=round(confidence, 4),
        setup_mode=setup_mode,
        alignment=ChartAlignment(
            daily_trend=lenses[0].state,
            weekly_trend=lenses[2].state,
            price_volume_state=lenses[1].state,
            bullish_lenses=state_counts[LensState.BULLISH],
            neutral_lenses=state_counts[LensState.NEUTRAL],
            bearish_lenses=state_counts[LensState.BEARISH],
            insufficient_lenses=state_counts[LensState.INSUFFICIENT_DATA],
            breakout_ready=breakout_ready,
            breakout_confirmed=breakout_confirmed,
            pullback_ready=pullback_ready,
        ),
        lenses=lenses,
        support_levels=support,
        resistance_levels=resistance,
        invalidation_levels=invalidation,
        confirmations=confirmations,
        contradictions=contradictions,
        data_gaps=tuple(gaps),
    )


def _dow_lens(bars: Sequence[PriceBar], profile: ChartProfile) -> LensAssessment:
    gaps = ["개별 종목 적응 모델이며 두 시장 평균의 공동 확인을 대신하지 않습니다."]
    if len(bars) < profile.minimum_observations:
        return _insufficient_lens(
            "dow_structure",
            "Dow식 추세 구조",
            "일봉",
            f"추세 구조에는 완료 일봉 {profile.minimum_observations}개가 필요합니다.",
            gaps,
        )
    dow_cadence_observations = 70 if len(bars) >= 70 else profile.minimum_observations
    if not _dense_daily_window(
        bars,
        observations=dow_cadence_observations,
        maximum_span_days=profile.maximum_short_window_span_days,
        maximum_gap_days=profile.maximum_daily_gap_days,
    ):
        return _insufficient_lens(
            "dow_structure",
            "Dow식 추세 구조",
            "일봉",
            "최근 60개 관측의 일봉 간격이 성겨 연속 추세 구조로 해석하지 않았습니다.",
            gaps,
        )

    closes = [bar.close for bar in bars]
    current = closes[-1]
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    long_trend_available = _dense_daily_window(
        bars,
        observations=200,
        maximum_span_days=profile.maximum_full_trend_span_days,
        maximum_gap_days=profile.maximum_daily_gap_days,
    )
    sma200 = _sma(closes, 200) if long_trend_available else None
    prior_sma50 = _sma(closes[:-20], 50)
    recent = bars[-20:]
    previous = bars[-40:-20]
    recent_high_values = [bar.high for bar in recent if bar.high is not None]
    previous_high_values = [bar.high for bar in previous if bar.high is not None]
    recent_low_values = [bar.low for bar in recent if bar.low is not None]
    previous_low_values = [bar.low for bar in previous if bar.low is not None]
    structure_coverage = min(
        len(recent_high_values),
        len(previous_high_values),
        len(recent_low_values),
        len(previous_low_values),
    )
    if structure_coverage < 15:
        recent_high = previous_high = recent_low = previous_low = None
        gaps.append(
            "최근·직전 20거래일 구간마다 고가·저가가 15개 미만이라 "
            "고저점 구조를 점수에서 제외했습니다."
        )
    else:
        recent_high = max(recent_high_values)
        previous_high = max(previous_high_values)
        recent_low = min(recent_low_values)
        previous_low = min(previous_low_values)
    conditions = (
        ("종가가 20일 평균 위입니다.", _greater(current, sma20), 20.0),
        ("20일 평균이 50일 평균 위입니다.", _greater(sma20, sma50), 20.0),
        ("종가가 50일 평균 위입니다.", _greater(current, sma50), 15.0),
        ("50일 평균 기울기가 상승입니다.", _greater(sma50, prior_sma50), 15.0),
        ("최근 고점 구조가 이전 구간보다 높습니다.", _greater(recent_high, previous_high), 15.0),
        ("최근 저점 구조가 이전 구간보다 높습니다.", _greater(recent_low, previous_low), 15.0),
    )
    score, confirmations, contradictions, available_weight = _score_conditions(conditions)
    if sma200 is None:
        gaps.append(
            "최근 200개 연속 일봉이 없어 200일 장기 평균을 확인하지 않았습니다."
        )
    else:
        relation = current > sma200
        confirmations, contradictions = _append_signal(
            relation,
            "종가가 200일 평균 위입니다.",
            "종가가 200일 평균 위에 있지 않습니다.",
            confirmations,
            contradictions,
        )
    continuous_observations = _dow_confidence_observations(bars, profile)
    confidence = min(
        0.82,
        available_weight * min(1.0, continuous_observations / 252) * 0.9,
    )
    state = _state_from_score(score)
    return LensAssessment(
        lens_id="dow_structure",
        title="Dow식 추세 구조",
        adaptation_notice=(
            "정통 Dow 이론의 지수 공동 확인이 아니라 개별 종목의 종가·고저점 구조를 "
            "재현한 제한적 적응입니다."
        ),
        timeframe="일봉",
        state=state,
        score=score,
        confidence=round(confidence, 4),
        summary=_state_summary(state, "상승 추세 구조", "방어적 추세 구조"),
        metrics=(
            _metric("종가", current, "가격"),
            _metric("SMA20", sma20, "가격"),
            _metric("SMA50", sma50, "가격"),
            _metric("SMA200", sma200, "가격"),
        ),
        confirmations=confirmations,
        contradictions=contradictions,
        data_gaps=tuple(gaps),
    )


def _wyckoff_lens(bars: Sequence[PriceBar], profile: ChartProfile) -> LensAssessment:
    gaps = [
        "거래범위 사건과 P&F 원인 규모가 없어 Wyckoff 단계나 큰손 의도를 단정하지 않습니다."
    ]
    if len(bars) < 60:
        return _insufficient_lens(
            "wyckoff_proxy",
            "Wyckoff 가격·거래량 프록시",
            "일봉",
            "가격·거래량 비교에는 완료 일봉 60개가 필요합니다.",
            gaps,
    )
    window = list(bars[-60:])
    volume_count = sum(
        bar.volume is not None and bar.volume > 0
        for bar in window
    )
    if volume_count < 45:
        return _insufficient_lens(
            "wyckoff_proxy",
            "Wyckoff 가격·거래량 프록시",
            "일봉",
            "최근 60개 중 거래량이 있는 일봉 45개가 필요합니다.",
            gaps,
        )
    if not _dense_daily_window(
        bars,
        observations=60,
        maximum_span_days=profile.maximum_short_window_span_days,
        maximum_gap_days=profile.maximum_daily_gap_days,
    ):
        return _insufficient_lens(
            "wyckoff_proxy",
            "Wyckoff 가격·거래량 프록시",
            "일봉",
            "최근 60개 관측의 일봉 간격이 성겨 가격·거래량 흐름으로 해석하지 않았습니다.",
            gaps,
        )

    recent = window[-20:]
    baseline = window[-40:-20]
    up_volume = 0.0
    down_volume = 0.0
    directional_volume_count = 0
    previous_close = window[-21].close
    for bar in recent:
        if bar.volume is not None and bar.volume > 0:
            directional_volume_count += 1
            if bar.close > previous_close:
                up_volume += bar.volume
            elif bar.close < previous_close:
                down_volume += bar.volume
        previous_close = bar.close
    if directional_volume_count < 15:
        volume_balance = None
        gaps.append(
            "최근 20거래일 중 방향별 거래량이 있는 일봉이 15개 미만이라 "
            "수요·공급 비를 계산하지 않았습니다."
        )
    elif down_volume > 0:
        volume_balance = up_volume / down_volume
    elif up_volume > 0:
        volume_balance = 2.0
    else:
        volume_balance = None
        gaps.append("최근 20거래일의 방향별 유효 거래량이 없어 수요·공급 비를 계산하지 않았습니다.")
    high60 = _maximum(bar.high if bar.high is not None else bar.close for bar in window)
    low60 = _minimum(bar.low if bar.low is not None else bar.close for bar in window)
    range_position = (
        (window[-1].close - low60) / (high60 - low60)
        if high60 is not None and low60 is not None and high60 > low60
        else 0.5
    )
    recent_volume = _average(
        bar.volume if bar.volume is not None and bar.volume > 0 else None
        for bar in window[-5:]
    )
    baseline_volume = _average(
        bar.volume if bar.volume is not None and bar.volume > 0 else None
        for bar in baseline
    )
    effort_ratio = _ratio(recent_volume, baseline_volume)
    return5 = _return_pct([bar.close for bar in window], 5)
    spread_pct = _average(
        (bar.high - bar.low) / bar.close * 100
        for bar in recent
        if bar.high is not None and bar.low is not None
    )
    volume_dry = effort_ratio is not None and effort_ratio <= profile.volume_dry_ratio
    effort_without_result = (
        effort_ratio is not None
        and effort_ratio >= profile.volume_confirmation_ratio
        and return5 is not None
        and abs(return5) < max(2.0, spread_pct or 0.0)
    )
    score = 50.0
    confirmations: list[str] = []
    contradictions: list[str] = []
    if volume_balance is not None and volume_balance >= 1.2:
        score += 18
        confirmations.append("상승일 거래량이 하락일 거래량보다 우세합니다.")
    elif volume_balance is not None and volume_balance <= 0.8:
        score -= 18
        contradictions.append("하락일 거래량이 상승일 거래량보다 우세합니다.")
    if range_position >= 0.65:
        score += 15
        confirmations.append("종가가 최근 거래범위 상단부를 유지합니다.")
    elif range_position <= 0.35:
        score -= 15
        contradictions.append("종가가 최근 거래범위 하단부에 있습니다.")
    if volume_dry and return5 is not None and return5 >= -2:
        score += 10
        confirmations.append("가격을 크게 잃지 않은 채 최근 거래량이 줄었습니다.")
    if effort_without_result:
        score -= 12
        contradictions.append("높은 거래량에 비해 가격 진전이 작아 노력·결과 불일치가 있습니다.")
    score = _clamp(score)
    state = _state_from_score(score)
    return LensAssessment(
        lens_id="wyckoff_proxy",
        title="Wyckoff 가격·거래량 프록시",
        adaptation_notice=(
            "공급·수요와 노력·결과를 정량 프록시로만 평가하며 축적·분산 단계를 "
            "사실처럼 라벨링하지 않습니다."
        ),
        timeframe="일봉",
        state=state,
        score=score,
        confidence=round(min(0.76, volume_count / 60 * 0.76), 4),
        summary=_state_summary(state, "수요 우세 프록시", "공급 우세 프록시"),
        metrics=(
            _metric("상승/하락 거래량 비", volume_balance, "배"),
            _metric("거래범위 위치", range_position * 100, "%"),
            _metric("최근 거래량 비", effort_ratio, "배"),
            _metric("5일 수익률", return5, "%"),
        ),
        confirmations=tuple(confirmations),
        contradictions=tuple(contradictions),
        data_gaps=tuple(gaps),
    )


def _weinstein_lens(
    weekly: Sequence[_WeeklyBar],
    profile: ChartProfile,
) -> LensAssessment:
    gaps = ["벤치마크 대비 Mansfield 상대강도를 계산하지 않았습니다."]
    if len(weekly) < 34:
        return _insufficient_lens(
            "weinstein_stage",
            "Weinstein 30주 단계",
            "주봉",
            "30주 평균과 4주 기울기에는 주봉 34개가 필요합니다.",
            gaps,
        )
    if not _dense_weekly_window(
        weekly,
        observations=34,
        maximum_span_days=profile.maximum_weekly_window_span_days,
        maximum_gap_days=profile.maximum_weekly_gap_days,
    ):
        return _insufficient_lens(
            "weinstein_stage",
            "Weinstein 30주 단계",
            "주봉",
            "최근 주봉 간격이 성겨 30주 단계로 해석하지 않았습니다.",
            gaps,
        )
    closes = [bar.close for bar in weekly]
    sma30 = _sma(closes, 30)
    prior_sma30 = _sma(closes[:-profile.weinstein_slope_weeks], 30)
    slope = _pct_change(sma30, prior_sma30)
    current = closes[-1]
    if sma30 is None or slope is None:
        return _insufficient_lens(
            "weinstein_stage",
            "Weinstein 30주 단계",
            "주봉",
            "30주 평균 기울기를 계산할 수 없습니다.",
            gaps,
        )
    confirmations: tuple[str, ...]
    contradictions: tuple[str, ...]
    if current > sma30 and slope > profile.weinstein_slope_threshold_pct:
        stage = "stage_2"
        state = LensState.BULLISH
        score = 82.0
        confirmations = ("주봉 종가가 상승하는 30주 평균 위에 있어 Stage 2 프록시입니다.",)
        contradictions = ()
    elif current < sma30 and slope < -profile.weinstein_slope_threshold_pct:
        stage = "stage_4"
        state = LensState.BEARISH
        score = 18.0
        confirmations = ()
        contradictions = ("주봉 종가가 하락하는 30주 평균 아래에 있어 Stage 4 프록시입니다.",)
    elif abs(slope) <= profile.weinstein_flat_threshold_pct:
        stage = "stage_1_or_3"
        state = LensState.NEUTRAL
        score = 50.0
        confirmations = ()
        contradictions = ("30주 평균이 평탄해 방향 전환 또는 베이스 상태입니다.",)
        gaps.append("직전 단계 이력이 없어 Stage 1과 Stage 3을 구분하지 않았습니다.")
    else:
        stage = "transition"
        state = LensState.NEUTRAL
        score = 55.0 if current > sma30 else 45.0
        confirmations = ()
        contradictions = ("가격과 30주 평균 기울기가 같은 단계로 정렬되지 않았습니다.",)
    return LensAssessment(
        lens_id="weinstein_stage",
        title="Weinstein 30주 단계",
        adaptation_notice=(
            "주봉 종가와 30주 평균만으로 만든 단계 프록시이며 직전 단계와 시장·산업군 "
            "확인은 별도 입력이 필요합니다."
        ),
        timeframe="주봉",
        state=state,
        score=score,
        confidence=round(
            min(
                0.82,
                _weinstein_confidence_observations(weekly, profile)
                / 52
                * 0.82,
            ),
            4,
        ),
        summary=f"현재 주봉 단계 프록시는 {stage}입니다.",
        metrics=(
            _metric("단계 프록시", stage),
            _metric("30주 SMA", sma30, "가격"),
            _metric("30주 SMA 4주 기울기", slope, "%"),
        ),
        confirmations=confirmations,
        contradictions=contradictions,
        data_gaps=tuple(gaps),
    )


def _oneil_minervini_lens(
    bars: Sequence[PriceBar],
    profile: ChartProfile,
) -> LensAssessment:
    gaps = [
        "IBD·횡단면 상대강도 순위가 없어 자체 가격 추세만 평가했습니다.",
        "실적·기관 보유·시장 방향이 없어 CAN SLIM 완료 판정이 아닙니다.",
        "컵·핸들 또는 VCP를 육안 패턴처럼 확정하지 않고 베이스 프록시만 계산했습니다.",
    ]
    if len(bars) < profile.full_trend_observations:
        return _insufficient_lens(
            "oneil_minervini_proxy",
            "O'Neil·Minervini 추세·베이스 프록시",
            "일봉·주봉 베이스",
            "장기 추세와 52주 위치에는 완료 일봉 252개가 필요합니다.",
            gaps,
        )
    if not _dense_daily_window(
        bars,
        observations=profile.full_trend_observations,
        maximum_span_days=profile.maximum_full_trend_span_days,
        maximum_gap_days=profile.maximum_daily_gap_days,
    ):
        return _insufficient_lens(
            "oneil_minervini_proxy",
            "O'Neil·Minervini 추세·베이스 프록시",
            "일봉·주봉 베이스",
            "장기 평균에 쓰는 252개 관측이 최근 약 1년의 연속 일봉이 아닙니다.",
            gaps,
        )
    recent_year_start = bars[-1].trade_date - timedelta(
        days=profile.recent_year_calendar_days
    )
    recent_year = [bar for bar in bars if bar.trade_date >= recent_year_start]
    if (
        len(recent_year) < profile.minimum_recent_year_observations
        or _largest_date_gap(recent_year) > profile.maximum_daily_gap_days
    ):
        return _insufficient_lens(
            "oneil_minervini_proxy",
            "O'Neil·Minervini 추세·베이스 프록시",
            "일봉·주봉 베이스",
            "최근 약 1년의 일봉 밀도가 부족해 52주 위치와 장기 추세를 판정하지 않았습니다.",
            gaps,
        )
    closes = [bar.close for bar in bars]
    current = closes[-1]
    sma50 = _sma(closes, 50)
    sma150 = _sma(closes, 150)
    sma200 = _sma(closes, 200)
    prior_sma200 = _sma(closes[:-20], 200)
    history = recent_year
    high52 = _maximum(bar.high if bar.high is not None else bar.close for bar in history)
    low52 = _minimum(bar.low if bar.low is not None else bar.close for bar in history)
    conditions = (
        (
            "종가가 150일·200일 평균 위입니다.",
            _all_true(_greater(current, sma150), _greater(current, sma200)),
            1.0,
        ),
        ("150일 평균이 200일 평균 위입니다.", _greater(sma150, sma200), 1.0),
        ("200일 평균이 최근 20거래일 동안 상승했습니다.", _greater(sma200, prior_sma200), 1.0),
        (
            "50일 평균이 150일·200일 평균 위입니다.",
            _all_true(_greater(sma50, sma150), _greater(sma50, sma200)),
            1.0,
        ),
        ("종가가 50일 평균 위입니다.", _greater(current, sma50), 1.0),
        (
            "종가가 52주 저가보다 30% 이상 높습니다.",
            low52 is not None and current >= low52 * 1.3,
            1.0,
        ),
        (
            "종가가 52주 고가의 25% 이내입니다.",
            high52 is not None and current >= high52 * 0.75,
            1.0,
        ),
    )
    score, confirmations, contradictions, _ = _score_conditions(conditions)
    trend_condition_count = len(confirmations)
    base = bars[-profile.base_lookback - 1 : -1]
    base_high = _maximum(bar.high if bar.high is not None else bar.close for bar in base)
    base_low = _minimum(bar.low if bar.low is not None else bar.close for bar in base)
    base_depth = (
        (base_high - base_low) / base_high * 100
        if base_high is not None and base_low is not None and base_high > 0
        else None
    )
    running_peak = 0.0
    base_max_pullback = 0.0
    for bar in base:
        running_peak = max(running_peak, bar.close)
        if running_peak > 0:
            base_max_pullback = max(
                base_max_pullback,
                (running_peak - bar.close) / running_peak * 100,
            )
    pivot_distance = (
        (base_high - current) / base_high * 100 if base_high is not None else None
    )
    prior_volumes = [
        bar.volume
        for bar in bars[-51:-1]
        if bar.volume is not None and bar.volume > 0
    ]
    average_volume = (
        sum(prior_volumes) / len(prior_volumes)
        if len(prior_volumes) >= 40
        else None
    )
    current_volume = bars[-1].volume
    relative_volume = _ratio(
        current_volume if current_volume is not None and current_volume > 0 else None,
        average_volume,
    )
    if average_volume is None:
        gaps.append(
            "직전 50거래일 중 양의 거래량이 40개 미만이라 "
            "돌파 거래량을 확인하지 않았습니다."
        )
    elif current_volume is None or current_volume <= 0:
        gaps.append("현재 거래량이 없어 돌파 거래량을 확인하지 않았습니다.")
    base_valid = (
        base_depth is not None
        and base_depth <= profile.base_max_depth_pct
        and base_max_pullback >= profile.base_min_pullback_pct
    )
    breakout_ready = (
        base_valid
        and pivot_distance is not None
        and 0 <= pivot_distance <= profile.near_pivot_pct
    )
    breakout_confirmed = (
        base_valid
        and base_high is not None
        and current > base_high
        and relative_volume is not None
        and relative_volume >= profile.volume_confirmation_ratio
    )
    if breakout_confirmed:
        confirmations += ("베이스 상단을 평균 대비 확대된 거래량으로 돌파했습니다.",)
    elif current > (base_high or math.inf):
        contradictions += ("베이스 상단 돌파에 필요한 거래량 확인이 부족합니다.",)
    if base_max_pullback < profile.base_min_pullback_pct:
        contradictions += (
            "직전 35거래일에 최소 되돌림이 없어 횡보·수축 베이스로 인정하지 않았습니다.",
        )
    state = _state_from_score(score)
    return LensAssessment(
        lens_id="oneil_minervini_proxy",
        title="O'Neil·Minervini 추세·베이스 프록시",
        adaptation_notice=(
            "공개된 추세·베이스 원칙을 재현한 후보 필터이며 독점 등급이나 전체 방법론의 "
            "완료 신호가 아닙니다."
        ),
        timeframe="일봉·주봉 베이스",
        state=state,
        score=score,
        confidence=round(min(0.75, len(bars) / 252 * 0.75), 4),
        summary=_state_summary(state, "장기 추세 필터 통과 우세", "장기 추세 필터 미달 우세"),
        metrics=(
            _metric("추세 조건 충족", trend_condition_count, "개"),
            _metric("베이스 깊이", base_depth, "%"),
            _metric("베이스 최대 되돌림", base_max_pullback, "%"),
            _metric("피벗 거리", pivot_distance, "%"),
            _metric("상대 거래량", relative_volume, "배"),
            _metric("돌파 준비", breakout_ready),
            _metric("돌파 확인", breakout_confirmed),
        ),
        confirmations=confirmations,
        contradictions=contradictions,
        data_gaps=tuple(gaps),
    )


def _elder_lens(
    bars: Sequence[PriceBar],
    weekly: Sequence[_WeeklyBar],
    profile: ChartProfile,
) -> LensAssessment:
    gaps = [
        "장중 주문 트리거를 만들지 않고 주봉 전략 방향과 일봉 눌림목 허용 여부만 평가합니다."
    ]
    if len(bars) < 30 or len(weekly) < 35:
        return _insufficient_lens(
            "elder_triple_screen",
            "Elder 주봉→일봉 Impulse",
            "주봉·일봉",
            "주봉·일봉 Impulse와 가치구역에는 주봉 35개와 일봉 30개가 필요합니다.",
            gaps,
        )
    if not _dense_daily_window(
        bars,
        observations=30,
        maximum_span_days=60,
        maximum_gap_days=profile.maximum_daily_gap_days,
    ) or not _dense_weekly_window(
        weekly,
        observations=35,
        maximum_span_days=profile.maximum_weekly_window_span_days,
        maximum_gap_days=profile.maximum_weekly_gap_days,
    ) or (
        sum(bar.observations for bar in weekly[-35:])
        < profile.elder_minimum_daily_observations
    ):
        return _insufficient_lens(
            "elder_triple_screen",
            "Elder 주봉→일봉 Impulse",
            "주봉·일봉",
            "주봉·일봉 연속성 또는 주봉 구간의 일봉 밀도가 부족해 해석하지 않았습니다.",
            gaps,
        )
    weekly_tail = weekly[-35:]
    daily_tail = bars[-30:]
    weekly_closes = [bar.close for bar in weekly_tail]
    weekly_histogram = _macd_histogram(weekly_closes)
    weekly_ema13 = _ema(weekly_closes, 13)
    closes = [bar.close for bar in daily_tail]
    daily_histogram = _macd_histogram(closes)
    daily_ema13_series = _ema(closes, 13)
    if (
        len(weekly_histogram) < 2
        or len(weekly_ema13) < 2
        or len(daily_histogram) < 2
        or len(daily_ema13_series) < 2
    ):
        return _insufficient_lens(
            "elder_triple_screen",
            "Elder 주봉→일봉 Impulse",
            "주봉·일봉",
            "두 시간축의 EMA와 MACD Histogram 기울기를 계산할 수 없습니다.",
            gaps,
        )
    weekly_ema_slope = weekly_ema13[-1] - weekly_ema13[-2]
    weekly_histogram_slope = weekly_histogram[-1] - weekly_histogram[-2]
    daily_ema_slope = daily_ema13_series[-1] - daily_ema13_series[-2]
    daily_histogram_slope = daily_histogram[-1] - daily_histogram[-2]
    weekly_impulse = _impulse_state(weekly_ema_slope, weekly_histogram_slope)
    daily_impulse = _impulse_state(daily_ema_slope, daily_histogram_slope)
    ema13 = daily_ema13_series[-1]
    ema26 = _ema(closes, 26)[-1]
    rsi14 = _rsi(closes, 14)
    current = closes[-1]
    lower_value = min(ema13, ema26) * (1 - profile.pullback_value_tolerance_pct / 100)
    upper_value = max(ema13, ema26) * (1 + profile.pullback_value_tolerance_pct / 100)
    near_value = lower_value <= current <= upper_value
    force_index = _elder_force_index(daily_tail)
    if force_index is None:
        gaps.append("최근 거래량이 불완전해 2일 Force Index를 계산하지 않았습니다.")
    pullback_ready = (
        weekly_impulse != "red"
        and daily_impulse == "blue"
        and near_value
        and force_index is not None
        and force_index < 0
    )
    confirmations: list[str] = []
    contradictions: list[str] = []
    if weekly_impulse != "red":
        confirmations.append("주봉 Impulse가 매수 금지 상태가 아닙니다.")
    else:
        contradictions.append("주봉 Impulse가 red여서 눌림목 관찰을 금지합니다.")
    if daily_impulse == "blue":
        confirmations.append("일봉 Impulse가 blue로 전환돼 전술 확인 조건을 충족합니다.")
    elif daily_impulse == "red":
        contradictions.append("일봉 Impulse가 red여서 눌림목 관찰을 금지합니다.")
    if pullback_ready:
        confirmations.append("일봉이 EMA 가치구역에 있고 2일 Force Index가 음수입니다.")
    elif not near_value:
        contradictions.append("일봉이 EMA 가치구역에서 벗어나 있습니다.")
    elif force_index is not None and force_index >= 0:
        contradictions.append("2일 Force Index가 음수가 아니어서 눌림목 조건을 충족하지 않습니다.")
    if pullback_ready:
        score = 75.0
        state = LensState.BULLISH
    elif weekly_impulse == "red" or daily_impulse == "red":
        score = 25.0
        state = LensState.BEARISH
    else:
        score = 55.0
        state = LensState.NEUTRAL
    return LensAssessment(
        lens_id="elder_triple_screen",
        title="Elder 주봉→일봉 Impulse",
        adaptation_notice=(
            "13 EMA와 12·26·9 MACD Histogram의 두 시간축 Impulse, 일봉 가치구역, "
            "2일 Force Index를 결합한 분석용 구현이며 주문 규칙은 만들지 않습니다."
        ),
        timeframe="주봉·일봉",
        state=state,
        score=score,
        confidence=0.72 if force_index is not None else 0.58,
        summary=(
            "상위 추세 안의 일봉 눌림목 후보입니다."
            if pullback_ready
            else "주봉 허용 상태와 일봉 눌림목 조건을 분리해 관찰해야 합니다."
        ),
        metrics=(
            _metric("주봉 Impulse", weekly_impulse),
            _metric("일봉 Impulse", daily_impulse),
            _metric("주봉 MACD Histogram 기울기", weekly_histogram_slope),
            _metric("일봉 EMA13", ema13, "가격"),
            _metric("일봉 EMA26", ema26, "가격"),
            _metric("RSI14", rsi14),
            _metric("2일 Force Index", force_index),
            _metric("눌림목 준비", pullback_ready),
        ),
        confirmations=tuple(confirmations),
        contradictions=tuple(contradictions),
        data_gaps=tuple(gaps),
    )


def _impulse_state(ema_slope: float, histogram_slope: float) -> str:
    if ema_slope > 0 and histogram_slope > 0:
        return "green"
    if ema_slope < 0 and histogram_slope < 0:
        return "red"
    return "blue"


def _elder_force_index(bars: Sequence[PriceBar]) -> float | None:
    recent = bars[-21:]
    if len(recent) < 3 or any(bar.volume is None for bar in recent):
        return None
    values = [
        (current.close - previous.close) * float(current.volume or 0.0)
        for previous, current in zip(recent[:-1], recent[1:], strict=True)
    ]
    smoothed = _ema(values, 2)
    return smoothed[-1] if smoothed else None


def _to_weekly_bars(bars: Sequence[PriceBar]) -> list[_WeeklyBar]:
    grouped: dict[tuple[int, int], list[PriceBar]] = {}
    for bar in bars:
        iso = bar.trade_date.isocalendar()
        grouped.setdefault((iso.year, iso.week), []).append(bar)
    weekly: list[_WeeklyBar] = []
    for values in grouped.values():
        opens = [bar.open for bar in values if bar.open is not None]
        highs = [bar.high for bar in values if bar.high is not None]
        lows = [bar.low for bar in values if bar.low is not None]
        volumes = [bar.volume for bar in values if bar.volume is not None]
        weekly.append(
            _WeeklyBar(
                trade_date=values[-1].trade_date,
                open=opens[0] if opens else None,
                high=max(highs) if highs else None,
                low=min(lows) if lows else None,
                close=values[-1].close,
                volume=sum(volumes) if volumes else None,
                observations=len(values),
            )
        )
    return weekly


def _price_levels(
    bars: Sequence[PriceBar],
    weekly: Sequence[_WeeklyBar],
    lenses: Sequence[LensAssessment],
) -> tuple[tuple[PriceLevel, ...], tuple[PriceLevel, ...], tuple[PriceLevel, ...]]:
    if not bars:
        return (), (), ()
    closes = [bar.close for bar in bars]
    current = closes[-1]
    recent20 = bars[-20:]
    recent_lows = [bar.low for bar in recent20 if bar.low is not None]
    dow_available = lenses[0].state is not LensState.INSUFFICIENT_DATA
    wyckoff_available = lenses[1].state is not LensState.INSUFFICIENT_DATA
    weinstein_available = lenses[2].state is not LensState.INSUFFICIENT_DATA
    oneil_available = lenses[3].state is not LensState.INSUFFICIENT_DATA
    covered_recent_low = (
        min(recent_lows)
        if wyckoff_available and len(recent_lows) >= 15
        else None
    )
    prior55 = bars[-56:-1]
    prior_highs = [bar.high for bar in prior55 if bar.high is not None]
    covered_prior_high = (
        max(prior_highs)
        if oneil_available and len(prior_highs) >= 40
        else None
    )
    support_candidates = (
        (
            _sma(closes, 20) if dow_available else None,
            "20일 단순이동평균",
            "일봉",
            ("dow_structure",),
        ),
        (
            _sma(closes, 50) if dow_available else None,
            "50일 단순이동평균",
            "일봉",
            ("dow_structure",),
        ),
        (covered_recent_low, "최근 20거래일 저점", "일봉", ("wyckoff_proxy",)),
        (
            _sma([bar.close for bar in weekly], 30) if weinstein_available else None,
            "30주 단순이동평균",
            "주봉",
            ("weinstein_stage",),
        ),
    )
    resistance_candidates = (
        (
            covered_prior_high,
            "직전 55거래일 상단",
            "일봉",
            ("oneil_minervini_proxy",),
        ),
    )
    supports = _make_levels(
        item
        for item in support_candidates
        if item[0] is not None and item[0] <= current
    )
    resistances = _make_levels(
        item
        for item in resistance_candidates
        if item[0] is not None and item[0] >= current
    )
    invalidations = _make_levels(
        item
        for item in support_candidates
        if item[0] is not None and item[0] < current
    )[:2]
    return supports[:4], resistances[:3], invalidations


def _make_levels(
    candidates: Iterable[tuple[float | None, str, str, tuple[str, ...]]],
) -> tuple[PriceLevel, ...]:
    levels: list[PriceLevel] = []
    for value, label, timeframe, sources in candidates:
        if value is None or value <= 0:
            continue
        if any(abs(existing.value - value) / value < 0.002 for existing in levels):
            continue
        levels.append(
            PriceLevel(
                value=round(value, 6),
                label=label,
                timeframe=timeframe,
                source_lenses=sources,
            )
        )
    return tuple(levels)


def _insufficient_lens(
    lens_id: str,
    title: str,
    timeframe: str,
    reason: str,
    gaps: Sequence[str],
) -> LensAssessment:
    return LensAssessment(
        lens_id=lens_id,
        title=title,
        adaptation_notice="필수 입력이 부족해 원전 이름을 빌린 방향성 판정을 만들지 않습니다.",
        timeframe=timeframe,
        state=LensState.INSUFFICIENT_DATA,
        score=50.0,
        confidence=0.0,
        summary=reason,
        data_gaps=tuple(dict.fromkeys([*gaps, reason])),
    )


def _score_conditions(
    conditions: Sequence[tuple[str, bool | None, float]],
) -> tuple[float, tuple[str, ...], tuple[str, ...], float]:
    available = [
        (label, result, weight)
        for label, result, weight in conditions
        if result is not None
    ]
    total_weight = sum(weight for _, _, weight in conditions)
    available_weight = sum(weight for _, _, weight in available)
    passed_weight = sum(weight for _, result, weight in available if result)
    score = passed_weight / available_weight * 100 if available_weight else 50.0
    confirmations = tuple(label for label, result, _ in available if result)
    contradictions = tuple(
        _negative_condition_label(label)
        for label, result, _ in available
        if not result
    )
    return round(score, 2), confirmations, contradictions, available_weight / total_weight


def _negative_condition_label(label: str) -> str:
    replacements = (
        (" 위입니다.", " 위에 있지 않습니다."),
        (" 상승입니다.", " 상승이 아닙니다."),
        (" 상승했습니다.", " 상승하지 않았습니다."),
        (" 높습니다.", " 높지 않습니다."),
        (" 이내입니다.", " 이내가 아닙니다."),
        (" 유지합니다.", " 유지하지 못합니다."),
    )
    for source, target in replacements:
        if label.endswith(source):
            return f"{label[: -len(source)]}{target}"
    if label.endswith("입니다."):
        return f"{label[:-4]}이 아닙니다."
    return f"다음 조건을 충족하지 못했습니다: {label}"


def _append_signal(
    result: bool,
    confirmation: str,
    contradiction: str,
    confirmations: tuple[str, ...],
    contradictions: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if result:
        return (*confirmations, confirmation), contradictions
    return confirmations, (*contradictions, contradiction)


def _metric(
    name: str,
    value: bool | int | float | str | None,
    unit: str | None = None,
) -> LensMetric:
    if isinstance(value, float) and math.isfinite(value):
        value = round(value, 4)
    return LensMetric(name=name, value=value, unit=unit)


def _metric_value(lens: LensAssessment, name: str) -> object:
    for metric in lens.metrics:
        if metric.name == name:
            return metric.value
    return None


def _state_from_score(score: float) -> LensState:
    if score >= 65:
        return LensState.BULLISH
    if score <= 35:
        return LensState.BEARISH
    return LensState.NEUTRAL


def _state_summary(state: LensState, positive: str, negative: str) -> str:
    if state is LensState.BULLISH:
        return f"{positive}가 우세합니다."
    if state is LensState.BEARISH:
        return f"{negative}가 우세합니다."
    return "확인과 모순이 섞여 있어 방향을 확정하지 않습니다."


def _greater(left: float | None, right: float | None) -> bool | None:
    if left is None or right is None:
        return None
    return left > right


def _all_true(*values: bool | None) -> bool | None:
    if any(value is None for value in values):
        return None
    return all(value is True for value in values)


def _largest_date_gap(
    values: Sequence[_DatedValue],
) -> int:
    if len(values) < 2:
        return 0
    return max(
        (current.trade_date - previous.trade_date).days
        for previous, current in zip(values[:-1], values[1:], strict=True)
    )


def _dense_daily_window(
    bars: Sequence[PriceBar],
    *,
    observations: int,
    maximum_span_days: int,
    maximum_gap_days: int,
) -> bool:
    if len(bars) < observations:
        return False
    window = bars[-observations:]
    span_days = (window[-1].trade_date - window[0].trade_date).days
    return (
        span_days <= maximum_span_days
        and _largest_date_gap(window) <= maximum_gap_days
    )


def _dense_weekly_window(
    bars: Sequence[_WeeklyBar],
    *,
    observations: int,
    maximum_span_days: int,
    maximum_gap_days: int,
) -> bool:
    if len(bars) < observations:
        return False
    window = bars[-observations:]
    span_days = (window[-1].trade_date - window[0].trade_date).days
    return (
        span_days <= maximum_span_days
        and _largest_date_gap(window) <= maximum_gap_days
    )


def _dow_confidence_observations(
    bars: Sequence[PriceBar],
    profile: ChartProfile,
) -> int:
    tiers = (
        (252, profile.maximum_full_trend_span_days),
        (200, 340),
        (180, 310),
        (150, 260),
        (120, 210),
        (90, 160),
        (70, profile.maximum_short_window_span_days),
        (profile.minimum_observations, profile.maximum_short_window_span_days),
    )
    for observations, maximum_span_days in tiers:
        if _dense_daily_window(
            bars,
            observations=observations,
            maximum_span_days=maximum_span_days,
            maximum_gap_days=profile.maximum_daily_gap_days,
        ):
            return observations
    return 0


def _weinstein_confidence_observations(
    bars: Sequence[_WeeklyBar],
    profile: ChartProfile,
) -> int:
    for observations, maximum_span_days in ((52, 370), (44, 310), (34, 245)):
        if _dense_weekly_window(
            bars,
            observations=observations,
            maximum_span_days=maximum_span_days,
            maximum_gap_days=profile.maximum_weekly_gap_days,
        ):
            return observations
    return 0


def _sma(values: Sequence[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _ema(values: Sequence[float], period: int) -> list[float]:
    if not values:
        return []
    multiplier = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(value * multiplier + result[-1] * (1 - multiplier))
    return result


def _macd_histogram(values: Sequence[float]) -> list[float]:
    if len(values) < 2:
        return []
    fast = _ema(values, 12)
    slow = _ema(values, 26)
    macd = [left - right for left, right in zip(fast, slow, strict=True)]
    signal = _ema(macd, 9)
    return [left - right for left, right in zip(macd, signal, strict=True)]


def _rsi(values: Sequence[float], period: int) -> float | None:
    if len(values) <= period:
        return None
    deltas = [current - previous for previous, current in zip(values, values[1:], strict=False)]
    gains = [max(delta, 0.0) for delta in deltas]
    losses = [max(-delta, 0.0) for delta in deltas]
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:], strict=True):
        average_gain = (average_gain * (period - 1) + gain) / period
        average_loss = (average_loss * (period - 1) + loss) / period
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    relative_strength = average_gain / average_loss
    return 100 - 100 / (1 + relative_strength)


def _return_pct(values: Sequence[float], horizon: int) -> float | None:
    if len(values) <= horizon or values[-horizon - 1] <= 0:
        return None
    return (values[-1] / values[-horizon - 1] - 1) * 100


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return (current / previous - 1) * 100


def _ratio(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None or baseline <= 0:
        return None
    return current / baseline


def _average(values: Iterable[float | None]) -> float | None:
    resolved = [float(value) for value in values if value is not None]
    return sum(resolved) / len(resolved) if resolved else None


def _maximum(values: Iterable[float | None]) -> float | None:
    resolved = [float(value) for value in values if value is not None]
    return max(resolved) if resolved else None


def _minimum(values: Iterable[float | None]) -> float | None:
    resolved = [float(value) for value in values if value is not None]
    return min(resolved) if resolved else None


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)
