# 미국과 한국 데이터 공급원 정책의 조회와 안전한 사용 조건을 검증한다
from __future__ import annotations

import pytest

from investment_office.services.source_registry import (
    SOURCE_REGISTRY,
    DataDomain,
    Market,
    SourceId,
    SourcePriority,
    TrustLevel,
    UnknownSourceError,
    UseScope,
    get_source_policy,
    list_source_policies,
    validate_registry,
    validate_source_configuration,
)


def test_registry_contains_required_us_and_korean_sources() -> None:
    assert set(SOURCE_REGISTRY) == set(SourceId)
    assert validate_registry() == ()


def test_lookup_returns_official_financial_and_macro_sources() -> None:
    sec = get_source_policy("sec")
    ecos = get_source_policy(SourceId.BOK_ECOS)

    assert sec.markets == frozenset({Market.US})
    assert {DataDomain.FINANCIALS, DataDomain.DISCLOSURE} <= sec.domains
    assert ecos.markets == frozenset({Market.KR})
    assert DataDomain.MACRO in ecos.domains


def test_full_market_reference_sources_are_ready_without_api_keys() -> None:
    us_sources = list_source_policies(market=Market.US, domain=DataDomain.REFERENCE)
    kr_sources = list_source_policies(market=Market.KR, domain=DataDomain.REFERENCE)

    assert [source.id for source in us_sources] == [SourceId.NASDAQ_TRADER]
    assert [source.id for source in kr_sources] == [SourceId.KRX_KIND]
    assert validate_source_configuration(SourceId.NASDAQ_TRADER, {}).analysis_ready is True
    assert validate_source_configuration(SourceId.KRX_KIND, {}).analysis_ready is True


def test_full_market_dart_bulk_source_is_ready_without_api_key() -> None:
    validation = validate_source_configuration(SourceId.DART_BULK, {})

    assert validation.ready is True
    assert validation.analysis_ready is True
    assert validation.missing_key_env_vars == ()


def test_unknown_source_is_rejected() -> None:
    with pytest.raises(UnknownSourceError, match="등록되지 않은"):
        get_source_policy("unknown")


def test_market_and_domain_query_is_priority_ordered() -> None:
    sources = list_source_policies(market=Market.KR, domain=DataDomain.PRICE)

    assert {source.id for source in sources} == {
        SourceId.KRX,
        SourceId.DATA_GO_KR,
        SourceId.KIS,
    }
    assert [source.priority for source in sources] == sorted(source.priority for source in sources)


def test_common_macro_sources_are_available_to_both_markets() -> None:
    us_ids = {
        source.id
        for source in list_source_policies(market=Market.US, domain=DataDomain.MACRO)
    }
    kr_ids = {
        source.id
        for source in list_source_policies(market=Market.KR, domain=DataDomain.MACRO)
    }

    common_sources = {
        SourceId.BLS,
        SourceId.US_TREASURY,
    }
    assert common_sources <= us_ids
    assert common_sources <= kr_ids
    assert SourceId.FRED not in us_ids
    assert SourceId.FRED not in kr_ids
    assert SourceId.FEDERAL_RESERVE_BOARD not in us_ids
    assert SourceId.FEDERAL_RESERVE_BOARD not in kr_ids
    assert SourceId.CBOE not in us_ids
    assert SourceId.CBOE not in kr_ids
    assert SourceId.BOK_ECOS not in us_ids
    assert SourceId.BOK_ECOS in kr_ids


def test_required_keys_determine_configuration_readiness() -> None:
    fred = validate_source_configuration(SourceId.FRED, {})
    bls = validate_source_configuration(SourceId.BLS, {}, require_analysis=True)
    federal_reserve = validate_source_configuration(
        SourceId.FEDERAL_RESERVE_BOARD,
        {},
        require_analysis=True,
    )
    sec = validate_source_configuration(SourceId.SEC, {})
    missing = validate_source_configuration(SourceId.KIS, {})
    configured = validate_source_configuration(
        SourceId.KIS,
        {"KIS_APP_KEY": "key", "KIS_APP_SECRET": "secret"},
        require_analysis=True,
    )

    assert fred.ready is False
    assert fred.analysis_ready is False
    assert bls.ready is True
    assert bls.analysis_ready is True
    assert federal_reserve.ready is False
    assert federal_reserve.analysis_ready is False
    assert sec.ready is False
    assert sec.missing_key_env_vars == ("SEC_USER_AGENT",)
    assert missing.ready is False
    assert missing.missing_key_env_vars == ("KIS_APP_KEY", "KIS_APP_SECRET")
    assert configured.ready is True
    assert configured.analysis_ready is True


@pytest.mark.parametrize("source_id", [SourceId.BIGKINDS, SourceId.NAVER_NEWS])
def test_news_search_sources_are_discovery_only(source_id: SourceId) -> None:
    policy = get_source_policy(source_id)
    environment = {key: "configured" for key in policy.required_key_env_vars}

    discovery = validate_source_configuration(source_id, environment)
    analysis = validate_source_configuration(source_id, environment, require_analysis=True)

    assert policy.use_scope is UseScope.DISCOVERY_ONLY
    assert discovery.ready is True
    assert discovery.analysis_ready is False
    assert analysis.ready is False
    assert any("분석용" in error for error in analysis.errors)


def test_reuters_is_disabled_until_ai_rights_are_confirmed() -> None:
    policy = get_source_policy(SourceId.REUTERS)
    validation = validate_source_configuration(
        SourceId.REUTERS,
        {
            "REUTERS_CONNECT_CLIENT_ID": "client",
            "REUTERS_CONNECT_CLIENT_SECRET": "secret",
        },
        enabled=True,
        require_analysis=True,
    )

    assert policy.enabled_by_default is False
    assert policy.ai_use_rights_confirmed is False
    assert policy.use_scope is UseScope.DISABLED_PENDING_LICENSE
    assert policy.priority is SourcePriority.DISABLED
    assert validation.ready is False
    assert any("AI 사용 권한" in error for error in validation.errors)


def test_yahoo_is_disabled_until_ai_rights_are_confirmed() -> None:
    policy = get_source_policy(SourceId.YAHOO_FINANCE)
    validation = validate_source_configuration(
        SourceId.YAHOO_FINANCE,
        {},
        enabled=True,
        require_analysis=True,
    )

    assert policy.trust_level is TrustLevel.LOW
    assert policy.priority is SourcePriority.DISABLED
    assert policy.markets == frozenset({Market.US, Market.KR})
    assert policy.enabled_by_default is False
    assert policy.ai_use_rights_confirmed is False
    assert validation.ready is False
    assert any("AI 사용 권한" in error for error in validation.errors)


def test_fred_is_disabled_until_ai_rights_are_confirmed() -> None:
    policy = get_source_policy(SourceId.FRED)
    validation = validate_source_configuration(
        SourceId.FRED,
        {},
        enabled=True,
        require_analysis=True,
    )

    assert policy.enabled_by_default is False
    assert policy.ai_use_rights_confirmed is False
    assert policy.use_scope is UseScope.DISABLED_PENDING_LICENSE
    assert policy.priority is SourcePriority.DISABLED
    assert validation.ready is False
    assert any("AI 사용 권한" in error for error in validation.errors)


def test_cboe_is_disabled_until_ai_rights_are_confirmed() -> None:
    policy = get_source_policy(SourceId.CBOE)
    validation = validate_source_configuration(
        SourceId.CBOE,
        {},
        enabled=True,
        require_analysis=True,
    )

    assert policy.enabled_by_default is False
    assert policy.ai_use_rights_confirmed is False
    assert policy.use_scope is UseScope.DISABLED_PENDING_LICENSE
    assert policy.priority is SourcePriority.DISABLED
    assert validation.ready is False
    assert any("AI 사용 권한" in error for error in validation.errors)


def test_disabled_sources_are_hidden_from_default_queries() -> None:
    default_ids = {source.id for source in list_source_policies()}
    all_ids = {
        source.id
        for source in list_source_policies(include_disabled=True)
    }

    assert SourceId.REUTERS not in default_ids
    assert SourceId.FRED not in default_ids
    assert SourceId.YAHOO_FINANCE not in default_ids
    assert SourceId.CBOE not in default_ids
    assert SourceId.REUTERS in all_ids
    assert SourceId.FRED in all_ids
    assert SourceId.YAHOO_FINANCE in all_ids
    assert SourceId.CBOE in all_ids
