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

    assert {SourceId.FRED, SourceId.US_TREASURY, SourceId.CBOE} <= us_ids
    assert {SourceId.FRED, SourceId.US_TREASURY, SourceId.CBOE} <= kr_ids
    assert SourceId.BOK_ECOS not in us_ids
    assert SourceId.BOK_ECOS in kr_ids


def test_required_keys_determine_configuration_readiness() -> None:
    fred = validate_source_configuration(SourceId.FRED, {})
    sec = validate_source_configuration(SourceId.SEC, {})
    missing = validate_source_configuration(SourceId.KIS, {})
    configured = validate_source_configuration(
        SourceId.KIS,
        {"KIS_APP_KEY": "key", "KIS_APP_SECRET": "secret"},
        require_analysis=True,
    )

    assert fred.ready is True
    assert fred.analysis_ready is True
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


def test_yahoo_is_low_trust_fallback_with_cross_check_warning() -> None:
    policy = get_source_policy(SourceId.YAHOO_FINANCE)
    validation = validate_source_configuration(SourceId.YAHOO_FINANCE, {})

    assert policy.trust_level is TrustLevel.LOW
    assert policy.priority is SourcePriority.FALLBACK
    assert validation.ready is True
    assert validation.warnings


def test_disabled_sources_are_hidden_from_default_queries() -> None:
    default_ids = {source.id for source in list_source_policies(domain=DataDomain.NEWS)}
    all_ids = {
        source.id
        for source in list_source_policies(domain=DataDomain.NEWS, include_disabled=True)
    }

    assert SourceId.REUTERS not in default_ids
    assert SourceId.REUTERS in all_ids
