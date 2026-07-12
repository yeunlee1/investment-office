# 미국·한국 공식 대량 재무 응답의 3개년 변환과 설정 차단을 검증한다.
from __future__ import annotations

import io
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from investment_office.services.bulk_fundamentals import (
    DART_BULK_LIST_URL,
    DART_BULK_MAIN_URL,
    BulkFundamentalsConfigurationError,
    BulkFundamentalsSourceError,
    DartMultiCompanyBulkProvider,
    UnavailableBulkFundamentalsProvider,
    _parse_dart_bulk_listing,
    _parse_dart_bulk_zip,
    _parse_dart_rows,
    _parse_sec_company_facts,
)
from investment_office.services.research_contracts import MarketId
from investment_office.services.universe_catalog import (
    UniverseCatalogMember,
    UniverseSnapshot,
    UniverseTier,
)


def us_member() -> UniverseCatalogMember:
    return UniverseCatalogMember(
        market=MarketId.US,
        ticker="GOOD",
        company_name="Good Company",
        exchange="Nasdaq",
        issuer_id="sec:0000000123",
        cik=123,
        tiers=(UniverseTier.CORE, UniverseTier.GROWTH),
        industry="technology",
    )


def kr_member() -> UniverseCatalogMember:
    return UniverseCatalogMember(
        market=MarketId.KR,
        ticker="005930",
        company_name="삼성전자",
        exchange="KOSPI",
        issuer_id="krx:005930",
        tiers=(UniverseTier.CORE,),
        industry="통신 및 방송 장비 제조업",
    )


def snapshot(member: UniverseCatalogMember) -> UniverseSnapshot:
    return UniverseSnapshot(
        market=member.market,
        provider_id="test",
        source_url="https://example.com/source",
        source_documentation_url="https://example.com/guide",
        source_urls=("https://example.com/source",),
        retrieved_at=datetime(2026, 7, 13, tzinfo=UTC),
        members=(member,),
        raw_count=1,
        excluded_count=0,
        duplicate_count=0,
    )


def sec_fact(
    values: tuple[int, int, int],
    *,
    form: str = "10-K",
    currency: str = "USD",
) -> dict[str, object]:
    return {
        "units": {
            currency: [
                {
                    "end": f"{year}-12-31",
                    "filed": f"{year + 1}-02-20",
                    "form": form,
                    "fp": "FY",
                    "val": value,
                }
                for year, value in zip((2023, 2024, 2025), values, strict=True)
            ]
        }
    }


def dart_bulk_zip(rows: list[list[str]]) -> bytes:
    header = [
        "재무제표종류",
        "종목코드",
        "회사명",
        "시장구분",
        "업종",
        "업종명",
        "결산월",
        "결산기준일",
        "보고서종류",
        "통화",
        "항목코드",
        "항목명",
        "당기",
        "",
        "전기",
        "전전기",
        "",
    ]
    text = "\n".join("\t".join(row) for row in [header, *rows])
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("재무정보.txt", text.encode("cp949"))
    return buffer.getvalue()


def dart_compact_bulk_zip(rows: list[list[str]]) -> bytes:
    header = [
        "재무제표종류",
        "종목코드",
        "회사명",
        "시장구분",
        "업종",
        "업종명",
        "결산월",
        "결산기준일",
        "보고서종류",
        "통화",
        "항목코드",
        "항목명",
        "당기",
        "전기",
        "전전기",
    ]
    compact_rows = [row[:13] + row[14:16] for row in rows]
    text = "\n".join("\t".join(row) for row in [header, *compact_rows])
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("재무정보.txt", text.encode("cp949"))
    return buffer.getvalue()


def dart_expanded_bulk_zip(rows: list[list[str]]) -> bytes:
    header = [
        "재무제표종류",
        "종목코드",
        "회사명",
        "시장구분",
        "업종",
        "업종명",
        "결산월",
        "결산기준일",
        "보고서종류",
        "통화",
        "항목코드",
        "항목명",
        "",
        "당기",
        "",
        "",
        "전기",
        "전전기",
        "",
    ]
    expanded_rows = [
        row[:12] + ["", row[12], "", "", row[14], row[15]] for row in rows
    ]
    text = "\n".join("\t".join(row) for row in [header, *expanded_rows])
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("재무정보.txt", text.encode("cp949"))
    return buffer.getvalue()


def dart_row(
    statement: str,
    account: str,
    values: tuple[int, int, int],
    *,
    account_id: str = "ifrs_Test",
) -> list[str]:
    oldest, previous, current = values
    return [
        statement,
        "[005930]",
        "삼성전자",
        "유가증권시장상장법인",
        "264",
        "통신 및 방송 장비 제조업",
        "12",
        "2025-12-31",
        "사업보고서",
        "KRW",
        account_id,
        account,
        str(current),
        "",
        str(previous),
        str(oldest),
        "",
    ]


def dart_listing(*years: int) -> str:
    return "\n".join(
        f"download_ext002('{year}','FY', '{statement}', "
        f"'{year}_4Q_{statement}_test.zip');"
        for year in years or (2025,)
        for statement in ("BS", "PL", "CF")
    )


def dart_archives(year: int = 2025) -> dict[str, bytes]:
    return {
        f"{year}_4Q_BS_test.zip": dart_bulk_zip(
            [
                dart_row("연결 재무상태표", "자본총계", (60, 70, 82)),
                dart_row("연결 재무상태표", "자산총계", (140, 155, 180)),
                dart_row("연결 재무상태표", "부채총계", (80, 85, 98)),
            ]
        ),
        f"{year}_4Q_PL_test.zip": dart_bulk_zip(
            [
                dart_row("연결 손익계산서", "매출액", (100, 120, 145)),
                dart_row("연결 손익계산서", "영업이익", (12, 15, 19)),
                dart_row("연결 손익계산서", "당기순이익", (9, 11, 14)),
            ]
        ),
        f"{year}_4Q_CF_test.zip": dart_bulk_zip(
            [
                dart_row("현금흐름표 - 별도재무제표", "영업활동현금흐름", (1, 1, 1)),
                dart_row("연결 현금흐름표", "영업활동현금흐름", (13, 16, 20)),
                dart_row("연결 현금흐름표", "유형자산의 취득", (3, 4, 5)),
            ]
        ),
    }


def test_sec_company_facts_are_aligned_into_three_annual_periods() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": sec_fact((100, 120, 145)),
                "OperatingIncomeLoss": sec_fact((12, 15, 19)),
                "NetIncomeLoss": sec_fact((9, 11, 14)),
                "NetCashProvidedByUsedInOperatingActivities": sec_fact((13, 16, 20)),
                "PaymentsToAcquirePropertyPlantAndEquipment": sec_fact((3, 4, 5)),
                "StockholdersEquity": sec_fact((60, 70, 82)),
                "Assets": sec_fact((140, 155, 180)),
                "Liabilities": sec_fact((80, 85, 98)),
            }
        }
    }

    result = _parse_sec_company_facts(payload, us_member())

    assert result is not None
    assert [period.fiscal_year for period in result.periods] == [2023, 2024, 2025]
    assert result.periods[-1].free_cash_flow == 15
    assert result.latest_report_date.isoformat() == "2026-02-20"


def test_sec_ifrs_company_facts_support_foreign_issuers_and_non_usd_units() -> None:
    payload = {
        "facts": {
            "ifrs-full": {
                "Revenue": sec_fact((100, 120, 145), form="20-F", currency="GBP"),
                "ProfitLossFromOperatingActivities": sec_fact(
                    (12, 15, 19), form="20-F", currency="GBP"
                ),
                "ProfitLoss": sec_fact((9, 11, 14), form="20-F", currency="GBP"),
                "CashFlowsFromUsedInOperatingActivities": sec_fact(
                    (13, 16, 20), form="20-F", currency="GBP"
                ),
                "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": sec_fact(
                    (3, 4, 5), form="20-F", currency="GBP"
                ),
                "Equity": sec_fact((60, 70, 82), form="20-F", currency="GBP"),
                "Assets": sec_fact((140, 155, 180), form="20-F", currency="GBP"),
                "Liabilities": sec_fact((80, 85, 98), form="20-F", currency="GBP"),
            }
        }
    }

    result = _parse_sec_company_facts(payload, us_member())

    assert result is not None
    assert result.currency == "GBP"
    assert [period.revenue for period in result.periods] == [100, 120, 145]
    assert result.periods[-1].operating_cash_flow == 20
    assert result.periods[-1].free_cash_flow == 15


def test_dart_prefers_consolidated_rows_and_builds_prior_years() -> None:
    rows: list[dict[str, object]] = []
    accounts = {
        "매출액": (100, 120, 145),
        "영업이익": (12, 15, 19),
        "당기순이익": (9, 11, 14),
        "영업활동현금흐름": (13, 16, 20),
        "자본총계": (60, 70, 82),
        "자산총계": (140, 155, 180),
        "부채총계": (80, 85, 98),
    }
    for account, values in accounts.items():
        rows.append(
            {
                "stock_code": "005930",
                "fs_div": "CFS",
                "account_nm": account,
                "bfefrmtrm_amount": str(values[0]),
                "frmtrm_amount": str(values[1]),
                "thstrm_amount": str(values[2]),
            }
        )
    rows.append(
        {
            "stock_code": "005930",
            "fs_div": "OFS",
            "account_nm": "매출액",
            "thstrm_amount": "1",
        }
    )

    result = _parse_dart_rows(rows, [kr_member()], 2025)

    assert len(result) == 1
    assert [period.revenue for period in result[0].periods] == [100, 120, 145]
    assert result[0].latest_report_date.isoformat() == "2026-03-31"


@pytest.mark.asyncio
async def test_unavailable_provider_blocks_price_only_recommendation() -> None:
    provider = UnavailableBulkFundamentalsProvider(
        MarketId.KR,
        "OpenDART 키가 없어 재무 검증을 시작할 수 없습니다.",
    )

    with pytest.raises(BulkFundamentalsConfigurationError, match="재무 검증"):
        await provider.fetch_many(snapshot(kr_member()))


def test_corp_code_fixture_is_a_valid_zip_for_provider_tests() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "CORPCODE.xml",
            "<result><list><corp_code>00126380</corp_code>"
            "<stock_code>005930</stock_code></list></result>",
        )

    assert zipfile.is_zipfile(io.BytesIO(buffer.getvalue()))


def test_dart_bulk_listing_uses_latest_complete_annual_bundle() -> None:
    html = "\n".join(
        (
            dart_listing(),
            "download_ext002('2026','FY', 'BS', '2026_BS.zip');",
            "download_ext002('2026','FY', 'PL', '2026_PL.zip');",
        )
    )

    candidates = _parse_dart_bulk_listing(
        html,
        2026,
        as_of_date=date(2026, 7, 13),
    )

    year, files = candidates[0]
    assert year == 2025
    assert files == {
        "BS": "2025_4Q_BS_test.zip",
        "PL": "2025_4Q_PL_test.zip",
        "CF": "2025_4Q_CF_test.zip",
    }


def test_dart_bulk_zip_accepts_current_compact_amount_columns() -> None:
    rows = _parse_dart_bulk_zip(
        dart_compact_bulk_zip(
            [dart_row("연결 재무상태표", "자본총계", (60, 70, 82))]
        ),
        file_name="2025_4Q_BS_test.zip",
        content_type="application/x-stuff;charset=UTF-8",
    )

    assert rows[0]["thstrm_amount"] == "82"
    assert rows[0]["frmtrm_amount"] == "70"
    assert rows[0]["bfefrmtrm_amount"] == "60"


def test_dart_bulk_zip_accepts_expanded_income_statement_columns() -> None:
    rows = _parse_dart_bulk_zip(
        dart_expanded_bulk_zip(
            [dart_row("연결 손익계산서", "매출액", (100, 120, 145))]
        ),
        file_name="2025_4Q_PL_test.zip",
        content_type="application/x-stuff;charset=UTF-8",
    )

    assert rows[0]["thstrm_amount"] == "145"
    assert rows[0]["frmtrm_amount"] == "120"
    assert rows[0]["bfefrmtrm_amount"] == "100"


@pytest.mark.asyncio
async def test_dart_bulk_provider_enriches_cash_flow_with_five_public_requests(
    tmp_path: Path,
) -> None:
    archives = dart_archives()
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if str(request.url.copy_with(query=None)) == DART_BULK_MAIN_URL:
            return httpx.Response(200, text="<html>세션 준비</html>", request=request)
        assert "Chrome/138.0" in request.headers["User-Agent"]
        assert request.headers["Referer"] == DART_BULK_MAIN_URL
        if str(request.url.copy_with(query=None)) == DART_BULK_LIST_URL:
            return httpx.Response(200, text=dart_listing(), request=request)
        file_name = request.url.params.get("fl_nm")
        return httpx.Response(200, content=archives[file_name], request=request)

    progress_updates: list[tuple[int, int, int]] = []

    async def progress(total: int, processed: int, cached: int) -> None:
        progress_updates.append((total, processed, cached))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = DartMultiCompanyBulkProvider(
            cache_path=tmp_path / "dart.json",
            fiscal_year=2025,
            client=client,
            now_factory=lambda: datetime(2026, 7, 13, tzinfo=UTC),
        )
        result = await provider.fetch_many(snapshot(kr_member()), progress=progress)
        cached = await provider.fetch_many(snapshot(kr_member()), progress=progress)

    assert len(requested) == 5
    assert requested[0].startswith(DART_BULK_MAIN_URL)
    assert result.cache_hit is False
    assert cached.cache_hit is True
    assert [period.operating_cash_flow for period in result.items[0].periods] == [13, 16, 20]
    assert [period.free_cash_flow for period in result.items[0].periods] == [10, 12, 15]
    assert len(result.source_urls) == 5
    assert progress_updates[0] == (6, 1, 0)
    assert (6, 6, 0) in progress_updates
    assert progress_updates[-1] == (1, 1, 1)


@pytest.mark.asyncio
async def test_dart_bulk_provider_falls_back_to_previous_fresh_complete_year(
    tmp_path: Path,
) -> None:
    archives = {**dart_archives(2025), **dart_archives(2024)}
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if str(request.url.copy_with(query=None)) == DART_BULK_MAIN_URL:
            return httpx.Response(200, text="<html>세션 준비</html>", request=request)
        if str(request.url.copy_with(query=None)) == DART_BULK_LIST_URL:
            return httpx.Response(200, text=dart_listing(2025, 2024), request=request)
        file_name = request.url.params.get("fl_nm")
        if file_name == "2025_4Q_CF_test.zip":
            return httpx.Response(
                200,
                content=b"x" * 975,
                headers={"Content-Type": "text/html; charset=utf-8"},
                request=request,
            )
        return httpx.Response(200, content=archives[file_name], request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = DartMultiCompanyBulkProvider(
            cache_path=tmp_path / "dart.json",
            fiscal_year=2025,
            client=client,
            now_factory=lambda: datetime(2026, 7, 13, tzinfo=UTC),
        )
        result = await provider.fetch_many(snapshot(kr_member()))

    assert len(requested) == 8
    assert len(result.items) == 1
    assert result.items[0].latest_report_date.isoformat() == "2025-03-31"
    assert [period.operating_cash_flow for period in result.items[0].periods] == [13, 16, 20]
    assert any("이전 신선 연도" in warning for warning in result.warnings)
    assert any("2025_4Q_CF_test.zip" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_dart_bulk_provider_reports_every_fresh_year_failure(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url.copy_with(query=None)) == DART_BULK_MAIN_URL:
            return httpx.Response(200, text="<html>세션 준비</html>", request=request)
        if str(request.url.copy_with(query=None)) == DART_BULK_LIST_URL:
            return httpx.Response(200, text=dart_listing(2025, 2024), request=request)
        return httpx.Response(
            200,
            content=b"x" * 975,
            headers={"Content-Type": "text/html; charset=utf-8"},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = DartMultiCompanyBulkProvider(
            cache_path=tmp_path / "dart.json",
            fiscal_year=2025,
            client=client,
            now_factory=lambda: datetime(2026, 7, 13, tzinfo=UTC),
        )
        with pytest.raises(BulkFundamentalsSourceError) as error:
            await provider.fetch_many(snapshot(kr_member()))

    detail = str(error.value)
    assert "2025년" in detail
    assert "2024년" in detail
    assert "2025_4Q_CF_test.zip" in detail
    assert "Content-Type text/html; charset=utf-8" in detail
    assert "975바이트" in detail
