# 미국과 한국 종목 식별자를 저장 형식과 표시 형식으로 정규화한다.
from __future__ import annotations

import re
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from investment_office.services.research_contracts import MarketId

_US_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")
_KR_SYMBOL_PATTERN = re.compile(r"^\d{6}$")


class InstrumentIdentityError(ValueError):
    """시장과 종목 식별자가 지원 계약과 맞지 않을 때 발생한다."""


class InstrumentIdentity(BaseModel):
    """외부 표시 심볼과 기존 DB에 저장할 호환 티커를 함께 제공한다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    market: MarketId
    symbol: str

    @property
    def canonical_id(self) -> str:
        return f"{self.market.value}:{self.symbol}"

    @property
    def storage_ticker(self) -> str:
        return self.symbol if self.market is MarketId.US else f"KR-{self.symbol}"

    @property
    def currency(self) -> str:
        return "USD" if self.market is MarketId.US else "KRW"


def normalize_instrument(market: MarketId | str, symbol: str) -> InstrumentIdentity:
    """사용자 입력을 시장별 정규 심볼로 바꾸고 모호한 형식을 거부한다."""

    try:
        resolved_market = MarketId(market)
    except ValueError as exc:
        raise InstrumentIdentityError("시장은 us 또는 kr이어야 합니다.") from exc
    if not isinstance(symbol, str):
        raise InstrumentIdentityError("종목 심볼은 문자열이어야 합니다.")
    normalized = symbol.strip().upper()
    if resolved_market is MarketId.US:
        normalized = normalized.replace("-", ".")
        if _US_SYMBOL_PATTERN.fullmatch(normalized) is None:
            raise InstrumentIdentityError("미국 종목 심볼 형식이 아닙니다. 예: AAPL, BRK.B")
    elif _KR_SYMBOL_PATTERN.fullmatch(normalized) is None:
        raise InstrumentIdentityError("한국 종목 심볼은 숫자 여섯 자리여야 합니다.")
    return InstrumentIdentity(market=resolved_market, symbol=normalized)


def resolve_stored_instrument(
    storage_ticker: str,
    attributes: Mapping[str, object],
) -> InstrumentIdentity:
    """기존 미국 기록과 새 시장 메타데이터를 동일한 식별자로 복원한다."""

    raw_market = attributes.get("market", MarketId.US.value)
    if not isinstance(raw_market, (str, MarketId)):
        raise InstrumentIdentityError("저장된 시장 식별자를 읽을 수 없습니다.")
    try:
        market = MarketId(raw_market)
    except ValueError as exc:
        raise InstrumentIdentityError("저장된 시장 식별자를 읽을 수 없습니다.") from exc
    raw_symbol = attributes.get("local_symbol")
    if isinstance(raw_symbol, str) and raw_symbol.strip():
        symbol = raw_symbol
    elif market is MarketId.KR and storage_ticker.startswith("KR-"):
        symbol = storage_ticker.removeprefix("KR-")
    else:
        symbol = storage_ticker
    identity = normalize_instrument(market, symbol)
    stored = storage_ticker.strip().upper()
    matches = (
        identity.storage_ticker.replace(".", "-") == stored.replace(".", "-")
        if market is MarketId.US
        else identity.storage_ticker == stored
    )
    if not matches:
        raise InstrumentIdentityError("저장 티커와 시장 메타데이터가 서로 다릅니다.")
    return identity
