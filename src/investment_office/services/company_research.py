# 미국 SEC와 한국 DART의 공식 회사 재무·공시 메타데이터를 수집한다
from __future__ import annotations

import hashlib
import io
import math
import re
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Final, cast
from xml.etree import ElementTree

import httpx
from pydantic import AnyHttpUrl

from investment_office.services.research_contracts import (
    Fact,
    InstrumentRef,
    MarketId,
    ResearchSection,
    SectionStatus,
    SourceRef,
    SourceTier,
)

SEC_TICKERS_URL: Final = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANY_FACTS_URL: Final = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_SUBMISSIONS_URL: Final = "https://data.sec.gov/submissions/CIK{cik}.json"
DART_CORP_CODE_URL: Final = "https://opendart.fss.or.kr/api/corpCode.xml"
DART_LIST_URL: Final = "https://opendart.fss.or.kr/api/list.json"
DART_FINANCIAL_URL: Final = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"

FUNDAMENTAL_SECTION_ID: Final = "company.fundamental"
OFFICIAL_NEWS_SECTION_ID: Final = "company.official_news"
OFFICIAL_DISCLOSURE_METADATA_UNITS: Final = frozenset(
    {"accession_number", "receipt_number", "form"}
)
OFFICIAL_DISCLOSURE_METADATA_GAP: Final = (
    "공시 접수번호·양식·문서명은 메타데이터이므로 "
    "공시 원문이나 독립 뉴스 근거를 대신할 수 없습니다."
)
_RECENT_FILING_FORMS: Final = frozenset({"10-K", "10-Q", "8-K"})
_MAX_FILING_EVENTS: Final = 20
_MAX_CORP_CODE_ARCHIVE_BYTES: Final = 20 * 1024 * 1024
_MAX_CORP_CODE_XML_BYTES: Final = 60 * 1024 * 1024


class CompanyResearchError(RuntimeError):
    """공식 회사 자료의 요청 또는 응답 계약이 올바르지 않을 때 발생한다."""


@dataclass(frozen=True, slots=True)
class CompanyResearchResult:
    """한 회사의 공식 재무 사실과 공시 메타데이터 수집 결과."""

    sources: tuple[SourceRef, ...]
    facts: tuple[Fact, ...]
    sections: tuple[ResearchSection, ...]


@dataclass(frozen=True, slots=True)
class ValuationMetrics:
    """충분한 입력으로만 계산한 재무 비율과 입력 공백."""

    per: float | None
    roe_pct: float | None
    roa_pct: float | None
    pbr: float | None
    data_gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _SecMetricSpec:
    key: str
    metric: str
    tags: tuple[str, ...]
    preferred_unit: str
    output_unit: str
    currency: str | None = "USD"


_SEC_METRICS: Final = (
    _SecMetricSpec(
        "revenue",
        "최근 공시 기준 매출",
        (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
        ),
        "USD",
        "currency",
    ),
    _SecMetricSpec(
        "operating_income",
        "최근 공시 기준 영업이익",
        ("OperatingIncomeLoss",),
        "USD",
        "currency",
    ),
    _SecMetricSpec(
        "net_income",
        "최근 공시 기준 순이익",
        ("NetIncomeLoss", "ProfitLoss"),
        "USD",
        "currency",
    ),
    _SecMetricSpec(
        "equity",
        "최근 공시 기준 자본",
        (
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ),
        "USD",
        "currency",
    ),
    _SecMetricSpec("assets", "최근 공시 기준 자산", ("Assets",), "USD", "currency"),
    _SecMetricSpec(
        "liabilities",
        "최근 공시 기준 부채",
        ("Liabilities",),
        "USD",
        "currency",
    ),
    _SecMetricSpec(
        "diluted_eps",
        "최근 공시 기준 희석 주당이익",
        ("EarningsPerShareDiluted",),
        "USD/shares",
        "currency_per_share",
    ),
    _SecMetricSpec(
        "operating_cash_flow",
        "최근 공시 기준 영업현금흐름",
        ("NetCashProvidedByUsedInOperatingActivities",),
        "USD",
        "currency",
    ),
    _SecMetricSpec(
        "capital_expenditure",
        "최근 공시 기준 설비투자",
        ("PaymentsToAcquirePropertyPlantAndEquipment",),
        "USD",
        "currency",
    ),
)

_DART_ACCOUNT_ALIASES: Final[Mapping[str, tuple[str, ...]]] = {
    "revenue": ("매출액", "수익(매출액)", "영업수익"),
    "operating_income": ("영업이익", "영업이익(손실)"),
    "net_income": ("당기순이익", "당기순이익(손실)"),
    "equity": ("자본총계",),
    "assets": ("자산총계",),
    "liabilities": ("부채총계",),
    "diluted_eps": ("희석주당이익", "희석주당이익(손실)"),
    "operating_cash_flow": ("영업활동현금흐름",),
    "capital_expenditure": ("유형자산의 취득", "유형자산 취득"),
}

_DART_METRIC_LABELS: Final[Mapping[str, str]] = {
    "revenue": "최근 공시 기준 매출",
    "operating_income": "최근 공시 기준 영업이익",
    "net_income": "최근 공시 기준 순이익",
    "equity": "최근 공시 기준 자본",
    "assets": "최근 공시 기준 자산",
    "liabilities": "최근 공시 기준 부채",
    "diluted_eps": "최근 공시 기준 희석 주당이익",
    "operating_cash_flow": "최근 공시 기준 영업현금흐름",
    "capital_expenditure": "최근 공시 기준 설비투자",
}


def calculate_valuation_metrics(
    *,
    price: float | None,
    shares_outstanding: float | None,
    ttm_net_income: float | None,
    average_equity: float | None,
    average_assets: float | None,
    book_equity: float | None,
) -> ValuationMetrics:
    """가격과 재무 입력이 충분한 비율만 계산한다."""

    valid_price = _positive_finite(price)
    valid_shares = _positive_finite(shares_outstanding)
    valid_income = _finite(ttm_net_income)
    valid_average_equity = _positive_finite(average_equity)
    valid_average_assets = _positive_finite(average_assets)
    valid_book_equity = _positive_finite(book_equity)
    market_cap = (
        valid_price * valid_shares
        if valid_price is not None and valid_shares is not None
        else None
    )

    gaps: list[str] = []
    per: float | None = None
    if market_cap is None:
        gaps.append("PER 계산에 유효한 가격과 발행주식수가 필요합니다.")
    elif valid_income is None or valid_income <= 0:
        gaps.append("PER 계산에 양수인 TTM 순이익이 필요합니다.")
    else:
        per = market_cap / valid_income

    roe: float | None = None
    if valid_income is None or valid_average_equity is None:
        gaps.append("ROE 계산에 TTM 순이익과 양수인 평균자본이 필요합니다.")
    else:
        roe = valid_income / valid_average_equity * 100

    roa: float | None = None
    if valid_income is None or valid_average_assets is None:
        gaps.append("ROA 계산에 TTM 순이익과 양수인 평균자산이 필요합니다.")
    else:
        roa = valid_income / valid_average_assets * 100

    pbr: float | None = None
    if market_cap is None or valid_book_equity is None:
        gaps.append("PBR 계산에 유효한 시가총액과 양수인 장부자본이 필요합니다.")
    else:
        pbr = market_cap / valid_book_equity

    return ValuationMetrics(
        per=per,
        roe_pct=roe,
        roa_pct=roa,
        pbr=pbr,
        data_gaps=tuple(gaps),
    )


class OfficialCompanyResearchClient:
    """SEC와 DART의 공식 API만 사용해 회사 연구 자료를 수집한다."""

    def __init__(
        self,
        *,
        sec_user_agent: str | None = None,
        dart_api_key: str | None = None,
        timeout_seconds: float = 20.0,
        client: httpx.AsyncClient | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        if isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds는 0보다 커야 합니다.")
        self.sec_user_agent = sec_user_agent.strip() if sec_user_agent else None
        self.dart_api_key = dart_api_key.strip() if dart_api_key else None
        self.timeout_seconds = float(timeout_seconds)
        self.client = client
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    async def fetch(
        self,
        instrument: InstrumentRef,
        *,
        cutoff: datetime,
        business_year: int | None = None,
        report_code: str = "11011",
    ) -> CompanyResearchResult:
        """시장에 맞는 공식 회사 자료를 cutoff 이전 정보로만 조회한다."""

        aware_cutoff = _require_aware(cutoff, "cutoff")
        collected_at = _require_aware(self._now_factory(), "현재 시각")
        if instrument.market is MarketId.US:
            return await self._fetch_us(instrument, aware_cutoff, collected_at)
        return await self._fetch_kr(
            instrument,
            aware_cutoff,
            collected_at,
            business_year=business_year,
            report_code=report_code,
        )

    async def _fetch_us(
        self,
        instrument: InstrumentRef,
        cutoff: datetime,
        collected_at: datetime,
    ) -> CompanyResearchResult:
        if self.sec_user_agent is None:
            return _unavailable_result("SEC User-Agent가 설정되지 않았습니다.")

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": self.sec_user_agent,
        }
        ticker_response = await self._get(SEC_TICKERS_URL, headers=headers)
        ticker_payload = _json_mapping(ticker_response, "SEC 종목 매핑")
        cik = _find_sec_cik(ticker_payload, instrument.symbol)
        padded_cik = f"{cik:010d}"

        facts_response = await self._get(
            SEC_COMPANY_FACTS_URL.format(cik=padded_cik),
            headers=headers,
        )
        submissions_response = await self._get(
            SEC_SUBMISSIONS_URL.format(cik=padded_cik),
            headers=headers,
        )
        company_facts = _json_mapping(facts_response, "SEC Company Facts")
        submissions = _json_mapping(submissions_response, "SEC submissions")

        sources = (
            _source("official:sec:ticker_mapping", "SEC 종목 매핑", ticker_response, collected_at),
            _source("official:sec:companyfacts", "SEC Company Facts", facts_response, collected_at),
            _source(
                "official:sec:submissions",
                "SEC submissions",
                submissions_response,
                collected_at,
            ),
        )
        fundamental_facts, fundamental_gaps = _extract_sec_fundamentals(
            company_facts,
            instrument,
            cutoff,
            collected_at,
        )
        filing_facts = _extract_sec_filings(
            submissions,
            instrument,
            cutoff,
            collected_at,
        )
        sections = (
            _evidence_section(
                FUNDAMENTAL_SECTION_ID,
                "공식 재무제표",
                fundamental_facts,
                fundamental_gaps,
            ),
            _evidence_section(
                OFFICIAL_NEWS_SECTION_ID,
                "공식 공시 메타데이터",
                filing_facts,
                (
                    (OFFICIAL_DISCLOSURE_METADATA_GAP,)
                    if filing_facts
                    else ("cutoff 이전 최근 10-K, 10-Q, 8-K 공시가 없습니다.",)
                ),
            ),
        )
        return CompanyResearchResult(
            sources=sources,
            facts=(*fundamental_facts, *filing_facts),
            sections=sections,
        )

    async def _fetch_kr(
        self,
        instrument: InstrumentRef,
        cutoff: datetime,
        collected_at: datetime,
        *,
        business_year: int | None,
        report_code: str,
    ) -> CompanyResearchResult:
        if self.dart_api_key is None:
            return _unavailable_result("OpenDART 인증키가 설정되지 않았습니다.")
        if not re.fullmatch(r"\d{5}", report_code):
            raise ValueError("report_code는 다섯 자리 숫자여야 합니다.")
        resolved_year = business_year if business_year is not None else cutoff.year - 1
        if resolved_year < 1999 or resolved_year > cutoff.year:
            raise ValueError("business_year가 cutoff 기준 유효 범위를 벗어났습니다.")

        corp_response = await self._get(
            DART_CORP_CODE_URL,
            params={"crtfc_key": self.dart_api_key},
        )
        corp_code = _find_dart_corp_code(corp_response.content, instrument.symbol)
        end_date = cutoff.date()
        list_response = await self._get(
            DART_LIST_URL,
            params={
                "crtfc_key": self.dart_api_key,
                "corp_code": corp_code,
                "bgn_de": (end_date - timedelta(days=365)).strftime("%Y%m%d"),
                "end_de": end_date.strftime("%Y%m%d"),
                "page_count": "100",
            },
        )
        financial_response = await self._get(
            DART_FINANCIAL_URL,
            params={
                "crtfc_key": self.dart_api_key,
                "corp_code": corp_code,
                "bsns_year": str(resolved_year),
                "reprt_code": report_code,
                "fs_div": "CFS",
            },
        )
        disclosures = _dart_payload_items(list_response, "OpenDART 공시 목록")
        financial_items = _dart_payload_items(financial_response, "OpenDART 재무제표")

        sources = (
            _source(
                "official:dart:corp_codes",
                "OpenDART 고유번호",
                corp_response,
                collected_at,
                public_url=DART_CORP_CODE_URL,
            ),
            _source(
                "official:dart:disclosures",
                "OpenDART 공시 목록",
                list_response,
                collected_at,
                public_url=DART_LIST_URL,
            ),
            _source(
                "official:dart:financials",
                "OpenDART 단일회사 전체 재무제표",
                financial_response,
                collected_at,
                public_url=DART_FINANCIAL_URL,
            ),
        )
        filing_dates = _dart_filing_dates(disclosures, cutoff.date())
        fundamental_facts, fundamental_gaps = _extract_dart_fundamentals(
            financial_items,
            instrument,
            cutoff,
            collected_at,
            resolved_year,
            filing_dates,
        )
        disclosure_facts = _extract_dart_disclosures(
            disclosures,
            instrument,
            cutoff,
            collected_at,
        )
        sections = (
            _evidence_section(
                FUNDAMENTAL_SECTION_ID,
                "공식 재무제표",
                fundamental_facts,
                fundamental_gaps,
            ),
            _evidence_section(
                OFFICIAL_NEWS_SECTION_ID,
                "공식 공시 메타데이터",
                disclosure_facts,
                (
                    (OFFICIAL_DISCLOSURE_METADATA_GAP,)
                    if disclosure_facts
                    else ("cutoff 이전 최근 OpenDART 공시가 없습니다.",)
                ),
            ),
        )
        return CompanyResearchResult(
            sources=sources,
            facts=(*fundamental_facts, *disclosure_facts),
            sections=sections,
        )

    async def _get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        try:
            if self.client is not None:
                response = await self.client.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=self.timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            safe_url = str(exc.request.url.copy_with(query=None))
            raise CompanyResearchError(
                f"공식 회사 자료가 HTTP {exc.response.status_code}로 실패했습니다. {safe_url}"
            ) from None
        except httpx.RequestError as exc:
            safe_url = str(exc.request.url.copy_with(query=None))
            raise CompanyResearchError(f"공식 회사 자료 요청에 실패했습니다. {safe_url}") from None
        return response


def _source(
    source_id: str,
    name: str,
    response: httpx.Response,
    collected_at: datetime,
    *,
    public_url: str | None = None,
) -> SourceRef:
    return SourceRef(
        source_id=source_id,
        name=name,
        tier=SourceTier.OFFICIAL,
        url=AnyHttpUrl(public_url or str(response.request.url)),
        retrieved_at=collected_at,
        content_checksum=hashlib.sha256(response.content).hexdigest(),
    )


def _unavailable_result(reason: str) -> CompanyResearchResult:
    sections = tuple(
        ResearchSection(
            section_id=section_id,
            title=title,
            status=SectionStatus.UNAVAILABLE,
            blocking_reasons=(reason,),
        )
        for section_id, title in (
            (FUNDAMENTAL_SECTION_ID, "공식 재무제표"),
            (OFFICIAL_NEWS_SECTION_ID, "공식 공시 메타데이터"),
        )
    )
    return CompanyResearchResult(sources=(), facts=(), sections=sections)


def _evidence_section(
    section_id: str,
    title: str,
    facts: tuple[Fact, ...],
    gaps: tuple[str, ...],
) -> ResearchSection:
    fact_ids = tuple(fact.fact_id for fact in facts)
    if fact_ids and gaps:
        return ResearchSection(
            section_id=section_id,
            title=title,
            status=SectionStatus.PARTIAL,
            fact_ids=fact_ids,
            data_gaps=gaps,
        )
    if fact_ids:
        return ResearchSection(
            section_id=section_id,
            title=title,
            status=SectionStatus.COMPLETE,
            fact_ids=fact_ids,
        )
    return ResearchSection(
        section_id=section_id,
        title=title,
        status=SectionStatus.UNAVAILABLE,
        blocking_reasons=gaps or ("공식 자료에서 사용할 수 있는 사실을 찾지 못했습니다.",),
    )


def _find_sec_cik(payload: Mapping[str, object], symbol: str) -> int:
    normalized = symbol.upper().replace("-", ".")
    for raw_entry in payload.values():
        if not isinstance(raw_entry, Mapping):
            continue
        ticker = raw_entry.get("ticker")
        cik = raw_entry.get("cik_str")
        normalized_ticker = ticker.upper().replace("-", ".") if isinstance(ticker, str) else None
        if (
            isinstance(ticker, str)
            and normalized_ticker == normalized
            and isinstance(cik, int)
            and not isinstance(cik, bool)
            and cik > 0
        ):
            return cik
    raise CompanyResearchError(f"SEC 종목 매핑에서 {symbol}의 CIK를 찾지 못했습니다.")


def _extract_sec_fundamentals(
    payload: Mapping[str, object],
    instrument: InstrumentRef,
    cutoff: datetime,
    collected_at: datetime,
) -> tuple[tuple[Fact, ...], tuple[str, ...]]:
    facts_root = _mapping(payload.get("facts"), "SEC facts")
    us_gaap = _mapping(facts_root.get("us-gaap"), "SEC us-gaap facts")
    facts: list[Fact] = []
    gaps: list[str] = []
    for spec in _SEC_METRICS:
        selected = _select_sec_value(us_gaap, spec, cutoff.date())
        if selected is None:
            gaps.append(f"{spec.metric} 자료가 없습니다.")
            continue
        value, observed_on, filed_on = selected
        facts.append(
            Fact(
                fact_id=f"sec:{instrument.symbol.lower()}:{spec.key}",
                source_id="official:sec:companyfacts",
                metric=spec.metric,
                value=value,
                unit=spec.output_unit,
                currency=spec.currency,
                observed_at=_date_time(observed_on),
                published_at=_date_time(filed_on),
                collected_at=collected_at,
                instrument=instrument,
            )
        )
    return tuple(facts), tuple(gaps)


def _select_sec_value(
    us_gaap: Mapping[str, object],
    spec: _SecMetricSpec,
    cutoff: date,
) -> tuple[float, date, date] | None:
    candidates: list[tuple[date, date, float]] = []
    for tag in spec.tags:
        raw_tag = us_gaap.get(tag)
        if not isinstance(raw_tag, Mapping):
            continue
        units = raw_tag.get("units")
        if not isinstance(units, Mapping):
            continue
        raw_values = units.get(spec.preferred_unit)
        if not _is_sequence(raw_values):
            continue
        for raw_value in cast(Sequence[object], raw_values):
            if not isinstance(raw_value, Mapping):
                continue
            form = raw_value.get("form")
            if form not in {"10-K", "10-Q", "10-K/A", "10-Q/A"}:
                continue
            filed_on = _try_iso_date(raw_value.get("filed"))
            observed_on = _try_iso_date(raw_value.get("end"))
            value = _number(raw_value.get("val"))
            if (
                filed_on is None
                or observed_on is None
                or value is None
                or filed_on > cutoff
                or observed_on > filed_on
            ):
                continue
            candidates.append((filed_on, observed_on, value))
        if candidates:
            break
    if not candidates:
        return None
    filed_on, observed_on, value = max(candidates, key=lambda item: (item[0], item[1]))
    return value, observed_on, filed_on


def _extract_sec_filings(
    payload: Mapping[str, object],
    instrument: InstrumentRef,
    cutoff: datetime,
    collected_at: datetime,
) -> tuple[Fact, ...]:
    filings = _mapping(payload.get("filings"), "SEC filings")
    recent = _mapping(filings.get("recent"), "SEC recent filings")
    forms = _sequence(recent.get("form"), "SEC recent form")
    accession_numbers = _sequence(recent.get("accessionNumber"), "SEC accession numbers")
    filing_dates = _sequence(recent.get("filingDate"), "SEC filing dates")
    primary_documents = recent.get("primaryDocument")
    documents = _sequence(primary_documents, "SEC primary documents") if primary_documents else ()
    length = min(len(forms), len(accession_numbers), len(filing_dates))
    records: list[tuple[date, str, str, str]] = []
    for index in range(length):
        form = forms[index]
        accession = accession_numbers[index]
        filed_on = _try_iso_date(filing_dates[index])
        if (
            not isinstance(form, str)
            or form not in _RECENT_FILING_FORMS
            or not isinstance(accession, str)
            or filed_on is None
            or filed_on > cutoff.date()
        ):
            continue
        document = documents[index] if index < len(documents) else ""
        records.append(
            (filed_on, form, accession, document if isinstance(document, str) else "")
        )
    records.sort(reverse=True)
    facts: list[Fact] = []
    for filed_on, form, accession, document in records[:_MAX_FILING_EVENTS]:
        safe_accession = re.sub(r"[^a-z0-9._:]", "_", accession.lower())
        metric = f"SEC {form} 공시"
        if document:
            metric = f"{metric} 메타데이터 {document[:80]}"
        facts.append(
            Fact(
                fact_id=f"sec:{instrument.symbol.lower()}:filing:{safe_accession}",
                source_id="official:sec:submissions",
                metric=metric,
                value=accession,
                unit="accession_number",
                observed_at=_date_time(filed_on),
                published_at=_date_time(filed_on),
                collected_at=collected_at,
                instrument=instrument,
            )
        )
    return tuple(facts)


def _find_dart_corp_code(content: bytes, symbol: str) -> str:
    if len(content) > _MAX_CORP_CODE_ARCHIVE_BYTES:
        raise CompanyResearchError("OpenDART 고유번호 압축 파일이 허용 크기를 초과했습니다.")
    xml_content = content
    if zipfile.is_zipfile(io.BytesIO(content)):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                members = [member for member in archive.infolist() if not member.is_dir()]
                if len(members) != 1 or members[0].file_size > _MAX_CORP_CODE_XML_BYTES:
                    raise CompanyResearchError(
                        "OpenDART 고유번호 압축 파일 구성이 올바르지 않습니다."
                    )
                xml_content = archive.read(members[0])
        except (OSError, zipfile.BadZipFile) as exc:
            raise CompanyResearchError("OpenDART 고유번호 압축 파일을 읽을 수 없습니다.") from exc
    try:
        root = ElementTree.fromstring(xml_content)
    except ElementTree.ParseError as exc:
        raise CompanyResearchError("OpenDART 고유번호 XML이 올바르지 않습니다.") from exc
    for entry in root.findall(".//list"):
        stock_code = (entry.findtext("stock_code") or "").strip()
        corp_code = (entry.findtext("corp_code") or "").strip()
        if stock_code == symbol and re.fullmatch(r"\d{8}", corp_code):
            return corp_code
    raise CompanyResearchError(f"OpenDART 고유번호에서 {symbol}을 찾지 못했습니다.")


def _dart_payload_items(response: httpx.Response, label: str) -> tuple[Mapping[str, object], ...]:
    payload = _json_mapping(response, label)
    status = payload.get("status")
    if status == "013":
        return ()
    if status != "000":
        message = payload.get("message")
        raise CompanyResearchError(f"{label} 응답 오류입니다. {status}: {message}")
    raw_items = payload.get("list")
    if raw_items is None:
        return ()
    return tuple(
        item for item in _sequence(raw_items, f"{label} list") if isinstance(item, Mapping)
    )


def _dart_filing_dates(
    disclosures: tuple[Mapping[str, object], ...],
    cutoff: date,
) -> dict[str, date]:
    dates: dict[str, date] = {}
    for item in disclosures:
        receipt = item.get("rcept_no")
        filed_on = _try_compact_date(item.get("rcept_dt"))
        if isinstance(receipt, str) and filed_on is not None and filed_on <= cutoff:
            dates[receipt] = filed_on
    return dates


def _extract_dart_fundamentals(
    items: tuple[Mapping[str, object], ...],
    instrument: InstrumentRef,
    cutoff: datetime,
    collected_at: datetime,
    business_year: int,
    filing_dates: Mapping[str, date],
) -> tuple[tuple[Fact, ...], tuple[str, ...]]:
    facts: list[Fact] = []
    gaps: list[str] = []
    for key, aliases in _DART_ACCOUNT_ALIASES.items():
        selected: Mapping[str, object] | None = None
        for item in items:
            if (
                item.get("account_nm") in aliases
                and _parse_amount(item.get("thstrm_amount")) is not None
            ):
                selected = item
                break
        if selected is None:
            gaps.append(f"{_DART_METRIC_LABELS[key]} 자료가 없습니다.")
            continue
        value = _parse_amount(selected.get("thstrm_amount"))
        if value is None:
            gaps.append(f"{_DART_METRIC_LABELS[key]} 금액을 해석할 수 없습니다.")
            continue
        observed_on = _dart_observed_date(selected.get("thstrm_dt"), business_year)
        receipt = selected.get("rcept_no")
        published_on = filing_dates.get(receipt) if isinstance(receipt, str) else None
        if published_on is None:
            published_on = _dart_receipt_date(receipt)
        if published_on is None or published_on > cutoff.date():
            gaps.append(f"{_DART_METRIC_LABELS[key]} 공개 시각을 확인할 수 없습니다.")
            continue
        if observed_on > published_on:
            gaps.append(f"{_DART_METRIC_LABELS[key]} 관측 시각이 공개 시각보다 늦습니다.")
            continue
        facts.append(
            Fact(
                fact_id=f"dart:{instrument.symbol}:{key}",
                source_id="official:dart:financials",
                metric=_DART_METRIC_LABELS[key],
                value=value,
                unit="currency_per_share" if key == "diluted_eps" else "currency",
                currency="KRW",
                observed_at=_date_time(observed_on),
                published_at=_date_time(published_on),
                collected_at=collected_at,
                instrument=instrument,
            )
        )
    return tuple(facts), tuple(gaps)


def _extract_dart_disclosures(
    items: tuple[Mapping[str, object], ...],
    instrument: InstrumentRef,
    cutoff: datetime,
    collected_at: datetime,
) -> tuple[Fact, ...]:
    records: list[tuple[date, str, str]] = []
    for item in items:
        receipt = item.get("rcept_no")
        title = item.get("report_nm")
        filed_on = _try_compact_date(item.get("rcept_dt"))
        if (
            not isinstance(receipt, str)
            or not receipt.isdigit()
            or not isinstance(title, str)
            or not title.strip()
            or filed_on is None
            or filed_on > cutoff.date()
        ):
            continue
        records.append((filed_on, receipt, title.strip()))
    records.sort(reverse=True)
    return tuple(
        Fact(
            fact_id=f"dart:{instrument.symbol}:filing:{receipt}",
            source_id="official:dart:disclosures",
            metric=f"OpenDART 공시 메타데이터 {title[:100]}",
            value=receipt,
            unit="receipt_number",
            observed_at=_date_time(filed_on),
            published_at=_date_time(filed_on),
            collected_at=collected_at,
            instrument=instrument,
        )
        for filed_on, receipt, title in records[:_MAX_FILING_EVENTS]
    )


def _dart_observed_date(value: object, business_year: int) -> date:
    if isinstance(value, str):
        matches = re.findall(r"(\d{4})[.\-/](\d{2})[.\-/](\d{2})", value)
        if matches:
            year, month, day = matches[-1]
            try:
                return date(int(year), int(month), int(day))
            except ValueError:
                pass
    return date(business_year, 12, 31)


def _parse_amount(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value) if math.isfinite(float(value)) else None
    if not isinstance(value, str):
        return None
    normalized = value.strip().replace(",", "")
    if normalized.startswith("(") and normalized.endswith(")"):
        normalized = f"-{normalized[1:-1]}"
    try:
        parsed = float(normalized)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _json_mapping(response: httpx.Response, label: str) -> Mapping[str, object]:
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise CompanyResearchError(f"{label} 응답이 유효한 JSON이 아닙니다.") from exc
    return _mapping(payload, label)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CompanyResearchError(f"{label} 객체가 없습니다.")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not _is_sequence(value):
        raise CompanyResearchError(f"{label} 배열이 없습니다.")
    return cast(Sequence[object], value)


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _finite(value: float | None) -> float | None:
    if value is None or isinstance(value, bool) or not math.isfinite(value):
        return None
    return float(value)


def _positive_finite(value: float | None) -> float | None:
    parsed = _finite(value)
    return parsed if parsed is not None and parsed > 0 else None


def _try_iso_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _try_compact_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def _dart_receipt_date(value: object) -> date | None:
    if not isinstance(value, str) or len(value) < 8:
        return None
    return _try_compact_date(value[:8])


def _date_time(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def _require_aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label}은 시간대가 포함된 시각이어야 합니다.")
    return value.astimezone(UTC)
