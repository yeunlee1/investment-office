# 전체시장 재무 하드게이트의 자료 충분성, 산업 분리와 위험성향 규칙을 검증한다.
from __future__ import annotations

from datetime import date

from investment_office.services.fundamental_screening import (
    AnnualFundamentals,
    FundamentalGate,
    FundamentalGateProfile,
    FundamentalGateStatus,
    IndustryModel,
    ScreeningFundamentals,
)
from investment_office.services.research_contracts import MarketId


def company(
    *,
    model: IndustryModel = IndustryModel.GENERAL,
    liabilities: float = 90,
    revenue: tuple[float, float, float] = (100, 112, 126),
    net_income: tuple[float, float, float] = (8, 10, 12),
    cash_flow: tuple[float, float, float] = (10, 12, 14),
) -> ScreeningFundamentals:
    periods = tuple(
        AnnualFundamentals(
            fiscal_year=year,
            revenue=revenue[index],
            operating_income=net_income[index] * 1.4,
            net_income=net_income[index],
            operating_cash_flow=cash_flow[index],
            free_cash_flow=cash_flow[index] * 0.7,
            equity=100,
            assets=100 + liabilities,
            liabilities=liabilities,
        )
        for index, year in enumerate((2023, 2024, 2025))
    )
    return ScreeningFundamentals(
        market=MarketId.US,
        ticker="GOOD",
        company_name="튼튼한 회사",
        sector="산업재",
        industry_model=model,
        currency="USD",
        periods=periods,
        latest_report_date=date(2026, 2, 20),
        source_urls=("https://www.sec.gov/",),
        trailing_pe=18,
        price_to_book=2.2,
    )


def test_profitable_cash_generating_company_passes_with_scores() -> None:
    result = FundamentalGate().evaluate(
        company(),
        FundamentalGateProfile.BALANCED,
        as_of_date=date(2026, 7, 13),
    )

    assert result.status is FundamentalGateStatus.PASSED
    assert result.passed is True
    assert result.scores is not None
    assert 0 < result.scores.quality <= 100
    assert 0 < result.scores.growth <= 100
    assert result.scores.valuation is not None


def test_missing_values_are_insufficient_instead_of_zero_scored() -> None:
    incomplete = company().model_copy(
        update={
            "periods": (
                AnnualFundamentals(fiscal_year=2024, revenue=100),
                AnnualFundamentals(fiscal_year=2025, revenue=110),
            )
        }
    )

    result = FundamentalGate().evaluate(
        incomplete,
        "balanced",
        as_of_date=date(2026, 7, 13),
    )

    assert result.status is FundamentalGateStatus.INSUFFICIENT_DATA
    assert result.scores is None
    assert "최근 3개 사업연도" in result.missing_fields
    assert "영업현금흐름" in result.missing_fields


def test_financial_companies_are_sent_to_special_review_without_general_debt_rule() -> None:
    result = FundamentalGate().evaluate(
        company(model=IndustryModel.FINANCIAL, liabilities=1_200),
        "defensive",
        as_of_date=date(2026, 7, 13),
    )

    assert result.status is FundamentalGateStatus.SPECIAL_REVIEW
    assert result.passed is False
    assert all("부채비율" not in reason for reason in result.reasons)


def test_aggressive_profile_keeps_profit_and_cash_flow_gate() -> None:
    result = FundamentalGate().evaluate(
        company(
            revenue=(100, 130, 170),
            net_income=(4, -2, -3),
            cash_flow=(5, -1, -2),
        ),
        "aggressive",
        as_of_date=date(2026, 7, 13),
    )

    assert result.status is FundamentalGateStatus.EXCLUDED
    assert result.passed is False
    assert any("순이익" in reason for reason in result.reasons)
    assert any("영업현금흐름" in reason for reason in result.reasons)


def test_profile_changes_debt_tolerance_but_not_other_hard_gates() -> None:
    defensive = FundamentalGate().evaluate(
        company(liabilities=200),
        "defensive",
        as_of_date=date(2026, 7, 13),
    )
    aggressive = FundamentalGate().evaluate(
        company(liabilities=200, revenue=(100, 120, 145)),
        "aggressive",
        as_of_date=date(2026, 7, 13),
    )

    assert defensive.status is FundamentalGateStatus.EXCLUDED
    assert aggressive.status is FundamentalGateStatus.PASSED
