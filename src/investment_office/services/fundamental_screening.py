# 전체시장 후보의 최근 3개년 재무를 검증하고 재무 하드게이트 점수를 계산한다.
from __future__ import annotations

import math
from datetime import date
from enum import StrEnum
from typing import Self, cast

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator

from investment_office.services.research_contracts import MarketId


class FundamentalGateProfile(StrEnum):
    """재무 안전장치의 보수성 수준이다."""

    DEFENSIVE = "defensive"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class IndustryModel(StrEnum):
    """부채와 현금흐름을 같은 방식으로 비교할 수 있는 산업군이다."""

    GENERAL = "general"
    FINANCIAL = "financial"
    INSURANCE = "insurance"
    REIT = "reit"
    UNKNOWN = "unknown"


class FundamentalGateStatus(StrEnum):
    """재무 하드게이트의 자동 처리 결과다."""

    PASSED = "passed"
    EXCLUDED = "excluded"
    INSUFFICIENT_DATA = "insufficient_data"
    SPECIAL_REVIEW = "special_review"


class AnnualFundamentals(BaseModel):
    """한 사업연도의 연결 재무 핵심값이다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fiscal_year: int = Field(ge=1990, le=2200)
    revenue: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    operating_cash_flow: float | None = None
    free_cash_flow: float | None = None
    equity: float | None = None
    assets: float | None = None
    liabilities: float | None = None


class ScreeningFundamentals(BaseModel):
    """종목 하나의 재무 게이트 입력과 데이터 계보다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    market: MarketId
    ticker: str = Field(min_length=1, max_length=15)
    company_name: str = Field(min_length=1, max_length=300)
    sector: str = Field(default="unknown", min_length=1, max_length=160)
    industry_model: IndustryModel = IndustryModel.UNKNOWN
    currency: str = Field(min_length=3, max_length=8)
    periods: tuple[AnnualFundamentals, ...] = Field(min_length=1, max_length=5)
    latest_report_date: date
    source_urls: tuple[AnyHttpUrl, ...] = Field(min_length=1)
    market_cap: float | None = Field(default=None, gt=0)
    trailing_pe: float | None = Field(default=None, gt=0)
    price_to_book: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_periods(self) -> Self:
        years = [period.fiscal_year for period in self.periods]
        if years != sorted(years):
            raise ValueError("재무 연도는 오래된 순서부터 정렬해야 합니다.")
        if len(years) != len(set(years)):
            raise ValueError("재무 연도는 중복될 수 없습니다.")
        return self


class FundamentalScoreBreakdown(BaseModel):
    """누락값을 0점으로 치환하지 않는 재무 세부 점수다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    quality: float = Field(ge=0, le=100)
    growth: float = Field(ge=0, le=100)
    valuation: float | None = Field(default=None, ge=0, le=100)
    total: float = Field(ge=0, le=100)


class FundamentalGateResult(BaseModel):
    """추천 가능 여부와 재현 가능한 재무 판정 근거다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    status: FundamentalGateStatus
    passed: bool
    reasons: tuple[str, ...]
    risks: tuple[str, ...]
    missing_fields: tuple[str, ...] = ()
    scores: FundamentalScoreBreakdown | None = None


class FundamentalGate:
    """최근 3개년 수익성과 현금흐름을 점수보다 먼저 검증한다."""

    _MAX_REPORT_AGE_DAYS = 550
    _MAX_DEBT_TO_EQUITY = {
        FundamentalGateProfile.DEFENSIVE: 1.5,
        FundamentalGateProfile.BALANCED: 2.5,
        FundamentalGateProfile.AGGRESSIVE: 3.5,
    }

    def evaluate(
        self,
        fundamentals: ScreeningFundamentals,
        profile: FundamentalGateProfile | str,
        *,
        as_of_date: date,
    ) -> FundamentalGateResult:
        """자료 충분성, 산업별 규칙과 재무 안전성을 순서대로 판정한다."""

        selected_profile = FundamentalGateProfile(profile)
        periods = fundamentals.periods[-3:]
        missing = self._missing_fields(periods)
        if len(periods) < 3:
            missing.insert(0, "최근 3개 사업연도")
        report_age = (as_of_date - fundamentals.latest_report_date).days
        if report_age < 0 or report_age > self._MAX_REPORT_AGE_DAYS:
            missing.append("최신 재무보고서")
        if missing:
            unique_missing = tuple(dict.fromkeys(missing))
            return FundamentalGateResult(
                ticker=fundamentals.ticker,
                status=FundamentalGateStatus.INSUFFICIENT_DATA,
                passed=False,
                reasons=("재무 하드게이트에 필요한 자료가 충분하지 않습니다.",),
                risks=("누락 재무값을 0으로 간주하지 않고 추천 대상에서 보류했습니다.",),
                missing_fields=unique_missing,
            )

        if fundamentals.industry_model in {
            IndustryModel.FINANCIAL,
            IndustryModel.INSURANCE,
            IndustryModel.REIT,
        }:
            return FundamentalGateResult(
                ticker=fundamentals.ticker,
                status=FundamentalGateStatus.SPECIAL_REVIEW,
                passed=False,
                reasons=("금융·보험·리츠 전용 건전성 지표 검토가 필요합니다.",),
                risks=("일반 기업의 부채비율과 현금흐름 기준을 적용하면 오판할 수 있습니다.",),
            )

        values = tuple(periods)
        latest = values[-1]
        revenue = tuple(float(item.revenue) for item in values if item.revenue is not None)
        operating_income = tuple(
            float(item.operating_income)
            for item in values
            if item.operating_income is not None
        )
        net_income = tuple(
            float(item.net_income) for item in values if item.net_income is not None
        )
        operating_cash_flow = tuple(
            float(item.operating_cash_flow)
            for item in values
            if item.operating_cash_flow is not None
        )
        equity = cast(float, latest.equity)
        liabilities = cast(float, latest.liabilities)
        debt_to_equity = liabilities / equity if equity > 0 else math.inf
        revenue_growth = _compound_growth(revenue[0], revenue[-1], len(revenue) - 1)

        failures: list[str] = []
        if equity <= 0:
            failures.append("최신 자본총계가 0 이하입니다.")
        if operating_income[-1] <= 0:
            failures.append("최신 영업이익이 적자입니다.")
        if net_income[-1] <= 0 or sum(value > 0 for value in net_income) < 2:
            failures.append("최근 3년 순이익의 지속성이 부족합니다.")
        if sum(value > 0 for value in operating_cash_flow) < 2:
            failures.append("최근 3년 영업현금흐름의 지속성이 부족합니다.")
        if debt_to_equity > self._MAX_DEBT_TO_EQUITY[selected_profile]:
            failures.append(
                f"부채비율이 {debt_to_equity * 100:.1f}%로 "
                f"{selected_profile.value} 기준을 넘습니다."
            )
        minimum_growth = (
            0.05
            if selected_profile is FundamentalGateProfile.AGGRESSIVE
            else -0.02
        )
        if revenue_growth < minimum_growth:
            failures.append(
                f"3개년 매출 연평균 성장률 {revenue_growth * 100:.1f}%가 기준보다 낮습니다."
            )
        if failures:
            return FundamentalGateResult(
                ticker=fundamentals.ticker,
                status=FundamentalGateStatus.EXCLUDED,
                passed=False,
                reasons=tuple(failures),
                risks=("가격 모멘텀이 좋아도 재무 하드게이트 실패를 상쇄하지 않습니다.",),
            )

        scores = self._scores(
            fundamentals,
            revenue_growth=revenue_growth,
            debt_to_equity=debt_to_equity,
            positive_net_income_years=sum(value > 0 for value in net_income),
            positive_cash_flow_years=sum(value > 0 for value in operating_cash_flow),
        )
        return FundamentalGateResult(
            ticker=fundamentals.ticker,
            status=FundamentalGateStatus.PASSED,
            passed=True,
            reasons=(
                "최근 3년 수익성과 영업현금흐름 기준을 통과했습니다.",
                f"3개년 매출 연평균 성장률은 {revenue_growth * 100:.1f}%입니다.",
                f"최신 부채비율은 {debt_to_equity * 100:.1f}%입니다.",
            ),
            risks=("공시 정정과 최신 분기 변화는 심층 분석에서 다시 확인해야 합니다.",),
            scores=scores,
        )

    @staticmethod
    def _missing_fields(periods: tuple[AnnualFundamentals, ...]) -> list[str]:
        missing: list[str] = []
        if len(periods) < 3 or any(item.revenue is None for item in periods):
            missing.append("매출")
        if len(periods) < 3 or any(item.operating_income is None for item in periods):
            missing.append("영업이익")
        if len(periods) < 3 or any(item.net_income is None for item in periods):
            missing.append("순이익")
        if len(periods) < 3 or any(item.operating_cash_flow is None for item in periods):
            missing.append("영업현금흐름")
        if not periods or periods[-1].equity is None:
            missing.append("최신 자본총계")
        if not periods or periods[-1].assets is None:
            missing.append("최신 자산총계")
        if not periods or periods[-1].liabilities is None:
            missing.append("최신 부채총계")
        return missing

    @staticmethod
    def _scores(
        fundamentals: ScreeningFundamentals,
        *,
        revenue_growth: float,
        debt_to_equity: float,
        positive_net_income_years: int,
        positive_cash_flow_years: int,
    ) -> FundamentalScoreBreakdown:
        latest = fundamentals.periods[-1]
        roe = cast(float, latest.net_income) / cast(float, latest.equity)
        quality = _clamp(
            positive_net_income_years / 3 * 25
            + positive_cash_flow_years / 3 * 25
            + _scale(roe, 0, 0.25) * 0.30
            + (100 - _scale(debt_to_equity, 0.5, 3.5)) * 0.20,
        )
        growth = _clamp(_scale(revenue_growth, -0.02, 0.25) * 0.65 + 35)
        valuation_parts: list[float] = []
        if fundamentals.trailing_pe is not None:
            valuation_parts.append(100 - _scale(fundamentals.trailing_pe, 8, 45))
        if fundamentals.price_to_book is not None:
            valuation_parts.append(100 - _scale(fundamentals.price_to_book, 0.8, 8))
        valuation = (
            round(sum(valuation_parts) / len(valuation_parts), 2)
            if valuation_parts
            else None
        )
        weighted = [(quality, 0.65), (growth, 0.25)]
        if valuation is not None:
            weighted.append((valuation, 0.10))
        total_weight = sum(weight for _, weight in weighted)
        total = sum(score * weight for score, weight in weighted) / total_weight
        return FundamentalScoreBreakdown(
            quality=round(quality, 2),
            growth=round(growth, 2),
            valuation=valuation,
            total=round(total, 2),
        )


def _compound_growth(first: float, last: float, years: int) -> float:
    if first <= 0 or last <= 0 or years < 1:
        return -1.0
    return math.pow(last / first, 1 / years) - 1


def _scale(value: float, low: float, high: float) -> float:
    if high <= low:
        raise ValueError("점수 상한은 하한보다 커야 합니다.")
    return _clamp((value - low) / (high - low) * 100)


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))
