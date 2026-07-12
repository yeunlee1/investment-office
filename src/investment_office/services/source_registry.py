# 미국과 한국 투자 데이터 공급원의 사용 정책과 준비 상태를 관리한다
from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from investment_office.services.research_contracts import MarketId

Market = MarketId


class DataDomain(StrEnum):
    REFERENCE = "reference"
    PRICE = "price"
    MACRO = "macro"
    FINANCIALS = "financials"
    DISCLOSURE = "disclosure"
    NEWS = "news"


class SourceId(StrEnum):
    SEC = "sec"
    NASDAQ_TRADER = "nasdaq_trader"
    FRED = "fred"
    BLS = "bls"
    FEDERAL_RESERVE_BOARD = "federal_reserve_board"
    US_TREASURY = "us_treasury"
    CBOE = "cboe"
    MASSIVE = "massive"
    TIINGO = "tiingo"
    YAHOO_FINANCE = "yahoo_finance"
    BOK_ECOS = "bok_ecos"
    KRX = "krx"
    KRX_KIND = "krx_kind"
    DATA_GO_KR = "data_go_kr"
    KIS = "kis"
    DART = "dart"
    DART_BULK = "dart_bulk"
    BIGKINDS = "bigkinds"
    NAVER_NEWS = "naver_news"
    REUTERS = "reuters"


class Officiality(StrEnum):
    GOVERNMENT = "government"
    CENTRAL_BANK = "central_bank"
    EXCHANGE = "exchange"
    LICENSED_VENDOR = "licensed_vendor"
    PUBLIC_INSTITUTION = "public_institution"
    NEWS_PUBLISHER = "news_publisher"
    SEARCH_AGGREGATOR = "search_aggregator"
    UNOFFICIAL = "unofficial"


class TrustLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class LicenseScope(StrEnum):
    PUBLIC_OPEN_DATA = "public_open_data"
    PUBLIC_REGISTERED_API = "public_registered_api"
    EXCHANGE_REFERENCE_DATA = "exchange_reference_data"
    COMMERCIAL_SUBSCRIPTION = "commercial_subscription"
    PERSONAL_INVESTMENT_NON_REDISTRIBUTION = "personal_investment_non_redistribution"
    DISCOVERY_METADATA_ONLY = "discovery_metadata_only"
    CONTRACT_REQUIRED = "contract_required"
    UNOFFICIAL_FALLBACK = "unofficial_fallback"


class SourceFreshness(StrEnum):
    REAL_TIME_OR_DELAYED = "real_time_or_delayed"
    NEAR_REAL_TIME = "near_real_time"
    INTRADAY = "intraday"
    END_OF_DAY = "end_of_day"
    NEXT_BUSINESS_DAY = "next_business_day"
    RELEASE_SCHEDULE = "release_schedule"
    TWICE_DAILY = "twice_daily"


class UseScope(StrEnum):
    ANALYSIS_ALLOWED = "analysis_allowed"
    DISCOVERY_ONLY = "discovery_only"
    DISABLED_PENDING_LICENSE = "disabled_pending_license"


class SourcePriority(IntEnum):
    PRIMARY = 1
    SECONDARY = 2
    FALLBACK = 3
    DISCOVERY = 4
    DISABLED = 99


class UnknownSourceError(KeyError):
    """등록되지 않은 공급원 식별자를 요청했을 때 발생한다."""


class SourcePolicy(BaseModel):
    """한 데이터 공급원의 출처 신뢰도와 허용된 사용 범위를 정의한다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: SourceId
    name: str = Field(min_length=1, max_length=100)
    markets: frozenset[MarketId] = Field(min_length=1)
    domains: frozenset[DataDomain] = Field(min_length=1)
    officiality: Officiality
    trust_level: TrustLevel
    required_key_env_vars: tuple[str, ...] = ()
    license_scope: LicenseScope
    license_note: str = Field(min_length=1, max_length=1_000)
    freshness: SourceFreshness
    freshness_note: str = Field(min_length=1, max_length=500)
    use_scope: UseScope
    priority: SourcePriority
    homepage_url: str = Field(pattern=r"^https://")
    enabled_by_default: bool = True
    ai_use_rights_confirmed: bool = True

    @model_validator(mode="after")
    def validate_usage_relationships(self) -> Self:
        if self.use_scope is UseScope.DISABLED_PENDING_LICENSE and self.enabled_by_default:
            raise ValueError("라이선스 확인 대기 공급원은 기본 활성화할 수 없습니다.")
        if self.use_scope is UseScope.ANALYSIS_ALLOWED and not self.ai_use_rights_confirmed:
            raise ValueError("분석 허용 공급원은 AI 사용 권한이 확인되어야 합니다.")
        return self


class SourceValidation(BaseModel):
    """환경 변수와 정책을 함께 확인한 공급원의 실행 준비 상태다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: SourceId
    enabled: bool
    ready: bool
    analysis_ready: bool
    missing_key_env_vars: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


_ALL_MARKETS: Final = frozenset({MarketId.US, MarketId.KR})


def _source(
    source_id: SourceId,
    name: str,
    markets: frozenset[MarketId],
    domains: frozenset[DataDomain],
    officiality: Officiality,
    trust_level: TrustLevel,
    license_scope: LicenseScope,
    license_note: str,
    freshness: SourceFreshness,
    freshness_note: str,
    use_scope: UseScope,
    priority: SourcePriority,
    homepage_url: str,
    *,
    required_key_env_vars: tuple[str, ...] = (),
    enabled_by_default: bool = True,
    ai_use_rights_confirmed: bool = True,
) -> SourcePolicy:
    return SourcePolicy(
        id=source_id,
        name=name,
        markets=markets,
        domains=domains,
        officiality=officiality,
        trust_level=trust_level,
        required_key_env_vars=required_key_env_vars,
        license_scope=license_scope,
        license_note=license_note,
        freshness=freshness,
        freshness_note=freshness_note,
        use_scope=use_scope,
        priority=priority,
        homepage_url=homepage_url,
        enabled_by_default=enabled_by_default,
        ai_use_rights_confirmed=ai_use_rights_confirmed,
    )


_POLICIES: Final = (
    _source(
        SourceId.SEC,
        "미국 증권거래위원회",
        frozenset({Market.US}),
        frozenset({DataDomain.FINANCIALS, DataDomain.DISCLOSURE}),
        Officiality.GOVERNMENT,
        TrustLevel.HIGH,
        LicenseScope.PUBLIC_OPEN_DATA,
        "공식 공시 원문과 기업 재무 사실을 분석할 수 있으며 공정 접근 정책을 지켜야 합니다.",
        SourceFreshness.NEAR_REAL_TIME,
        "공시는 접수 후 수 분 내 제공되지만 정정 공시는 별도 버전으로 추적해야 합니다.",
        UseScope.ANALYSIS_ALLOWED,
        SourcePriority.PRIMARY,
        "https://data.sec.gov/",
        required_key_env_vars=("SEC_USER_AGENT",),
    ),
    _source(
        SourceId.NASDAQ_TRADER,
        "나스닥 트레이더 종목 디렉터리",
        frozenset({Market.US}),
        frozenset({DataDomain.REFERENCE}),
        Officiality.EXCHANGE,
        TrustLevel.HIGH,
        LicenseScope.EXCHANGE_REFERENCE_DATA,
        "공식 상장 종목 원장을 개인 내부 분석에 사용하며 원본 파일을 재배포하지 않습니다.",
        SourceFreshness.INTRADAY,
        "거래일 중 수시로 갱신되는 종목 디렉터리를 하루 한 번 로컬 캐시합니다.",
        UseScope.ANALYSIS_ALLOWED,
        SourcePriority.PRIMARY,
        "https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs",
    ),
    _source(
        SourceId.FRED,
        "연방준비은행 경제 데이터",
        _ALL_MARKETS,
        frozenset({DataDomain.MACRO}),
        Officiality.GOVERNMENT,
        TrustLevel.HIGH,
        LicenseScope.CONTRACT_REQUIRED,
        "AI 처리와 자동 수집 및 저장에 필요한 권리가 서면으로 확인되기 전에는 사용하지 않습니다.",
        SourceFreshness.RELEASE_SCHEDULE,
        "각 지표의 공식 발표 일정과 수정 주기를 따릅니다.",
        UseScope.DISABLED_PENDING_LICENSE,
        SourcePriority.DISABLED,
        "https://fred.stlouisfed.org/graph/fredgraph.csv",
        enabled_by_default=False,
        ai_use_rights_confirmed=False,
    ),
    _source(
        SourceId.BLS,
        "미국 노동통계국",
        _ALL_MARKETS,
        frozenset({DataDomain.MACRO}),
        Officiality.GOVERNMENT,
        TrustLevel.HIGH,
        LicenseScope.PUBLIC_OPEN_DATA,
        "공개 통계와 API 응답을 분석하며 노동통계국 출처와 조회일 및 면책 문구를 함께 보존합니다.",
        SourceFreshness.RELEASE_SCHEDULE,
        "지표별 공식 발표 일정과 정정 및 연간 개정 주기를 따릅니다.",
        UseScope.ANALYSIS_ALLOWED,
        SourcePriority.PRIMARY,
        "https://www.bls.gov/developers/",
    ),
    _source(
        SourceId.FEDERAL_RESERVE_BOARD,
        "미국 연방준비제도 이사회",
        _ALL_MARKETS,
        frozenset({DataDomain.MACRO}),
        Officiality.CENTRAL_BANK,
        TrustLevel.HIGH,
        LicenseScope.PUBLIC_OPEN_DATA,
        "별도 표시가 없는 이사회 공개 자료를 분석하며 이사회 출처를 밝히고 "
        "제3자 저작물은 제외합니다.",
        SourceFreshness.RELEASE_SCHEDULE,
        "정책금리와 통계별 공식 발표 일정 및 수정 주기를 따릅니다.",
        UseScope.ANALYSIS_ALLOWED,
        SourcePriority.PRIMARY,
        "https://www.federalreserve.gov/data.htm",
        enabled_by_default=False,
    ),
    _source(
        SourceId.US_TREASURY,
        "미국 재무부",
        _ALL_MARKETS,
        frozenset({DataDomain.MACRO}),
        Officiality.GOVERNMENT,
        TrustLevel.HIGH,
        LicenseScope.PUBLIC_OPEN_DATA,
        "공식 국채 금리와 재정 데이터를 분석할 수 있습니다.",
        SourceFreshness.END_OF_DAY,
        "미국 영업일 기준 일별 금리 공개 시각을 따릅니다.",
        UseScope.ANALYSIS_ALLOWED,
        SourcePriority.PRIMARY,
        "https://fiscaldata.treasury.gov/api/fiscal_service/",
    ),
    _source(
        SourceId.CBOE,
        "시카고옵션거래소",
        _ALL_MARKETS,
        frozenset({DataDomain.MACRO}),
        Officiality.EXCHANGE,
        TrustLevel.HIGH,
        LicenseScope.CONTRACT_REQUIRED,
        "VIX 자료의 자동 수집과 AI 처리 권리가 확인되기 전에는 사용하지 않습니다.",
        SourceFreshness.END_OF_DAY,
        "활성화하지 않으며 계약 후 허용된 지연 또는 종가 범위를 별도로 정해야 합니다.",
        UseScope.DISABLED_PENDING_LICENSE,
        SourcePriority.DISABLED,
        "https://www.cboe.com/tradable-products/vix/",
        enabled_by_default=False,
        ai_use_rights_confirmed=False,
    ),
    _source(
        SourceId.MASSIVE,
        "Massive",
        frozenset({Market.US}),
        frozenset({DataDomain.PRICE, DataDomain.NEWS}),
        Officiality.LICENSED_VENDOR,
        TrustLevel.HIGH,
        LicenseScope.COMMERCIAL_SUBSCRIPTION,
        "구독 플랜이 허용한 미국 가격과 뉴스 필드만 내부 분석에 사용합니다.",
        SourceFreshness.REAL_TIME_OR_DELAYED,
        "실시간 여부와 지연 시간은 구독 플랜에 따라 달라집니다.",
        UseScope.ANALYSIS_ALLOWED,
        SourcePriority.PRIMARY,
        "https://massive.com/docs/rest/stocks/overview",
        required_key_env_vars=("MASSIVE_API_KEY",),
    ),
    _source(
        SourceId.TIINGO,
        "Tiingo",
        frozenset({Market.US}),
        frozenset({DataDomain.PRICE, DataDomain.NEWS}),
        Officiality.LICENSED_VENDOR,
        TrustLevel.HIGH,
        LicenseScope.COMMERCIAL_SUBSCRIPTION,
        "구독 약관과 호출 한도 안에서 가격과 뉴스 데이터를 내부 분석에 사용합니다.",
        SourceFreshness.END_OF_DAY,
        "기본 정책은 조정 완료된 일봉이며 상위 플랜은 별도 신선도를 적용합니다.",
        UseScope.ANALYSIS_ALLOWED,
        SourcePriority.SECONDARY,
        "https://www.tiingo.com/documentation/general/overview",
        required_key_env_vars=("TIINGO_API_TOKEN",),
    ),
    _source(
        SourceId.YAHOO_FINANCE,
        "Yahoo Finance 비공식 차트",
        _ALL_MARKETS,
        frozenset({DataDomain.PRICE}),
        Officiality.UNOFFICIAL,
        TrustLevel.LOW,
        LicenseScope.CONTRACT_REQUIRED,
        "자동 수집과 AI 처리 및 저장 권리가 확인되기 전에는 가격 자료를 사용하지 않습니다.",
        SourceFreshness.END_OF_DAY,
        "활성화하지 않으며 계약 후 별도 수집 정책과 신선도 기준을 정해야 합니다.",
        UseScope.DISABLED_PENDING_LICENSE,
        SourcePriority.DISABLED,
        "https://finance.yahoo.com/",
        enabled_by_default=False,
        ai_use_rights_confirmed=False,
    ),
    _source(
        SourceId.BOK_ECOS,
        "한국은행 경제통계시스템",
        frozenset({Market.KR}),
        frozenset({DataDomain.MACRO}),
        Officiality.CENTRAL_BANK,
        TrustLevel.HIGH,
        LicenseScope.PUBLIC_REGISTERED_API,
        "공식 거시 시계열을 내부 분석에 사용하며 통계 수정 이력을 보존합니다.",
        SourceFreshness.RELEASE_SCHEDULE,
        "통계표별 발표 주기와 한국은행 수정 일정을 따릅니다.",
        UseScope.ANALYSIS_ALLOWED,
        SourcePriority.PRIMARY,
        "https://ecos.bok.or.kr/api/",
        required_key_env_vars=("BOK_ECOS_API_KEY",),
    ),
    _source(
        SourceId.KRX,
        "한국거래소 정보데이터시스템",
        frozenset({Market.KR}),
        frozenset({DataDomain.PRICE, DataDomain.MACRO}),
        Officiality.EXCHANGE,
        TrustLevel.HIGH,
        LicenseScope.PUBLIC_REGISTERED_API,
        "공식 종가와 지수 및 수급 자료를 분석하며 재배포 조건은 별도로 준수합니다.",
        SourceFreshness.END_OF_DAY,
        "거래일 장 종료 후 확정된 자료를 사용합니다.",
        UseScope.ANALYSIS_ALLOWED,
        SourcePriority.PRIMARY,
        "https://openapi.krx.co.kr/",
        required_key_env_vars=("KRX_API_KEY",),
    ),
    _source(
        SourceId.KRX_KIND,
        "한국거래소 상장법인 목록",
        frozenset({Market.KR}),
        frozenset({DataDomain.REFERENCE}),
        Officiality.EXCHANGE,
        TrustLevel.HIGH,
        LicenseScope.EXCHANGE_REFERENCE_DATA,
        "KOSPI와 KOSDAQ 상장법인 목록을 개인 내부 분석에 사용하고 출처를 표시합니다.",
        SourceFreshness.END_OF_DAY,
        "상장·상호·업종 변경을 반영하기 위해 하루 한 번 로컬 캐시를 갱신합니다.",
        UseScope.ANALYSIS_ALLOWED,
        SourcePriority.PRIMARY,
        "https://kind.krx.co.kr/corpgeneral/corpList.do?method=loadInitPage",
    ),
    _source(
        SourceId.DATA_GO_KR,
        "공공데이터포털 금융위원회 주식시세",
        frozenset({Market.KR}),
        frozenset({DataDomain.PRICE}),
        Officiality.GOVERNMENT,
        TrustLevel.HIGH,
        LicenseScope.PUBLIC_REGISTERED_API,
        "공공데이터 이용조건에 따라 한국 주식 시세 교차검증에 사용합니다.",
        SourceFreshness.NEXT_BUSINESS_DAY,
        "통상 다음 영업일 반영 자료이므로 당일 종가의 단독 근거로 사용하지 않습니다.",
        UseScope.ANALYSIS_ALLOWED,
        SourcePriority.SECONDARY,
        "https://www.data.go.kr/data/15094808/openapi.do",
        required_key_env_vars=("DATA_GO_KR_SERVICE_KEY",),
    ),
    _source(
        SourceId.KIS,
        "한국투자증권 오픈 API",
        _ALL_MARKETS,
        frozenset({DataDomain.PRICE}),
        Officiality.LICENSED_VENDOR,
        TrustLevel.HIGH,
        LicenseScope.PERSONAL_INVESTMENT_NON_REDISTRIBUTION,
        "개인 투자 분석 범위에서만 사용하며 제3자 제공과 재배포를 금지합니다.",
        SourceFreshness.INTRADAY,
        "장중 시세를 제공하지만 분석 저장 시 조회 시각과 시장 세션을 고정합니다.",
        UseScope.ANALYSIS_ALLOWED,
        SourcePriority.SECONDARY,
        "https://apiportal.koreainvestment.com/",
        required_key_env_vars=("KIS_APP_KEY", "KIS_APP_SECRET"),
    ),
    _source(
        SourceId.DART,
        "금융감독원 전자공시 오픈 API",
        frozenset({Market.KR}),
        frozenset({DataDomain.FINANCIALS, DataDomain.DISCLOSURE}),
        Officiality.GOVERNMENT,
        TrustLevel.HIGH,
        LicenseScope.PUBLIC_REGISTERED_API,
        "공식 공시와 연결 재무제표를 분석하며 정정 공시와 보고서 기준일을 추적합니다.",
        SourceFreshness.NEAR_REAL_TIME,
        "공시는 접수 후 갱신되며 재무제표는 해당 보고서 공개 시점부터 사용합니다.",
        UseScope.ANALYSIS_ALLOWED,
        SourcePriority.PRIMARY,
        "https://opendart.fss.or.kr/",
        required_key_env_vars=("DART_API_KEY",),
    ),
    _source(
        SourceId.DART_BULK,
        "금융감독원 전자공시 재무정보 일괄자료",
        frozenset({Market.KR}),
        frozenset({DataDomain.FINANCIALS}),
        Officiality.GOVERNMENT,
        TrustLevel.HIGH,
        LicenseScope.PUBLIC_OPEN_DATA,
        "공개 연간 재무제표 묶음을 개인 내부 전체시장 선별에 사용하고 원본은 재배포하지 않습니다.",
        SourceFreshness.END_OF_DAY,
        "완료 사업보고서의 재무상태표·손익계산서·현금흐름표 묶음을 하루 한 번 확인합니다.",
        UseScope.ANALYSIS_ALLOWED,
        SourcePriority.PRIMARY,
        "https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/main.do",
    ),
    _source(
        SourceId.BIGKINDS,
        "빅카인즈",
        frozenset({Market.KR}),
        frozenset({DataDomain.NEWS}),
        Officiality.PUBLIC_INSTITUTION,
        TrustLevel.MEDIUM,
        LicenseScope.DISCOVERY_METADATA_ONLY,
        "기사 발견과 출처 교차검증에만 사용하며 기사 전문을 저장하거나 LLM에 전달하지 않습니다.",
        SourceFreshness.TWICE_DAILY,
        "서비스의 일일 분석 주기에 따라 최신 기사 반영이 지연될 수 있습니다.",
        UseScope.DISCOVERY_ONLY,
        SourcePriority.DISCOVERY,
        "https://www.bigkinds.or.kr/",
        required_key_env_vars=("BIGKINDS_API_KEY",),
    ),
    _source(
        SourceId.NAVER_NEWS,
        "네이버 뉴스 검색 API",
        frozenset({Market.KR}),
        frozenset({DataDomain.NEWS}),
        Officiality.SEARCH_AGGREGATOR,
        TrustLevel.MEDIUM,
        LicenseScope.DISCOVERY_METADATA_ONLY,
        "검색 결과의 제목과 링크로 원문을 발견하는 용도이며 기사 본문 분석 권한을 뜻하지 않습니다.",
        SourceFreshness.NEAR_REAL_TIME,
        "검색 색인 반영 시각은 원문 발행 시각과 다를 수 있습니다.",
        UseScope.DISCOVERY_ONLY,
        SourcePriority.DISCOVERY,
        "https://developers.naver.com/docs/serviceapi/search/news/news.md",
        required_key_env_vars=("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"),
    ),
    _source(
        SourceId.REUTERS,
        "Reuters Connect",
        _ALL_MARKETS,
        frozenset({DataDomain.NEWS}),
        Officiality.NEWS_PUBLISHER,
        TrustLevel.HIGH,
        LicenseScope.CONTRACT_REQUIRED,
        "계약별 AI 처리와 저장 권한이 확인되기 전에는 검색과 분석 모두 사용하지 않습니다.",
        SourceFreshness.NEAR_REAL_TIME,
        "계약된 피드의 게시 시각을 따릅니다.",
        UseScope.DISABLED_PENDING_LICENSE,
        SourcePriority.DISABLED,
        "https://www.reutersconnect.com/",
        required_key_env_vars=("REUTERS_CONNECT_CLIENT_ID", "REUTERS_CONNECT_CLIENT_SECRET"),
        enabled_by_default=False,
        ai_use_rights_confirmed=False,
    ),
)

SOURCE_REGISTRY: Final[Mapping[SourceId, SourcePolicy]] = MappingProxyType(
    {policy.id: policy for policy in _POLICIES}
)
_ENV_VAR_PATTERN: Final = re.compile(r"^[A-Z][A-Z0-9_]*$")


def get_source_policy(source_id: SourceId | str) -> SourcePolicy:
    """식별자로 공급원 정책을 조회한다."""

    try:
        normalized = source_id if isinstance(source_id, SourceId) else SourceId(source_id.strip())
        return SOURCE_REGISTRY[normalized]
    except (KeyError, ValueError, AttributeError) as exc:
        raise UnknownSourceError(f"등록되지 않은 데이터 공급원입니다. {source_id!r}") from exc


def list_source_policies(
    *,
    market: MarketId | None = None,
    domain: DataDomain | None = None,
    use_scope: UseScope | None = None,
    include_disabled: bool = False,
) -> tuple[SourcePolicy, ...]:
    """시장과 자료 영역 및 허용 범위로 공급원 정책을 우선순위순 조회한다."""

    policies = (
        policy
        for policy in SOURCE_REGISTRY.values()
        if (market is None or market in policy.markets)
        and (domain is None or domain in policy.domains)
        and (use_scope is None or policy.use_scope is use_scope)
        and (include_disabled or policy.enabled_by_default)
    )
    return tuple(sorted(policies, key=lambda policy: (policy.priority, policy.id.value)))


def validate_source_configuration(
    source_id: SourceId | str,
    environment: Mapping[str, str] | None = None,
    *,
    enabled: bool | None = None,
    require_analysis: bool = False,
) -> SourceValidation:
    """공급원의 키, 활성화 상태, 라이선스 범위가 요청 용도에 맞는지 확인한다."""

    policy = get_source_policy(source_id)
    values = os.environ if environment is None else environment
    active = policy.enabled_by_default if enabled is None else enabled
    missing = tuple(
        key for key in policy.required_key_env_vars if not values.get(key, "").strip()
    )
    errors: list[str] = []
    warnings: list[str] = []

    if not active:
        errors.append("공급원이 비활성화되어 있습니다.")
    if missing:
        errors.append("필수 인증 환경변수가 설정되지 않았습니다.")
    if policy.use_scope is UseScope.DISABLED_PENDING_LICENSE:
        errors.append("계약상 AI 사용 권한 확인 전에는 사용할 수 없습니다.")
    if require_analysis and policy.use_scope is not UseScope.ANALYSIS_ALLOWED:
        errors.append("이 공급원은 분석용으로 허용되지 않았습니다.")
    if not policy.ai_use_rights_confirmed:
        errors.append("AI 처리 권한이 확인되지 않았습니다.")
    if policy.trust_level is TrustLevel.LOW:
        warnings.append("낮은 신뢰도의 장애 대응 공급원이므로 다른 출처와 교차검증해야 합니다.")
    elif policy.priority is SourcePriority.FALLBACK:
        warnings.append("주 공급원 실패 시에만 사용하는 대체 공급원입니다.")

    discovery_ready = active and not missing and not errors
    analysis_ready = (
        discovery_ready
        and policy.use_scope is UseScope.ANALYSIS_ALLOWED
        and policy.ai_use_rights_confirmed
    )
    return SourceValidation(
        source_id=policy.id,
        enabled=active,
        ready=analysis_ready if require_analysis else discovery_ready,
        analysis_ready=analysis_ready,
        missing_key_env_vars=missing,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def validate_registry(
    policies: Iterable[SourcePolicy] | None = None,
) -> tuple[str, ...]:
    """레지스트리의 식별자, 환경변수, 우선순위와 라이선스 관계를 검증한다."""

    entries = tuple(SOURCE_REGISTRY.values()) if policies is None else tuple(policies)
    errors: list[str] = []
    seen: set[SourceId] = set()
    for policy in entries:
        if policy.id in seen:
            errors.append(f"중복 공급원 식별자입니다. {policy.id.value}")
        seen.add(policy.id)
        if len(set(policy.required_key_env_vars)) != len(policy.required_key_env_vars):
            errors.append(f"인증 환경변수가 중복되었습니다. {policy.id.value}")
        for key in policy.required_key_env_vars:
            if not _ENV_VAR_PATTERN.fullmatch(key):
                errors.append(f"인증 환경변수 이름이 올바르지 않습니다. {policy.id.value}: {key}")
        if policy.trust_level is TrustLevel.LOW and policy.priority < SourcePriority.FALLBACK:
            errors.append(f"낮은 신뢰도 공급원은 주 공급원이 될 수 없습니다. {policy.id.value}")
        if (
            policy.use_scope is UseScope.DISCOVERY_ONLY
            and policy.priority is not SourcePriority.DISCOVERY
        ):
            errors.append(f"발견 전용 공급원의 우선순위가 올바르지 않습니다. {policy.id.value}")
        if policy.use_scope is UseScope.DISABLED_PENDING_LICENSE:
            if policy.priority is not SourcePriority.DISABLED:
                errors.append(
                    f"라이선스 대기 공급원의 우선순위가 올바르지 않습니다. {policy.id.value}"
                )
            if policy.enabled_by_default:
                errors.append(f"라이선스 대기 공급원이 기본 활성화되었습니다. {policy.id.value}")

    if policies is None:
        missing_sources = set(SourceId) - seen
        for source_id in sorted(missing_sources, key=lambda item: item.value):
            errors.append(f"필수 공급원 정책이 없습니다. {source_id.value}")
    return tuple(errors)
