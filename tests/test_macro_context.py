# FRED 공통 거시 수집기의 값 계산과 품질 차단 정책을 시험한다
from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime

import httpx
import pytest

from investment_office.services.macro_context import (
    FRED_SERIES_IDS,
    FredMacroContextClient,
    MacroContextError,
    build_ecos_unavailable_section,
)
from investment_office.services.research_contracts import (
    PublicationTimeBasis,
    SectionStatus,
)

COLLECTED_AT = datetime(2026, 7, 12, 9, 30, tzinfo=UTC)


def _csv(*rows: tuple[str, list[str]]) -> str:
    header = ",".join(("observation_date", *FRED_SERIES_IDS))
    return "\n".join((header, *(f"{day},{','.join(values)}" for day, values in rows)))


def _values(start: float) -> list[str]:
    return [str(start + index) for index in range(len(FRED_SERIES_IDS))]


def _mock_client(content: str, requests: list[httpx.Request]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=content, request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _mock_binary_client(content: bytes) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_fetch_uses_bounded_official_requests_and_builds_all_sections() -> None:
    content = _csv(
        ("2025-07-10", _values(5)),
        ("2026-06-09", _values(10)),
        ("2026-07-09", _values(20)),
        ("2026-07-10", _values(30)),
    )
    requests: list[httpx.Request] = []
    http_client = _mock_client(content, requests)
    try:
        result = await FredMacroContextClient(
            client=http_client,
            now_factory=lambda: COLLECTED_AT,
        ).fetch()
    finally:
        await http_client.aclose()

    assert len(requests) == 2
    assert all(request.url.host == "fred.stlouisfed.org" for request in requests)
    requested_ids = [
        series_id
        for request in requests
        for series_id in request.url.params["id"].split(",")
    ]
    assert requested_ids == list(FRED_SERIES_IDS)
    assert len(result.sources) == 1
    assert str(result.sources[0].url).startswith("https://fred.stlouisfed.org/")
    assert result.sources[0].retrieved_at == COLLECTED_AT
    assert result.sources[0].content_checksum is not None
    assert len(result.sources[0].content_checksum) == 64
    assert len(result.facts) == len(FRED_SERIES_IDS) * 2
    assert {section.status for section in result.sections} == {SectionStatus.COMPLETE}
    assert [section.section_id for section in result.sections] == [
        "macro.rates",
        "macro.currency",
        "macro.volatility",
        "macro.commodities",
        "macro.liquidity",
        "macro.growth_inflation",
    ]
    assert result.stale_fact_ids == ()
    assert result.future_section_ids == ()

    dgs10_level = next(fact for fact in result.facts if fact.fact_id.endswith("dgs10:level"))
    dgs10_change = next(fact for fact in result.facts if fact.fact_id.endswith("dgs10:change_30d"))
    assert dgs10_level.value == 36.0
    assert dgs10_level.observed_at == datetime(2026, 7, 10, tzinfo=UTC)
    assert dgs10_level.collected_at == COLLECTED_AT
    assert dgs10_level.publication_time_basis is PublicationTimeBasis.OBSERVATION_DATE_PROXY
    assert dgs10_change.value == 20.0
    assert dgs10_change.unit == "percentage_point"


@pytest.mark.asyncio
async def test_fetch_merges_official_multi_series_zip_response() -> None:
    first_ids = FRED_SERIES_IDS[:4]
    second_ids = FRED_SERIES_IDS[4:]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "daily-one.csv",
            "observation_date,"
            + ",".join(first_ids)
            + "\n2025-07-10,1,2,3,4\n2026-06-10,1,2,3,4\n"
            + "2026-07-10,5,6,7,8\n",
        )
        archive.writestr(
            "daily-two.csv",
            "observation_date,"
            + ",".join(second_ids)
            + "\n2025-07-10,1,2,3,4,5,6,7,8,9,10,11,12,13\n"
            + "2026-06-10,1,2,3,4,5,6,7,8,9,10,11,12,13\n"
            + "2026-07-10,5,6,7,8,9,10,11,12,13,14,15,16,17\n",
        )
        archive.writestr("README.txt", "설명")
    http_client = _mock_binary_client(buffer.getvalue())
    try:
        result = await FredMacroContextClient(
            client=http_client,
            now_factory=lambda: COLLECTED_AT,
        ).fetch()
    finally:
        await http_client.aclose()

    assert len(result.facts) == len(FRED_SERIES_IDS) * 2
    assert {section.status for section in result.sections} == {SectionStatus.COMPLETE}


@pytest.mark.asyncio
async def test_missing_series_and_baseline_are_explicitly_partial_or_blocked() -> None:
    latest = _values(30)
    latest[FRED_SERIES_IDS.index("DGS3")] = "."
    content = _csv(("2026-07-10", latest))
    requests: list[httpx.Request] = []
    http_client = _mock_client(content, requests)
    try:
        result = await FredMacroContextClient(
            client=http_client,
            now_factory=lambda: COLLECTED_AT,
        ).fetch()
    finally:
        await http_client.aclose()

    sections = {section.section_id: section for section in result.sections}
    assert sections["macro.rates"].status is SectionStatus.PARTIAL
    assert any("DGS3 최신 유효값" in gap for gap in sections["macro.rates"].data_gaps)
    assert any("30일 변화 기준값" in gap for gap in sections["macro.currency"].data_gaps)
    assert sections["macro.volatility"].status is SectionStatus.PARTIAL
    assert sections["macro.liquidity"].status is SectionStatus.PARTIAL

    all_missing = _csv(("2026-07-10", ["."] * len(FRED_SERIES_IDS)))
    blocked_client = _mock_client(all_missing, [])
    try:
        blocked = await FredMacroContextClient(
            client=blocked_client,
            now_factory=lambda: COLLECTED_AT,
        ).fetch()
    finally:
        await blocked_client.aclose()
    assert {section.status for section in blocked.sections} == {SectionStatus.BLOCKED}
    assert all(section.blocking_reasons for section in blocked.sections)


@pytest.mark.asyncio
async def test_stale_latest_values_block_sections_and_identify_stale_facts() -> None:
    content = _csv(
        ("2026-05-31", _values(10)),
        ("2026-07-01", _values(20)),
    )
    requests: list[httpx.Request] = []
    http_client = _mock_client(content, requests)
    try:
        result = await FredMacroContextClient(
            client=http_client,
            now_factory=lambda: datetime(2026, 10, 20, tzinfo=UTC),
        ).fetch()
    finally:
        await http_client.aclose()

    assert {section.status for section in result.sections} == {SectionStatus.BLOCKED}
    assert len(result.stale_fact_ids) == len(result.facts)
    assert all(
        "허용 수명" in reason for section in result.sections for reason in section.blocking_reasons
    )


def test_ecos_policy_marks_missing_key_unavailable() -> None:
    section = build_ecos_unavailable_section("  ")

    assert section is not None
    assert section.section_id == "macro.kr.ecos"
    assert section.status is SectionStatus.UNAVAILABLE
    assert section.required is True
    assert "ECOS API 키" in section.blocking_reasons[0]
    assert build_ecos_unavailable_section("configured-key") is None


@pytest.mark.asyncio
async def test_invalid_csv_is_reported_without_falling_back_to_network() -> None:
    requests: list[httpx.Request] = []
    http_client = _mock_client("not_a_date,VIXCLS\n2026-07-10,20", requests)
    try:
        with pytest.raises(MacroContextError, match="관측일 열"):
            await FredMacroContextClient(
                client=http_client,
                now_factory=lambda: COLLECTED_AT,
            ).fetch()
    finally:
        await http_client.aclose()

    assert len(requests) == 2
