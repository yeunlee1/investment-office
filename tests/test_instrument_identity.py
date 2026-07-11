# 미국과 한국 종목 식별자의 정규화와 기존 기록 호환성을 검증한다.
import pytest

from investment_office.services.instrument_identity import (
    InstrumentIdentityError,
    normalize_instrument,
    resolve_stored_instrument,
)
from investment_office.services.research_contracts import MarketId


def test_normalizes_us_and_kr_symbols() -> None:
    us = normalize_instrument("us", " brk-b ")
    kr = normalize_instrument(MarketId.KR, "005930")

    assert us.symbol == "BRK.B"
    assert us.storage_ticker == "BRK.B"
    assert us.canonical_id == "us:BRK.B"
    assert us.currency == "USD"
    assert kr.storage_ticker == "KR-005930"
    assert kr.canonical_id == "kr:005930"
    assert kr.currency == "KRW"


def test_resolves_legacy_us_and_new_kr_records() -> None:
    legacy = resolve_stored_instrument("AAPL", {})
    korean = resolve_stored_instrument(
        "KR-000660",
        {"market": "kr", "local_symbol": "000660"},
    )

    assert legacy.market is MarketId.US
    assert legacy.symbol == "AAPL"
    assert korean.market is MarketId.KR
    assert korean.symbol == "000660"


@pytest.mark.parametrize(
    ("market", "symbol"),
    [("kr", "5930"), ("us", "005930"), ("eu", "SAP")],
)
def test_rejects_ambiguous_or_unsupported_symbols(market: str, symbol: str) -> None:
    with pytest.raises(InstrumentIdentityError):
        normalize_instrument(market, symbol)


def test_rejects_mismatched_stored_metadata() -> None:
    with pytest.raises(InstrumentIdentityError, match="서로 다릅니다"):
        resolve_stored_instrument(
            "KR-005930",
            {"market": "kr", "local_symbol": "000660"},
        )
