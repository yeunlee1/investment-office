# 권리 확인된 공식 거시 수집기의 계산과 차단 정책을 검증한다
from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from investment_office.services.macro_context import (
    BLS_API_URL,
    TREASURY_XML_URL,
    FredMacroContextClient,
    MacroContextError,
    OfficialMacroContextClient,
    build_ecos_unavailable_section,
)
from investment_office.services.research_contracts import (
    PublicationTimeBasis,
    SectionStatus,
)

NOW = datetime(2026, 7, 12, 3, 0, tzinfo=UTC)
JAN_NOW = datetime(2026, 1, 10, 3, 0, tzinfo=UTC)


def _treasury_xml(rows: list[tuple[str, str, str, str]]) -> bytes:
    entries = "".join(
        "<entry><content><m:properties>"
        f"<d:NEW_DATE>{observed_on}T00:00:00</d:NEW_DATE>"
        f"<d:BC_2YEAR>{two_year}</d:BC_2YEAR>"
        f"<d:BC_3YEAR>{three_year}</d:BC_3YEAR>"
        f"<d:BC_10YEAR>{ten_year}</d:BC_10YEAR>"
        "</m:properties></content></entry>"
        for observed_on, two_year, three_year, ten_year in rows
    )
    return (
        '<feed xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" '
        'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">'
        f"{entries}</feed>"
    ).encode()


def _bls_payload() -> bytes:
    return json.dumps(
        {
            "status": "REQUEST_SUCCEEDED",
            "Results": {
                "series": [
                    {
                        "seriesID": "CUSR0000SA0",
                        "data": [
                            {"year": "2026", "period": "M06", "value": "324.1"},
                            {"year": "2025", "period": "M06", "value": "318.0"},
                        ],
                    },
                    {
                        "seriesID": "CUSR0000SA0L1E",
                        "data": [
                            {"year": "2026", "period": "M06", "value": "332.5"},
                            {"year": "2025", "period": "M06", "value": "325.0"},
                        ],
                    },
                    {
                        "seriesID": "LNS14000000",
                        "data": [
                            {"year": "2026", "period": "M06", "value": "4.2"},
                            {"year": "2026", "period": "M05", "value": "4.1"},
                        ],
                    },
                ]
            },
        }
    ).encode()


def _bls_year_boundary_payload() -> bytes:
    return json.dumps(
        {
            "status": "REQUEST_SUCCEEDED",
            "Results": {
                "series": [
                    {
                        "seriesID": "CUSR0000SA0",
                        "data": [
                            {"year": "2025", "period": "M11", "value": "324.1"},
                            {"year": "2024", "period": "M11", "value": "318.0"},
                        ],
                    },
                    {
                        "seriesID": "CUSR0000SA0L1E",
                        "data": [
                            {"year": "2025", "period": "M11", "value": "332.5"},
                            {"year": "2024", "period": "M11", "value": "325.0"},
                        ],
                    },
                    {
                        "seriesID": "LNS14000000",
                        "data": [
                            {"year": "2025", "period": "M12", "value": "4.2"},
                            {"year": "2025", "period": "M11", "value": "4.1"},
                        ],
                    },
                ]
            },
        }
    ).encode()


@pytest.mark.asyncio
async def test_official_client_uses_origin_sources_and_blocks_unlicensed_axes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if str(request.url).startswith(TREASURY_XML_URL):
            year = request.url.params["field_tdr_date_value"]
            rows = (
                [("2026-06-10", "4.10", "4.05", "4.30"), ("2026-07-10", "4.20", "4.15", "4.40")]
                if year == "2026"
                else [("2025-12-31", "4.00", "3.95", "4.20")]
            )
            return httpx.Response(200, content=_treasury_xml(rows), request=request)
        if str(request.url) == BLS_API_URL:
            return httpx.Response(200, content=_bls_payload(), request=request)
        raise AssertionError(f"예상하지 못한 요청입니다. {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await OfficialMacroContextClient(
            client=client,
            now_factory=lambda: NOW,
        ).fetch()

    assert len(requests) == 3
    assert all("fred.stlouisfed.org" not in str(request.url) for request in requests)
    assert {source.source_id for source in result.sources} == {
        "official:us_treasury:yield_curve",
        "official:bls:public_data",
    }
    assert len(result.facts) == 14
    assert all(fact.published_at == NOW for fact in result.facts)
    assert all(
        fact.publication_time_basis is PublicationTimeBasis.RETRIEVAL_TIME_PROXY
        for fact in result.facts
    )
    by_section = {section.section_id: section for section in result.sections}
    assert by_section["macro.rates"].status is SectionStatus.COMPLETE
    assert by_section["macro.growth_inflation"].status is SectionStatus.COMPLETE
    assert by_section["macro.currency"].status is SectionStatus.UNAVAILABLE
    assert by_section["macro.volatility"].status is SectionStatus.UNAVAILABLE
    assert by_section["macro.commodities"].status is SectionStatus.UNAVAILABLE
    assert by_section["macro.liquidity"].status is SectionStatus.UNAVAILABLE
    assert result.stale_fact_ids == ()


@pytest.mark.asyncio
async def test_provider_failure_preserves_other_official_axis() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(TREASURY_XML_URL):
            return httpx.Response(
                200,
                content=_treasury_xml(
                    [("2026-06-10", "4.10", "4.05", "4.30"), ("2026-07-10", "4.20", "4.15", "4.40")]
                ),
                request=request,
            )
        return httpx.Response(503, content=b"unavailable", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await OfficialMacroContextClient(
            client=client,
            now_factory=lambda: NOW,
        ).fetch()

    by_section = {section.section_id: section for section in result.sections}
    assert by_section["macro.rates"].status is SectionStatus.COMPLETE
    assert by_section["macro.growth_inflation"].status is SectionStatus.BLOCKED
    assert any(
        "노동통계국" in reason for reason in by_section["macro.growth_inflation"].blocking_reasons
    )


@pytest.mark.asyncio
async def test_duplicate_treasury_failures_preserve_bls_axis() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(TREASURY_XML_URL):
            return httpx.Response(503, content=b"unavailable", request=request)
        return httpx.Response(200, content=_bls_payload(), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await OfficialMacroContextClient(
            client=client,
            now_factory=lambda: NOW,
        ).fetch()

    by_section = {section.section_id: section for section in result.sections}
    assert by_section["macro.rates"].status is SectionStatus.BLOCKED
    assert len(by_section["macro.rates"].blocking_reasons) == len(
        set(by_section["macro.rates"].blocking_reasons)
    )
    assert by_section["macro.growth_inflation"].status is SectionStatus.COMPLETE
    assert {source.source_id for source in result.sources} == {
        "official:bls:public_data"
    }


@pytest.mark.asyncio
async def test_bls_monthly_baselines_cross_calendar_year_safely() -> None:
    bls_request_body: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(TREASURY_XML_URL):
            return httpx.Response(
                200,
                content=_treasury_xml(
                    [
                        ("2025-11-30", "4.10", "4.05", "4.30"),
                        ("2025-12-31", "4.20", "4.15", "4.40"),
                    ]
                ),
                request=request,
            )
        bls_request_body.update(json.loads(request.content))
        return httpx.Response(
            200,
            content=_bls_year_boundary_payload(),
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await OfficialMacroContextClient(
            client=client,
            now_factory=lambda: JAN_NOW,
        ).fetch()

    assert bls_request_body["startyear"] == "2024"
    growth = next(
        section
        for section in result.sections
        if section.section_id == "macro.growth_inflation"
    )
    assert growth.status is SectionStatus.COMPLETE
    assert len(growth.fact_ids) == 6


@pytest.mark.asyncio
async def test_fred_client_is_disabled_before_network_access() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MacroContextError, match="비활성화"):
            await FredMacroContextClient(client=client).fetch()

    assert calls == 0


@pytest.mark.asyncio
async def test_official_client_rejects_naive_collection_time() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, request=request))
    ) as client:
        with pytest.raises(MacroContextError, match="시간대"):
            await OfficialMacroContextClient(
                client=client,
                now_factory=lambda: datetime(2026, 7, 12),
            ).fetch()


def test_missing_ecos_key_builds_required_unavailable_section() -> None:
    section = build_ecos_unavailable_section(None)

    assert section is not None
    assert section.status is SectionStatus.UNAVAILABLE
    assert section.required is True
    assert build_ecos_unavailable_section("configured") is None
