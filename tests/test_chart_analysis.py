# 다섯 차트 렌즈의 방향·설정·누락 데이터·결정론 계약을 검증한다
from __future__ import annotations

import json
import math
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from investment_office.services.chart_analysis import (
    ChartDeskReport,
    ChartState,
    LensAssessment,
    LensState,
    PriceBar,
    SetupMode,
    analyze_chart,
    chart_profile_v1,
)


def _business_days(count: int, *, start: date = date(2024, 1, 2)) -> list[date]:
    resolved: list[date] = []
    current = start
    while len(resolved) < count:
        if current.weekday() < 5:
            resolved.append(current)
        current += timedelta(days=1)
    return resolved


def _complete_bar(
    trade_date: date,
    close: float,
    *,
    volume: float | None = 1_000_000,
) -> PriceBar:
    open_price = close * 0.998
    return PriceBar(
        trade_date=trade_date,
        open=open_price,
        high=max(open_price, close) * 1.01,
        low=min(open_price, close) * 0.99,
        close=close,
        volume=volume,
    )


def _trend_bars(
    daily_return: float,
    *,
    final_jump: float = 0.0,
    final_volume: float = 1_000_000,
) -> list[PriceBar]:
    dates = _business_days(300)
    price = 50.0 if daily_return > 0 else 200.0
    bars: list[PriceBar] = []
    for index, trade_date in enumerate(dates):
        price *= 1 + daily_return
        if index == len(dates) - 1:
            price *= 1 + final_jump
        open_price = price * (0.998 if daily_return > 0 else 1.002)
        bars.append(
            PriceBar(
                trade_date=trade_date,
                open=open_price,
                high=max(open_price, price) * 1.01,
                low=min(open_price, price) * 0.99,
                close=price,
                volume=final_volume if index == len(dates) - 1 else 1_000_000,
            )
        )
    return bars


def _pullback_bars() -> list[PriceBar]:
    dates = _business_days(300)
    price = 50.0
    bars: list[PriceBar] = []
    for index, trade_date in enumerate(dates):
        if index < 285:
            daily_return = 0.0015
        elif index < 295:
            daily_return = -0.003
        elif index < 299:
            daily_return = 0.001
        else:
            daily_return = -0.0005
        price *= 1 + daily_return
        bars.append(_complete_bar(trade_date, price))
    return bars


def _breakout_bars(*, sparse_volume: bool = False) -> list[PriceBar]:
    dates = _business_days(300)
    price = 50.0
    bars: list[PriceBar] = []
    for index, trade_date in enumerate(dates):
        if index < 264:
            price *= 1.003
        elif index < 299:
            phase = (index - 264) / 34
            price = bars[263].close * (1 - 0.06 * math.sin(math.pi * phase))
        else:
            price = bars[263].close * 1.03
        volume: float | None = 2_000_000 if index == 299 else 1_000_000
        if sparse_volume and 249 <= index < 298:
            volume = None
        bars.append(_complete_bar(trade_date, price, volume=volume))
    return bars


def _lens(report: ChartDeskReport, lens_id: str) -> LensAssessment:
    return next(lens for lens in report.lenses if lens.lens_id == lens_id)


def _metrics(lens: LensAssessment) -> dict[str, object]:
    return {metric.name: metric.value for metric in lens.metrics}


def test_price_bar_accepts_missing_optional_values_and_validates_present_ohlc() -> None:
    partial = PriceBar(trade_date=date(2025, 1, 2), close=100.0)

    assert partial.open is None
    assert partial.high is None
    assert partial.low is None
    assert partial.volume is None

    with pytest.raises(ValidationError, match="고가는"):
        PriceBar(trade_date=date(2025, 1, 2), high=99.0, close=100.0)


def test_rising_and_falling_series_produce_opposite_market_states() -> None:
    rising = _trend_bars(0.003)
    falling = _trend_bars(-0.003)

    rising_report = analyze_chart(" rise ", rising[-1].trade_date, rising)
    falling_report = analyze_chart("fall", falling[-1].trade_date, falling)

    assert rising_report.ticker == "RISE"
    assert rising_report.state is ChartState.CONSTRUCTIVE
    assert rising_report.composite_score >= 65
    assert rising_report.alignment.daily_trend is LensState.BULLISH
    assert rising_report.alignment.weekly_trend is LensState.BULLISH
    assert rising_report.alignment.price_volume_state is LensState.BULLISH

    assert falling_report.state is ChartState.DEFENSIVE
    assert falling_report.composite_score <= 35
    assert falling_report.alignment.daily_trend is LensState.BEARISH
    assert falling_report.alignment.weekly_trend is LensState.BEARISH
    assert falling_report.alignment.price_volume_state is LensState.BEARISH


def test_volume_confirmed_breakout_is_kept_separate_from_pullback() -> None:
    bars = _breakout_bars()

    report = analyze_chart("break", bars[-1].trade_date, bars)
    oneil_minervini = _lens(report, "oneil_minervini_proxy")

    assert _metrics(oneil_minervini)["돌파 확인"] is True
    assert report.alignment.breakout_confirmed is True
    assert report.alignment.pullback_ready is False
    assert report.setup_mode is SetupMode.BREAKOUT
    assert _metrics(oneil_minervini)["추세 조건 충족"] == 7


def test_weekly_to_daily_pullback_has_its_own_setup_mode() -> None:
    bars = _pullback_bars()

    report = analyze_chart("pull", bars[-1].trade_date, bars)
    elder = _lens(report, "elder_triple_screen")

    assert _metrics(elder)["눌림목 준비"] is True
    assert report.alignment.pullback_ready is True
    assert report.alignment.breakout_ready is False
    assert report.alignment.breakout_confirmed is False
    assert report.setup_mode is SetupMode.PULLBACK


def test_missing_ohlcv_degrades_only_dependent_lenses() -> None:
    dates = _business_days(260)
    close_only = [
        PriceBar(trade_date=trade_date, close=50 * (1.002**index))
        for index, trade_date in enumerate(dates)
    ]

    report = analyze_chart("partial", dates[-1], close_only)

    assert report.observations == 260
    assert len(report.lenses) == 5
    assert _lens(report, "wyckoff_proxy").state is LensState.INSUFFICIENT_DATA
    assert _lens(report, "oneil_minervini_proxy").state is not LensState.INSUFFICIENT_DATA
    assert any(
        all(field in gap for field in ("high", "low", "open", "volume"))
        for gap in report.data_gaps
    )


def test_one_available_lens_cannot_promote_the_whole_report() -> None:
    dates = _business_days(60)
    bars = [
        PriceBar(trade_date=trade_date, close=100 + index)
        for index, trade_date in enumerate(dates)
    ]

    report = analyze_chart("thin", dates[-1], bars)

    assert report.state is ChartState.INSUFFICIENT_DATA
    assert report.setup_mode is SetupMode.INSUFFICIENT_DATA
    assert report.composite_score < 65
    assert report.alignment.insufficient_lenses == 4


def test_wyckoff_uses_latest_closes_when_recent_ohlcv_is_missing() -> None:
    dates = _business_days(60)
    bars = [
        _complete_bar(trade_date, 100 + index)
        for index, trade_date in enumerate(dates[:50])
    ]
    bars.extend(
        PriceBar(trade_date=trade_date, close=50 - index)
        for index, trade_date in enumerate(dates[50:])
    )

    report = analyze_chart("recent-gap", dates[-1], bars)
    wyckoff = _lens(report, "wyckoff_proxy")
    range_position = _metrics(wyckoff)["거래범위 위치"]

    assert wyckoff.state is not LensState.BULLISH
    assert isinstance(range_position, (int, float))
    assert range_position < 35


def test_zero_volume_cannot_create_a_wyckoff_bullish_signal() -> None:
    dates = _business_days(60)
    bars = [
        _complete_bar(trade_date, 100 + index, volume=0)
        for index, trade_date in enumerate(dates)
    ]

    report = analyze_chart("zero-volume", dates[-1], bars)

    assert _lens(report, "wyckoff_proxy").state is LensState.INSUFFICIENT_DATA


def test_partial_year_cannot_activate_the_long_term_template() -> None:
    dates = _business_days(200)
    bars = [
        _complete_bar(trade_date, 100 + index)
        for index, trade_date in enumerate(dates)
    ]

    report = analyze_chart("partial-year", dates[-1], bars)

    assert _lens(report, "oneil_minervini_proxy").state is LensState.INSUFFICIENT_DATA
    assert report.alignment.breakout_ready is False
    assert report.alignment.breakout_confirmed is False
    assert report.setup_mode is not SetupMode.BREAKOUT


def test_sparse_calendar_observations_cannot_masquerade_as_daily_bars() -> None:
    dates = [date(2004, 1, 1) + timedelta(days=31 * index) for index in range(252)]
    bars = [
        _complete_bar(trade_date, 100 + index)
        for index, trade_date in enumerate(dates)
    ]

    report = analyze_chart("sparse-calendar", dates[-1], bars)

    assert _lens(report, "oneil_minervini_proxy").state is LensState.INSUFFICIENT_DATA
    assert any("최대 간격" in gap for gap in report.data_gaps)
    assert report.support_levels == ()
    assert report.resistance_levels == ()
    assert report.invalidation_levels == ()


def test_dense_korea_style_year_is_not_rejected_by_us_calendar_span() -> None:
    all_dates = _business_days(268, start=date(2024, 1, 2))
    removed = set(range(10, 266, 16))
    dates = [value for index, value in enumerate(all_dates) if index not in removed]
    assert len(dates) == 252
    assert 370 < (dates[-1] - dates[0]).days <= 400
    bars = [
        _complete_bar(trade_date, 100 + index)
        for index, trade_date in enumerate(dates)
    ]

    report = analyze_chart("kr-dense", dates[-1], bars)

    assert _lens(report, "oneil_minervini_proxy").state is not LensState.INSUFFICIENT_DATA


def test_old_tail_cannot_fill_long_moving_average_history() -> None:
    old_dates = _business_days(52, start=date(2000, 1, 3))
    recent_dates = _business_days(200, start=date(2024, 1, 2))
    dates = [*old_dates, *recent_dates]
    bars = [
        _complete_bar(trade_date, 100 + index)
        for index, trade_date in enumerate(dates)
    ]

    report = analyze_chart("old-tail", dates[-1], bars)

    assert _lens(report, "oneil_minervini_proxy").state is LensState.INSUFFICIENT_DATA
    assert any("252개 관측" in gap for gap in report.data_gaps)


def test_old_tail_cannot_fill_dow_slope_history() -> None:
    old_dates = _business_days(10, start=date(2000, 1, 3))
    recent_dates = _business_days(60, start=date(2024, 1, 2))
    dates = [*old_dates, *recent_dates]
    bars = [
        _complete_bar(trade_date, 100 + index)
        for index, trade_date in enumerate(dates)
    ]

    report = analyze_chart("old-dow-tail", dates[-1], bars)

    assert _lens(report, "dow_structure").state is LensState.INSUFFICIENT_DATA


def test_old_tail_cannot_strengthen_dow_long_average_or_confidence() -> None:
    old_dates = _business_days(130, start=date(2000, 1, 3))
    recent_dates = _business_days(70, start=date(2024, 1, 2))
    bars = [
        *[_complete_bar(trade_date, 10.0) for trade_date in old_dates],
        *[_complete_bar(trade_date, 100.0) for trade_date in recent_dates],
    ]

    report = analyze_chart("old-dow-average", recent_dates[-1], bars)
    dow = _lens(report, "dow_structure")

    assert _metrics(dow)["SMA200"] is None
    assert "종가가 200일 평균 위입니다." not in dow.confirmations
    assert dow.confidence <= 0.25
    assert any("최근 200개 연속 일봉" in gap for gap in dow.data_gaps)


def test_weekly_prefix_cannot_strengthen_daily_dow_confidence() -> None:
    recent_dates = _business_days(70, start=date(2024, 8, 5))
    old_dates = [
        recent_dates[0] - timedelta(days=7 * index)
        for index in range(182, 0, -1)
    ]
    recent = [_complete_bar(trade_date, 100.0) for trade_date in recent_dates]
    with_weekly_prefix = [
        *[_complete_bar(trade_date, 10.0) for trade_date in old_dates],
        *recent,
    ]

    recent_dow = _lens(
        analyze_chart("daily-tail", recent_dates[-1], recent),
        "dow_structure",
    )
    prefixed_dow = _lens(
        analyze_chart("weekly-prefix", recent_dates[-1], with_weekly_prefix),
        "dow_structure",
    )

    assert prefixed_dow.state == recent_dow.state
    assert prefixed_dow.confidence == recent_dow.confidence


def test_old_tail_cannot_strengthen_weinstein_confidence() -> None:
    old_dates = [date(2000, 1, 7) + timedelta(days=7 * index) for index in range(18)]
    recent_dates = [date(2024, 1, 5) + timedelta(days=7 * index) for index in range(34)]
    recent = [
        _complete_bar(trade_date, 100 + index)
        for index, trade_date in enumerate(recent_dates)
    ]
    with_old_tail = [
        *[
            _complete_bar(trade_date, 50 + index)
            for index, trade_date in enumerate(old_dates)
        ],
        *recent,
    ]

    recent_report = analyze_chart("weekly-recent", recent_dates[-1], recent)
    tailed_report = analyze_chart("weekly-tailed", recent_dates[-1], with_old_tail)
    recent_lens = _lens(recent_report, "weinstein_stage")
    tailed_lens = _lens(tailed_report, "weinstein_stage")

    assert recent_lens.state is not LensState.INSUFFICIENT_DATA
    assert tailed_lens.state == recent_lens.state
    assert tailed_lens.confidence == recent_lens.confidence


def test_biweekly_prefix_cannot_strengthen_weinstein_confidence() -> None:
    recent_dates = [date(2024, 8, 2) + timedelta(days=7 * index) for index in range(34)]
    old_dates = [
        recent_dates[0] - timedelta(days=14 * index)
        for index in range(18, 0, -1)
    ]
    recent = [
        _complete_bar(trade_date, 100 + index)
        for index, trade_date in enumerate(recent_dates)
    ]
    with_biweekly_prefix = [
        *[
            _complete_bar(trade_date, 50 + index)
            for index, trade_date in enumerate(old_dates)
        ],
        *recent,
    ]

    recent_lens = _lens(
        analyze_chart("weekly-tail", recent_dates[-1], recent),
        "weinstein_stage",
    )
    prefixed_lens = _lens(
        analyze_chart("biweekly-prefix", recent_dates[-1], with_biweekly_prefix),
        "weinstein_stage",
    )

    assert prefixed_lens.state == recent_lens.state
    assert prefixed_lens.confidence == recent_lens.confidence


def test_nine_day_prefix_cannot_strengthen_weinstein_confidence() -> None:
    recent_dates = [date(2024, 8, 2) + timedelta(days=7 * index) for index in range(34)]
    old_dates = [
        recent_dates[0] - timedelta(days=9 * index)
        for index in range(18, 0, -1)
    ]
    recent = [
        _complete_bar(trade_date, 100 + index)
        for index, trade_date in enumerate(recent_dates)
    ]
    with_sparse_prefix = [
        *[
            _complete_bar(trade_date, 50 + index)
            for index, trade_date in enumerate(old_dates)
        ],
        *recent,
    ]

    recent_lens = _lens(
        analyze_chart("weekly-tail-nine", recent_dates[-1], recent),
        "weinstein_stage",
    )
    prefixed_lens = _lens(
        analyze_chart("nine-day-prefix", recent_dates[-1], with_sparse_prefix),
        "weinstein_stage",
    )

    assert prefixed_lens.state == recent_lens.state
    assert prefixed_lens.confidence == recent_lens.confidence


def test_old_tail_cannot_change_elder_impulse() -> None:
    old_dates = [date(2000, 1, 7) + timedelta(days=7 * index) for index in range(20)]
    recent_dates = _business_days(180, start=date(2024, 1, 2))
    recent = [_complete_bar(trade_date, 100.0) for trade_date in recent_dates]
    with_old_tail = [
        *[_complete_bar(trade_date, 1_000.0) for trade_date in old_dates],
        *recent,
    ]

    recent_report = analyze_chart("elder-recent", recent_dates[-1], recent)
    tailed_report = analyze_chart("elder-tailed", recent_dates[-1], with_old_tail)
    recent_lens = _lens(recent_report, "elder_triple_screen")
    tailed_lens = _lens(tailed_report, "elder_triple_screen")

    assert recent_lens.state is not LensState.INSUFFICIENT_DATA
    assert tailed_lens.state == recent_lens.state
    assert _metrics(tailed_lens)["주봉 Impulse"] == _metrics(recent_lens)["주봉 Impulse"]


def test_elder_requires_daily_coverage_across_weekly_window() -> None:
    recent_dates = _business_days(30, start=date(2024, 8, 5))
    old_dates = [
        recent_dates[0] - timedelta(days=3 + 7 * index)
        for index in range(29, 0, -1)
    ]
    bars = [
        *[_complete_bar(trade_date, 1_000.0) for trade_date in old_dates],
        *[_complete_bar(trade_date, 100.0) for trade_date in recent_dates],
    ]

    report = analyze_chart("elder-thin-weeks", recent_dates[-1], bars)

    assert _lens(report, "elder_triple_screen").state is LensState.INSUFFICIENT_DATA


def test_elder_keeps_fixed_window_across_a_normal_long_holiday() -> None:
    dates = _business_days(180, start=date(2024, 1, 2))
    monday_index = next(
        index
        for index in range(len(dates) - 35, len(dates) - 15)
        if dates[index].weekday() == 0
    )
    removed = set(dates[monday_index + 1 : monday_index + 5])
    holiday_dates = [trade_date for trade_date in dates if trade_date not in removed]
    bars = [
        _complete_bar(trade_date, 100 + index * 0.1)
        for index, trade_date in enumerate(holiday_dates)
    ]

    report = analyze_chart("elder-holiday", holiday_dates[-1], bars)
    elder = _lens(report, "elder_triple_screen")

    assert elder.state is not LensState.INSUFFICIENT_DATA
    assert _metrics(elder)["주봉 Impulse"] in {"green", "blue", "red"}

    dow = _lens(report, "dow_structure")
    assert dow.state is not LensState.INSUFFICIENT_DATA
    assert dow.confidence > 0.4


def test_dow_structure_requires_covered_highs_and_lows() -> None:
    dates = _business_days(252)
    bars = [
        PriceBar(trade_date=trade_date, close=100.0)
        for trade_date in dates
    ]
    for index in (220, 240):
        bars[index] = bars[index].model_copy(update={"high": 101.0, "low": 99.0})

    report = analyze_chart("thin-ohlc", dates[-1], bars)
    dow = _lens(report, "dow_structure")

    assert not any("고점 구조" in item or "저점 구조" in item for item in dow.confirmations)
    assert dow.confidence <= 0.63
    assert any("15개 미만" in gap for gap in dow.data_gaps)
    assert not any(level.label == "최근 20거래일 저점" for level in report.support_levels)


def test_single_prior_high_cannot_create_resistance() -> None:
    dates = _business_days(300)
    bars = [
        PriceBar(
            trade_date=trade_date,
            close=100 + index,
            volume=1_000_000,
        )
        for index, trade_date in enumerate(dates)
    ]
    bars[-20] = bars[-20].model_copy(update={"high": bars[-20].close * 1.01})

    report = analyze_chart("thin-resistance", dates[-1], bars)

    assert _lens(report, "oneil_minervini_proxy").state is not LensState.INSUFFICIENT_DATA
    assert report.resistance_levels == ()


def test_monotonic_rise_is_not_called_a_base_breakout() -> None:
    bars = _trend_bars(0.003)

    report = analyze_chart("no-base", bars[-1].trade_date, bars)
    oneil_minervini = _lens(report, "oneil_minervini_proxy")

    assert _metrics(oneil_minervini)["돌파 준비"] is False
    assert _metrics(oneil_minervini)["돌파 확인"] is False
    assert report.setup_mode is not SetupMode.BREAKOUT
    assert any("최소 되돌림" in item for item in oneil_minervini.contradictions)


def test_in_progress_week_is_excluded_from_weekly_lenses() -> None:
    bars = _trend_bars(0.003)
    assert bars[-1].trade_date.weekday() < 4
    all_weeks = {
        (bar.trade_date.isocalendar().year, bar.trade_date.isocalendar().week)
        for bar in bars
    }

    report = analyze_chart("partial-week", bars[-1].trade_date, bars)

    assert report.weekly_observations == len(all_weeks) - 1
    assert any("진행 중인 주봉" in gap for gap in report.data_gaps)


def test_sma_equality_is_not_described_as_below() -> None:
    dates = _business_days(252)
    bars = [_complete_bar(trade_date, 100.0) for trade_date in dates]

    report = analyze_chart("flat", dates[-1], bars)
    dow = _lens(report, "dow_structure")

    assert "종가가 200일 평균 위에 있지 않습니다." in dow.contradictions
    assert "종가가 200일 평균 아래입니다." not in dow.contradictions


def test_sparse_volume_cannot_confirm_a_breakout() -> None:
    bars = _breakout_bars(sparse_volume=True)

    report = analyze_chart("sparse-volume", bars[-1].trade_date, bars)
    oneil_minervini = _lens(report, "oneil_minervini_proxy")

    assert _metrics(oneil_minervini)["돌파 확인"] is False
    assert report.alignment.breakout_confirmed is False
    assert any("40개 미만" in gap for gap in oneil_minervini.data_gaps)


def test_future_bars_are_excluded_and_reported() -> None:
    bars = _trend_bars(0.003)
    as_of_date = bars[-2].trade_date

    report = analyze_chart("future", as_of_date, bars)

    assert report.as_of_date == as_of_date
    assert report.observations == len(bars) - 1
    assert any("기준일 이후" in gap for gap in report.data_gaps)


def test_duplicate_trade_dates_are_rejected() -> None:
    trade_date = date(2025, 1, 2)
    bars = [
        _complete_bar(trade_date, 100.0),
        _complete_bar(trade_date, 101.0),
    ]

    with pytest.raises(ValueError, match="중복"):
        analyze_chart("duplicate", trade_date, bars)


def test_report_is_json_serializable_and_preserves_all_lenses() -> None:
    bars = _trend_bars(0.003)

    report = analyze_chart("json", bars[-1].trade_date, bars)
    payload = json.loads(report.model_dump_json())
    restored = ChartDeskReport.model_validate_json(report.model_dump_json())

    assert payload["methodology_version"] == chart_profile_v1.version
    assert payload["as_of_date"] == bars[-1].trade_date.isoformat()
    assert {lens["lens_id"] for lens in payload["lenses"]} == {
        "dow_structure",
        "wyckoff_proxy",
        "weinstein_stage",
        "oneil_minervini_proxy",
        "elder_triple_screen",
    }
    assert restored == report
    assert not {"action", "order", "recommendation"}.intersection(payload)


def test_price_levels_are_deterministic_for_input_order() -> None:
    bars = _trend_bars(0.003)

    ordered = analyze_chart("levels", bars[-1].trade_date, bars)
    reversed_input = analyze_chart("levels", bars[-1].trade_date, list(reversed(bars)))

    assert ordered.support_levels
    assert ordered.resistance_levels
    assert ordered.invalidation_levels
    assert ordered.support_levels == reversed_input.support_levels
    assert ordered.resistance_levels == reversed_input.resistance_levels
    assert ordered.invalidation_levels == reversed_input.invalidation_levels
    assert all(level.value > 0 and level.source_lenses for level in ordered.support_levels)
    current = bars[-1].close
    assert all(level.value <= current for level in ordered.support_levels)
    assert all(level.value >= current for level in ordered.resistance_levels)
