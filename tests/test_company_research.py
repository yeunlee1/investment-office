# SEC와 DART 회사 연구 수집기의 공식 자료 계약과 계산 공백을 시험한다
from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Final

import httpx
import pytest

from investment_office.services.company_research import (
    DART_CORP_CODE_URL,
    DART_FINANCIAL_URL,
    DART_LIST_URL,
    FUNDAMENTAL_SECTION_ID,
    OFFICIAL_NEWS_SECTION_ID,
    OfficialCompanyResearchClient,
    calculate_valuation_metrics,
)
from investment_office.services.research_contracts import (
    InstrumentRef,
    MarketId,
    SectionStatus,
)

NOW: Final = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def _us_instrument() -> InstrumentRef:
    return InstrumentRef(
        market=MarketId.US,
        symbol="AAPL",
        name="Apple",
        exchange="NASDAQ",
        currency="USD",
    )


def _kr_instrument() -> InstrumentRef:
    return InstrumentRef(
        market=MarketId.KR,
        symbol="005930",
        name="삼성전자",
        exchange="KRX",
        currency="KRW",
    )


def _sec_company_facts() -> dict[str, object]:
    tags = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": ("USD", 1000),
        "OperatingIncomeLoss": ("USD", 200),
        "NetIncomeLoss": ("USD", 150),
        "StockholdersEquity": ("USD", 800),
        "Assets": ("USD", 2000),
        "Liabilities": ("USD", 1200),
        "EarningsPerShareDiluted": ("USD/shares", 1.5),
        "NetCashProvidedByUsedInOperatingActivities": ("USD", 300),
        "PaymentsToAcquirePropertyPlantAndEquipment": ("USD", 75),
    }
    facts: dict[str, object] = {}
    for tag, (unit, value) in tags.items():
        facts[tag] = {
            "units": {
                unit: [
                    {
                        "end": "2025-09-30",
                        "filed": "2025-10-31",
                        "form": "10-Q",
                        "val": value,
                    },
                    {
                        "end": "2025-12-31",
                        "filed": "2026-02-01",
                        "form": "10-K",
                        "val": value * 10,
                    },
                ]
            }
        }
    return {"facts": {"us-gaap": facts}}


def _sec_submissions() -> dict[str, object]:
    return {
        "filings": {
            "recent": {
                "form": ["10-K", "10-Q", "8-K", "4", "10-K"],
                "accessionNumber": [
                    "0001-25-000001",
                    "0001-25-000002",
                    "0001-25-000003",
                    "0001-25-000004",
                    "0001-26-000005",
                ],
                "filingDate": [
                    "2025-02-01",
                    "2025-05-01",
                    "2025-12-01",
                    "2025-12-02",
                    "2026-02-01",
                ],
                "primaryDocument": [
                    "annual.htm",
                    "quarterly.htm",
                    "current.htm",
                    "ownership.htm",
                    "future.htm",
                ],
            }
        }
    }


def _dart_corp_code_archive() -> bytes:
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<result>
  <list><corp_code>00126380</corp_code><corp_name>Samsung</corp_name><stock_code>005930</stock_code></list>
</result>"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("CORPCODE.xml", xml)
    return buffer.getvalue()


def _dart_financials() -> dict[str, object]:
    accounts = {
        "매출액": "1,000,000",
        "영업이익": "200,000",
        "당기순이익": "150,000",
        "자본총계": "800,000",
        "자산총계": "2,000,000",
        "부채총계": "1,200,000",
        "희석주당이익": "1,500",
        "영업활동현금흐름": "300,000",
        "유형자산의 취득": "(75,000)",
    }
    return {
        "status": "000",
        "message": "정상",
        "list": [
            {
                "account_nm": account_name,
                "thstrm_amount": amount,
                "thstrm_dt": "2024.01.01 ~ 2024.12.31",
                "rcept_no": "20250318000123",
            }
            for account_name, amount in accounts.items()
        ],
    }


@pytest.mark.parametrize(
    ("instrument", "reason"),
    [
        (_us_instrument(), "SEC User-Agent"),
        (_kr_instrument(), "OpenDART 인증키"),
    ],
)
async def test_missing_official_access_returns_explicit_unavailable_sections_without_network(
    instrument: InstrumentRef,
    reason: str,
) -> None:
    def reject_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"네트워크 요청이 발생했습니다. {request.url}")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(reject_network))
    client = OfficialCompanyResearchClient(
        client=http_client,
        now_factory=lambda: NOW,
    )

    try:
        result = await client.fetch(instrument, cutoff=NOW - timedelta(minutes=1))
    finally:
        await http_client.aclose()

    assert result.sources == ()
    assert result.facts == ()
    assert {section.section_id for section in result.sections} == {
        FUNDAMENTAL_SECTION_ID,
        OFFICIAL_NEWS_SECTION_ID,
    }
    assert all(section.status is SectionStatus.UNAVAILABLE for section in result.sections)
    assert all(reason in section.blocking_reasons[0] for section in result.sections)


async def test_sec_collects_cutoff_safe_financials_and_recent_filing_metadata() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/files/company_tickers.json":
            payload: object = {
                "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}
            }
        elif request.url.path.endswith("/api/xbrl/companyfacts/CIK0000320193.json"):
            payload = _sec_company_facts()
        elif request.url.path.endswith("/submissions/CIK0000320193.json"):
            payload = _sec_submissions()
        else:
            return httpx.Response(404, request=request)
        return httpx.Response(200, json=payload, request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OfficialCompanyResearchClient(
        sec_user_agent="Investment Office research@example.com",
        client=http_client,
        now_factory=lambda: NOW,
    )
    try:
        result = await client.fetch(_us_instrument(), cutoff=NOW)
    finally:
        await http_client.aclose()

    assert len(requests) == 3
    assert all(
        request.headers["user-agent"] == "Investment Office research@example.com"
        for request in requests
    )
    fundamental = next(
        section for section in result.sections if section.section_id == FUNDAMENTAL_SECTION_ID
    )
    official_news = next(
        section for section in result.sections if section.section_id == OFFICIAL_NEWS_SECTION_ID
    )
    assert fundamental.status is SectionStatus.COMPLETE
    assert len(fundamental.fact_ids) == 9
    assert official_news.status is SectionStatus.PARTIAL
    assert len(official_news.fact_ids) == 3
    assert any("메타데이터" in gap for gap in official_news.data_gaps)
    revenue = next(fact for fact in result.facts if fact.fact_id == "sec:aapl:revenue")
    assert revenue.value == 1000
    assert revenue.published_at <= NOW
    assert all("ownership" not in fact.metric for fact in result.facts)
    assert all("future" not in fact.metric for fact in result.facts)


async def test_dart_calls_official_contracts_and_collects_only_metadata() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if str(request.url.copy_with(query=None)) == DART_CORP_CODE_URL:
            return httpx.Response(200, content=_dart_corp_code_archive(), request=request)
        if str(request.url.copy_with(query=None)) == DART_LIST_URL:
            return httpx.Response(
                200,
                json={
                    "status": "000",
                    "message": "정상",
                    "list": [
                        {
                            "rcept_no": "20250318000123",
                            "rcept_dt": "20250318",
                            "report_nm": "사업보고서 (2024.12)",
                        },
                        {
                            "rcept_no": "20260201000456",
                            "rcept_dt": "20260201",
                            "report_nm": "미래 공시",
                        },
                    ],
                },
                request=request,
            )
        if str(request.url.copy_with(query=None)) == DART_FINANCIAL_URL:
            return httpx.Response(200, json=_dart_financials(), request=request)
        return httpx.Response(404, request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OfficialCompanyResearchClient(
        dart_api_key="secret-dart-key",
        client=http_client,
        now_factory=lambda: NOW,
    )
    try:
        result = await client.fetch(_kr_instrument(), cutoff=NOW, business_year=2024)
    finally:
        await http_client.aclose()

    assert len(requests) == 3
    assert requests[0].url.params["crtfc_key"] == "secret-dart-key"
    assert requests[1].url.params["corp_code"] == "00126380"
    assert requests[1].url.params["end_de"] == "20260115"
    assert requests[2].url.params["bsns_year"] == "2024"
    assert requests[2].url.params["reprt_code"] == "11011"
    assert requests[2].url.params["fs_div"] == "CFS"
    assert all("secret-dart-key" not in str(source.url) for source in result.sources)

    fundamental = next(
        section for section in result.sections if section.section_id == FUNDAMENTAL_SECTION_ID
    )
    official_news = next(
        section for section in result.sections if section.section_id == OFFICIAL_NEWS_SECTION_ID
    )
    assert fundamental.status is SectionStatus.COMPLETE
    assert len(fundamental.fact_ids) == 9
    assert official_news.status is SectionStatus.PARTIAL
    assert len(official_news.fact_ids) == 1
    assert any("메타데이터" in gap for gap in official_news.data_gaps)
    capex = next(fact for fact in result.facts if fact.fact_id.endswith(":capital_expenditure"))
    assert capex.value == -75_000
    disclosure = next(fact for fact in result.facts if ":filing:" in fact.fact_id)
    assert disclosure.value == "20250318000123"
    assert "사업보고서" in disclosure.metric
    assert not hasattr(disclosure, "body")


def test_valuation_metrics_calculate_only_with_sufficient_inputs() -> None:
    complete = calculate_valuation_metrics(
        price=50,
        shares_outstanding=10,
        ttm_net_income=25,
        average_equity=200,
        average_assets=500,
        book_equity=250,
    )

    assert complete.per == 20
    assert complete.roe_pct == 12.5
    assert complete.roa_pct == 5
    assert complete.pbr == 2
    assert complete.data_gaps == ()

    incomplete = calculate_valuation_metrics(
        price=50,
        shares_outstanding=None,
        ttm_net_income=-10,
        average_equity=None,
        average_assets=500,
        book_equity=None,
    )

    assert incomplete.per is None
    assert incomplete.roe_pct is None
    assert incomplete.roa_pct == -2
    assert incomplete.pbr is None
    assert len(incomplete.data_gaps) == 3
    assert any("PER" in gap for gap in incomplete.data_gaps)
    assert any("ROE" in gap for gap in incomplete.data_gaps)
    assert any("PBR" in gap for gap in incomplete.data_gaps)
