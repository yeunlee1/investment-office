# 미국·한국 전체 상장 유니버스 원천과 TTL 캐시 계약을 검증한다.
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from investment_office.services.research_contracts import MarketId
from investment_office.services.universe_catalog import (
    KRX_KIND_KOSDAQ_URL,
    KRX_KIND_KOSPI_URL,
    NASDAQ_LISTED_URL,
    NASDAQ_OTHER_LISTED_URL,
    SEC_COMPANY_TICKERS_EXCHANGE_URL,
    CompositeUniverseCatalogProvider,
    KrxKindUniverseCatalogProvider,
    UniverseCatalogUnavailableError,
    UniverseTier,
    UsExchangeUniverseCatalogProvider,
)

NOW = datetime(2026, 7, 13, 3, 0, tzinfo=UTC)

NASDAQ_LISTED_FIXTURE = (
    "Symbol|Security Name|Market Category|Test Issue|Financial Status|"
    "Round Lot Size|ETF|NextShares\n"
    "AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\n"
    "QQQ|Invesco QQQ ETF|Q|N|N|100|Y|N\n"
    "PREF|Acme Preferred Stock|Q|N|N|100|N|N\n"
    "TEST|Test Company Common Stock|Q|Y|N|100|N|N\n"
    "NEXT|Next Company Common Stock|Q|N|N|100|N|Y\n"
    "BAD|Bad Company Common Stock|Q|N|D|100|N|N\n"
    "File Creation Time: 0713202603:00|||||||\n"
)

OTHER_LISTED_FIXTURE = (
    "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|"
    "Test Issue|NASDAQ Symbol\n"
    "IBM|International Business Machines Corporation Common Stock|N|IBM|N|100|N|IBM\n"
    "AAPL|Apple Inc. Common Stock|N|AAPL|N|100|N|AAPL\n"
    "SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY\n"
    "IBMP|IBM Preferred Stock|N|IBMP|N|100|N|IBMP\n"
    "OTC|Outside Exchange Common Stock|Q|OTC|N|100|N|OTC\n"
    "File Creation Time: 0713202603:00|||||||\n"
)

SEC_FIXTURE = {
    "fields": ["cik", "name", "ticker", "exchange"],
    "data": [
        [320193, "Apple Inc.", "AAPL", "Nasdaq"],
        [51143, "International Business Machines Corporation", "IBM", "NYSE"],
    ],
}


def _krx_html(rows: list[tuple[str, str, str, str, str]]) -> bytes:
    body = "".join(
        "<tr>"
        f"<td>{name}</td><td>{ticker}</td><td>{industry}</td>"
        f"<td>{products}</td><td>{listed_on}</td>"
        "</tr>"
        for name, ticker, industry, products, listed_on in rows
    )
    html = (
        "<html><body><table>"
        "<tr><th>회사명</th><th>종목코드</th><th>업종</th>"
        "<th>주요제품</th><th>상장일</th></tr>"
        f"{body}</table></body></html>"
    )
    return html.encode("euc-kr")


KOSPI_FIXTURE = _krx_html(
    [
        ("삼성전자", "005930", "통신 및 방송 장비 제조업", "반도체, 스마트폰", "1975-06-11"),
        ("삼성전자우", "005935", "통신 및 방송 장비 제조업", "우선주", "1989-01-01"),
        ("미래에셋비전스팩1호", "412930", "금융 지원 서비스업", "기업인수", "2022-04-01"),
    ]
)
KOSDAQ_FIXTURE = _krx_html(
    [
        ("알테오젠", "196170", "자연과학 연구개발업", "바이오의약품", "2014-12-12"),
        ("테스트기업인수목적", "123456", "금융 지원 서비스업", "기업인수", "2025-01-01"),
    ]
)


def _full_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url == NASDAQ_LISTED_URL:
        return httpx.Response(200, text=NASDAQ_LISTED_FIXTURE)
    if url == NASDAQ_OTHER_LISTED_URL:
        return httpx.Response(200, text=OTHER_LISTED_FIXTURE)
    if url == SEC_COMPANY_TICKERS_EXCHANGE_URL:
        return httpx.Response(200, json=SEC_FIXTURE)
    if url == KRX_KIND_KOSPI_URL:
        return httpx.Response(
            200,
            content=KOSPI_FIXTURE,
            headers={"Content-Type": "text/html; charset=euc-kr"},
        )
    if url == KRX_KIND_KOSDAQ_URL:
        return httpx.Response(
            200,
            content=KOSDAQ_FIXTURE,
            headers={"Content-Type": "text/html; charset=euc-kr"},
        )
    raise AssertionError(f"예상하지 않은 요청입니다. {url}")


@pytest.mark.asyncio
async def test_us_catalog_combines_exchange_files_filters_and_enriches_cik(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _full_handler(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = UsExchangeUniverseCatalogProvider(
            user_agent="Personal research contact@example.com",
            cache_path=tmp_path / "us.json",
            client=client,
            now_factory=lambda: NOW,
        )
        snapshot = await provider.load_snapshot(MarketId.US)

    assert [member.ticker for member in snapshot.members] == ["AAPL", "IBM"]
    assert snapshot.raw_count == 11
    assert snapshot.excluded_count == 8
    assert snapshot.duplicate_count == 1
    assert snapshot.members[0].cik == 320193
    assert snapshot.members[0].issuer_id == "sec:0000320193"
    assert snapshot.members[0].tiers == tuple(UniverseTier)
    assert snapshot.warnings == ()
    assert (tmp_path / "us.json").is_file()
    assert {str(request.url) for request in requests} == {
        NASDAQ_LISTED_URL,
        NASDAQ_OTHER_LISTED_URL,
        SEC_COMPANY_TICKERS_EXCHANGE_URL,
    }
    assert all(
        request.headers["user-agent"] == "Personal research contact@example.com"
        for request in requests
    )


@pytest.mark.asyncio
async def test_us_catalog_survives_sec_enrichment_failure_with_provenance_warning(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == SEC_COMPANY_TICKERS_EXCHANGE_URL:
            return httpx.Response(403, text="차단")
        return _full_handler(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = UsExchangeUniverseCatalogProvider(
            user_agent="Personal research contact@example.com",
            cache_path=tmp_path / "us.json",
            client=client,
            now_factory=lambda: NOW,
        )
        snapshot = await provider.load_snapshot(MarketId.US)

    assert [member.ticker for member in snapshot.members] == ["AAPL", "IBM"]
    assert all(member.cik is None for member in snapshot.members)
    assert snapshot.members[0].issuer_id == "us:AAPL"
    assert any("SEC CIK 보강" in warning for warning in snapshot.warnings)
    assert str(snapshot.source_url) == NASDAQ_LISTED_URL


@pytest.mark.asyncio
async def test_us_catalog_rejects_partial_primary_coverage(tmp_path: Path) -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if str(request.url) == NASDAQ_LISTED_URL:
            return httpx.Response(503, text="Nasdaq 범위 중단")
        return _full_handler(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = UsExchangeUniverseCatalogProvider(
            user_agent="Personal research contact@example.com",
            cache_path=tmp_path / "us.json",
            client=client,
            now_factory=lambda: NOW,
        )
        with pytest.raises(UniverseCatalogUnavailableError, match="두 미국 상장 원장"):
            await provider.load_snapshot(MarketId.US)

    assert SEC_COMPANY_TICKERS_EXCHANGE_URL not in requested_urls


@pytest.mark.asyncio
async def test_us_catalog_keeps_common_ads_and_filters_preferred_depositary_shares(
    tmp_path: Path,
) -> None:
    nasdaq = (
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|"
        "Round Lot Size|ETF|NextShares\n"
        "ARM|Arm Holdings plc - American Depositary Shares|Q|N|N|100|N|N\n"
        "PDD|PDD Holdings Inc. - American Depositary Shares|Q|N|N|100|N|N\n"
        "PREF|Example Bancorp Depositary Shares Each Representing a 1/40th Interest "
        "in a Share of Preferred Stock|Q|N|N|100|N|N\n"
    )
    other = (
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|"
        "Test Issue|NASDAQ Symbol\n"
        "BABA|Alibaba Group Holding Limited American Depositary Shares|N|"
        "BABA|N|100|N|BABA\n"
    )
    sec = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [
            [1973239, "Arm Holdings plc", "ARM", "Nasdaq"],
            [1737806, "PDD Holdings Inc.", "PDD", "Nasdaq"],
            [1577552, "Alibaba Group Holding Limited", "BABA", "NYSE"],
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == NASDAQ_LISTED_URL:
            return httpx.Response(200, text=nasdaq)
        if str(request.url) == NASDAQ_OTHER_LISTED_URL:
            return httpx.Response(200, text=other)
        if str(request.url) == SEC_COMPANY_TICKERS_EXCHANGE_URL:
            return httpx.Response(200, json=sec)
        raise AssertionError(f"예상하지 않은 요청입니다. {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = UsExchangeUniverseCatalogProvider(
            user_agent="Personal research contact@example.com",
            cache_path=tmp_path / "us.json",
            client=client,
            now_factory=lambda: NOW,
        )
        snapshot = await provider.load_snapshot(MarketId.US)

    assert [member.ticker for member in snapshot.members] == ["ARM", "BABA", "PDD"]
    assert snapshot.raw_count == 4
    assert snapshot.excluded_count == 1
    assert all(member.cik is not None for member in snapshot.members)


@pytest.mark.asyncio
async def test_sec_cik_mapping_normalizes_dot_and_hyphen_share_classes(tmp_path: Path) -> None:
    nasdaq = (
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|"
        "Round Lot Size|ETF|NextShares\n"
        "AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\n"
    )
    other = (
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|"
        "Test Issue|NASDAQ Symbol\n"
        "BRK.B|Berkshire Hathaway Inc. Class B Common Stock|N|BRK.B|N|100|N|BRK.B\n"
    )
    sec = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [
            [320193, "Apple Inc.", "AAPL", "Nasdaq"],
            [1067983, "Berkshire Hathaway Inc.", "BRK-B", "NYSE"],
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == NASDAQ_LISTED_URL:
            return httpx.Response(200, text=nasdaq)
        if str(request.url) == NASDAQ_OTHER_LISTED_URL:
            return httpx.Response(200, text=other)
        if str(request.url) == SEC_COMPANY_TICKERS_EXCHANGE_URL:
            return httpx.Response(200, json=sec)
        raise AssertionError(f"예상하지 않은 요청입니다. {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = UsExchangeUniverseCatalogProvider(
            user_agent="Personal research contact@example.com",
            cache_path=tmp_path / "us.json",
            client=client,
            now_factory=lambda: NOW,
        )
        snapshot = await provider.load_snapshot(MarketId.US)

    berkshire = next(member for member in snapshot.members if member.ticker == "BRK.B")
    assert berkshire.cik == 1067983
    assert berkshire.issuer_id == "sec:0001067983"


@pytest.mark.asyncio
async def test_us_catalog_fails_explicitly_when_both_primary_files_fail(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text=f"실패 {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = UsExchangeUniverseCatalogProvider(
            user_agent="Personal research contact@example.com",
            cache_path=tmp_path / "missing.json",
            client=client,
            now_factory=lambda: NOW,
        )
        with pytest.raises(UniverseCatalogUnavailableError, match="두 미국 상장 원장"):
            await provider.load_snapshot(MarketId.US)


@pytest.mark.asyncio
async def test_fresh_cache_avoids_network_and_expired_cache_does_not_mask_failure(
    tmp_path: Path,
) -> None:
    state = {"failed": False}
    current_time = {"value": NOW}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["failed"]:
            return httpx.Response(503, text="중단")
        return _full_handler(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = UsExchangeUniverseCatalogProvider(
            user_agent="Personal research contact@example.com",
            cache_path=tmp_path / "us.json",
            cache_ttl=timedelta(hours=1),
            client=client,
            now_factory=lambda: current_time["value"],
        )
        first = await provider.load_snapshot(MarketId.US)
        state["failed"] = True
        cached = await provider.load_snapshot(MarketId.US)
        current_time["value"] = NOW + timedelta(hours=2)
        with pytest.raises(UniverseCatalogUnavailableError, match="만료됨"):
            await provider.load_snapshot(MarketId.US)

    assert not first.cache_hit
    assert cached.cache_hit


@pytest.mark.asyncio
async def test_corrupt_cache_and_network_failure_are_reported_together(tmp_path: Path) -> None:
    cache_path = tmp_path / "us.json"
    cache_path.write_text("{고장", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text=f"실패 {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = UsExchangeUniverseCatalogProvider(
            user_agent="Personal research contact@example.com",
            cache_path=cache_path,
            client=client,
            now_factory=lambda: NOW,
        )
        with pytest.raises(UniverseCatalogUnavailableError, match="손상됨"):
            await provider.load_snapshot(MarketId.US)


@pytest.mark.asyncio
async def test_krx_catalog_reads_euc_kr_fields_and_filters_spac_and_preferred(
    tmp_path: Path,
) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(_full_handler)) as client:
        kr_provider = KrxKindUniverseCatalogProvider(
            user_agent="Personal research contact@example.com",
            cache_path=tmp_path / "kr.json",
            client=client,
            now_factory=lambda: NOW,
        )
        us_provider = UsExchangeUniverseCatalogProvider(
            user_agent="Personal research contact@example.com",
            cache_path=tmp_path / "us.json",
            client=client,
            now_factory=lambda: NOW,
        )
        composite = CompositeUniverseCatalogProvider((us_provider, kr_provider))
        snapshot = await composite.load_snapshot(MarketId.KR)

    assert composite.supported_markets == frozenset({MarketId.US, MarketId.KR})
    assert [member.ticker for member in snapshot.members] == ["005930", "196170"]
    samsung = snapshot.members[0]
    assert samsung.company_name == "삼성전자"
    assert samsung.exchange == "KOSPI"
    assert samsung.industry == "통신 및 방송 장비 제조업"
    assert samsung.main_products == "반도체, 스마트폰"
    assert samsung.listed_on == date(1975, 6, 11)
    assert snapshot.raw_count == 5
    assert snapshot.excluded_count == 3
    assert snapshot.duplicate_count == 0
    assert snapshot.warnings == ()


@pytest.mark.asyncio
async def test_krx_catalog_rejects_partial_primary_coverage(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == KRX_KIND_KOSDAQ_URL:
            return httpx.Response(503, text="KOSDAQ 범위 중단")
        return _full_handler(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = KrxKindUniverseCatalogProvider(
            user_agent="Personal research contact@example.com",
            cache_path=tmp_path / "kr.json",
            client=client,
            now_factory=lambda: NOW,
        )
        with pytest.raises(UniverseCatalogUnavailableError, match="KOSPI·KOSDAQ 원장이 모두"):
            await provider.load_snapshot(MarketId.KR)


def test_provider_requires_user_agent_and_rejects_duplicate_market() -> None:
    with pytest.raises(ValueError, match="User-Agent"):
        UsExchangeUniverseCatalogProvider(user_agent="")

    first = UsExchangeUniverseCatalogProvider(user_agent="Personal research contact@example.com")
    second = UsExchangeUniverseCatalogProvider(user_agent="Personal research contact@example.com")
    with pytest.raises(ValueError, match="중복"):
        CompositeUniverseCatalogProvider((first, second))
