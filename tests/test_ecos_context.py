# 한국은행 ECOS 거시 수집기의 공식 코드와 실패 차단 정책을 시험한다
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from investment_office.services.ecos_context import (
    ECOS_OPEN_API_URL,
    ECOS_SERIES,
    ECOS_STATISTIC_ITEM_LIST_URL,
    ECOS_STATISTIC_SEARCH_URL,
    EcosMacroContextClient,
)
from investment_office.services.research_contracts import SectionStatus

COLLECTED_AT = datetime(2026, 7, 12, 9, 30, tzinfo=UTC)
API_KEY = "secretKey123"


def _payload(
    stat_code: str,
    item_code: str,
    *values: tuple[str, str],
) -> dict[str, Any]:
    return {
        "StatisticSearch": {
            "list_total_count": len(values),
            "row": [
                {
                    "STAT_CODE": stat_code,
                    "ITEM_CODE1": item_code,
                    "TIME": period,
                    "DATA_VALUE": value,
                }
                for period, value in values
            ],
        }
    }


def _periods(slug: str) -> tuple[tuple[str, str], ...]:
    if slug == "cpi":
        return (("202605", "117.9"), ("202606", "118.2"))
    return (("20260701", "3.1"), ("20260710", "3.2"))


def _mock_client(
    requests: list[httpx.Request],
    override: Callable[[httpx.Request, str], httpx.Response | None] | None = None,
) -> httpx.AsyncClient:
    by_path = {
        (spec.stat_code, spec.item_code): spec
        for spec in ECOS_SERIES
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        matched = next(
            (
                spec
                for (stat_code, item_code), spec in by_path.items()
                if f"/{stat_code}/{spec.cycle}/" in request.url.path
                and request.url.path.endswith(f"/{item_code}/")
            ),
            None,
        )
        if matched is None:
            return httpx.Response(404, request=request)
        if override is not None:
            custom = override(request, matched.slug)
            if custom is not None:
                return custom
        return httpx.Response(
            200,
            json=_payload(
                matched.stat_code,
                matched.item_code,
                *_periods(matched.slug),
            ),
            request=request,
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_official_codes_are_locked_to_verified_ecos_metadata() -> None:
    assert ECOS_STATISTIC_SEARCH_URL == "https://ecos.bok.or.kr/api/StatisticSearch"
    assert ECOS_STATISTIC_ITEM_LIST_URL == "https://ecos.bok.or.kr/api/StatisticItemList"
    assert {
        (spec.slug, spec.stat_code, spec.item_code, spec.cycle)
        for spec in ECOS_SERIES
    } == {
        ("base_rate", "722Y001", "0101000", "D"),
        ("kr_gov_3y", "817Y002", "010200000", "D"),
        ("kr_gov_10y", "817Y002", "010210000", "D"),
        ("usd_krw", "731Y001", "0000001", "D"),
        ("cpi", "901Y009", "0", "M"),
    }


@pytest.mark.asyncio
async def test_missing_key_returns_unavailable_without_network() -> None:
    requests: list[httpx.Request] = []
    http_client = _mock_client(requests)
    try:
        result = await EcosMacroContextClient(
            "  ",
            client=http_client,
            now_factory=lambda: COLLECTED_AT,
        ).fetch()
    finally:
        await http_client.aclose()

    assert requests == []
    assert result.sources == ()
    assert result.facts == ()
    assert result.sections[0].status is SectionStatus.UNAVAILABLE
    assert "API 키가 없어" in result.sections[0].blocking_reasons[0]


@pytest.mark.asyncio
async def test_fetch_uses_verified_codes_and_builds_complete_official_section() -> None:
    requests: list[httpx.Request] = []
    http_client = _mock_client(requests)
    try:
        result = await EcosMacroContextClient(
            API_KEY,
            client=http_client,
            now_factory=lambda: COLLECTED_AT,
        ).fetch()
    finally:
        await http_client.aclose()

    assert len(requests) == len(ECOS_SERIES)
    assert all(request.url.host == "ecos.bok.or.kr" for request in requests)
    assert all(f"/{API_KEY}/json/kr/1/100/" in request.url.path for request in requests)
    assert result.sections[0].status is SectionStatus.COMPLETE
    assert result.sections[0].blocking_reasons == ()
    assert result.stale_fact_ids == ()
    assert len(result.facts) == len(ECOS_SERIES)
    assert len(result.sources) == 1
    assert str(result.sources[0].url) == ECOS_OPEN_API_URL
    assert API_KEY not in str(result.sources[0].url)
    assert result.sources[0].content_checksum is not None
    assert len(result.sources[0].content_checksum or "") == 64

    facts = {fact.fact_id: fact for fact in result.facts}
    assert facts["macro:ecos:kr_gov_10y:level"].value == 3.2
    assert facts["macro:ecos:kr_gov_10y:level"].unit == "percent"
    assert facts["macro:ecos:usd_krw:level"].currency == "KRW"
    assert facts["macro:ecos:cpi:level"].observed_at == datetime(2026, 6, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_http_and_logical_errors_block_without_exposing_key_or_remote_message() -> None:
    requests: list[httpx.Request] = []

    def override(
        request: httpx.Request,
        slug: str,
    ) -> httpx.Response | None:
        if slug == "kr_gov_10y":
            return httpx.Response(503, text="down", request=request)
        if slug == "cpi":
            return httpx.Response(
                200,
                json={
                    "RESULT": {
                        "CODE": "ERROR-100",
                        "MESSAGE": f"원격 메시지에 {API_KEY}가 포함된 경우",
                    }
                },
                request=request,
            )
        return None

    http_client = _mock_client(requests, override)
    try:
        result = await EcosMacroContextClient(
            API_KEY,
            client=http_client,
            now_factory=lambda: COLLECTED_AT,
        ).fetch()
    finally:
        await http_client.aclose()

    section = result.sections[0]
    assert section.status is SectionStatus.BLOCKED
    assert len(result.facts) == 3
    assert any("HTTP 503" in reason for reason in section.blocking_reasons)
    assert any("ERROR-100" in reason for reason in section.blocking_reasons)
    assert API_KEY not in repr(result)
    assert "원격 메시지" not in repr(result)


@pytest.mark.asyncio
async def test_stale_values_and_future_rows_are_blocked_and_identified() -> None:
    requests: list[httpx.Request] = []

    def override(
        request: httpx.Request,
        slug: str,
    ) -> httpx.Response | None:
        spec = next(item for item in ECOS_SERIES if item.slug == slug)
        periods = (
            (("202604", "110"), ("202608", "999"))
            if slug == "cpi"
            else (("20260601", "2.5"), ("20260713", "999"))
        )
        return httpx.Response(
            200,
            json=_payload(spec.stat_code, spec.item_code, *periods),
            request=request,
        )

    http_client = _mock_client(requests, override)
    try:
        result = await EcosMacroContextClient(
            API_KEY,
            client=http_client,
            now_factory=lambda: COLLECTED_AT,
        ).fetch()
    finally:
        await http_client.aclose()

    assert result.sections[0].status is SectionStatus.BLOCKED
    assert len(result.stale_fact_ids) == len(ECOS_SERIES)
    assert all(fact.value != 999 for fact in result.facts)
    assert all("허용 수명" in reason for reason in result.sections[0].blocking_reasons)


@pytest.mark.asyncio
async def test_invalid_key_is_blocked_without_network_or_secret_echo() -> None:
    requests: list[httpx.Request] = []
    http_client = _mock_client(requests)
    invalid_key = "unsafe/key/value"
    try:
        result = await EcosMacroContextClient(
            invalid_key,
            client=http_client,
            now_factory=lambda: COLLECTED_AT,
        ).fetch()
    finally:
        await http_client.aclose()

    assert requests == []
    assert result.sections[0].status is SectionStatus.BLOCKED
    assert invalid_key not in repr(result)
