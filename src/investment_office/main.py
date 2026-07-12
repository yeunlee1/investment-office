# FastAPI 웹 화면과 분석·검토·SSE API를 제공하는 애플리케이션 진입점이다.
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, timedelta
from pathlib import Path
from typing import Any, Literal, Self, cast
from uuid import UUID, uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from sqlalchemy import text
from sqlalchemy.engine import Connection
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware

from investment_office.config import LOOPBACK_HOSTS, Settings, get_settings
from investment_office.database import DatabaseRuntime, create_database_runtime
from investment_office.domain import AgentRole, AnalysisRunStatus, ReviewDecision, utc_now
from investment_office.services.bulk_fundamentals import (
    CompositeBulkFundamentalsProvider,
    DartMultiCompanyBulkProvider,
    SecCompanyFactsBulkProvider,
    UnavailableBulkFundamentalsProvider,
)
from investment_office.services.candidate_discovery import (
    CandidateDiscoveryService,
    DiscoveryStrategy,
)
from investment_office.services.codex_provider import (
    CodexProvider,
    build_codex_child_environment,
)
from investment_office.services.committee_broker import (
    CommitteeBroker,
    CommitteeConflictError,
    CommitteeError,
    CommitteeNotFoundError,
    CommitteeValidationError,
)
from investment_office.services.company_research import OfficialCompanyResearchClient
from investment_office.services.decision_archive import (
    DecisionArchiveNotFoundError,
    DecisionArchiveService,
)
from investment_office.services.discovery_jobs import (
    DiscoveryJobNotFoundError,
    DiscoveryJobService,
)
from investment_office.services.event_broker import EventBroker
from investment_office.services.full_market_discovery import FullMarketDiscoveryService
from investment_office.services.fundamental_screening import FundamentalGateProfile
from investment_office.services.instrument_identity import (
    normalize_instrument,
    resolve_stored_instrument,
)
from investment_office.services.macro_context import OfficialMacroContextClient
from investment_office.services.market_data import YahooFinanceClient
from investment_office.services.market_overview import MarketOverviewService
from investment_office.services.orchestrator import (
    DISCOVERY_ANALYSIS_THESIS,
    AnalysisProvider,
    AnalysisRunConflictError,
    ConcurrencyLimitedEODMarketDataClient,
    ConcurrencyLimitedResearchDataClient,
    EODMarketDataClient,
    InvestmentCommittee,
    ResearchDataClient,
    RiskFunction,
)
from investment_office.services.price_gateway import build_default_committee_price_gateway
from investment_office.services.research_contracts import MarketId
from investment_office.services.research_pipeline import ResearchPipeline
from investment_office.services.risk import assess_risk
from investment_office.services.scheduled_analysis import (
    ScheduledAnalysis,
    ScheduledAnalysisConflictError,
    ScheduledAnalysisError,
    ScheduledAnalysisNotFoundError,
    ScheduledAnalysisService,
    ScheduledAnalysisStatus,
    ScheduledAnalysisTransitionError,
    ScheduledAnalysisValidationError,
)
from investment_office.services.source_registry import (
    SourceId,
    list_source_policies,
    validate_source_configuration,
)
from investment_office.services.universe_catalog import (
    CompositeUniverseCatalogProvider,
    KrxKindUniverseCatalogProvider,
    UsExchangeUniverseCatalogProvider,
)
from investment_office.services.work_items import (
    WorkItemNotFoundError,
    WorkItemService,
    WorkItemTransitionError,
)
from investment_office.storage import Storage

PACKAGE_ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=PACKAGE_ROOT / "templates")
logger = logging.getLogger(__name__)


class _DefaultResearchDataMarker:
    """연구 수집기의 기본 생성과 명시적 비활성화를 구분하는 표식."""


_DEFAULT_RESEARCH_DATA = _DefaultResearchDataMarker()


def _log_background_task_failure(completed: asyncio.Task[Any]) -> None:
    """회수된 백그라운드 태스크의 예상 밖 예외를 서버 로그에 남긴다."""

    if completed.cancelled():
        return
    failure = completed.exception()
    if failure is None:
        return
    logger.error(
        "백그라운드 태스크가 예상 밖 예외로 종료되었습니다. 태스크=%s",
        completed.get_name(),
        exc_info=(type(failure), failure, failure.__traceback__),
    )


class AnalyzeRequest(BaseModel):
    """사람이 제출하는 미국 또는 한국 종목 분석 요청."""

    model_config = ConfigDict(extra="forbid")
    market: MarketId = MarketId.US
    ticker: str = Field(min_length=1, max_length=15, pattern=r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")
    thesis: str | None = Field(default=None, max_length=5_000)

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_market_ticker(self) -> Self:
        self.ticker = normalize_instrument(self.market, self.ticker).symbol
        return self


class ScheduleAnalysisRequest(AnalyzeRequest):
    """한국시간을 포함한 절대 시각으로 1회 분석을 예약하는 요청."""

    scheduled_for: AwareDatetime


class DiscoveryScreenRequest(BaseModel):
    """선택한 시장 전체 상장 원장의 다단계 후보 선별 요청."""

    model_config = ConfigDict(extra="forbid")
    market: MarketId = MarketId.US
    strategy: DiscoveryStrategy = DiscoveryStrategy.BALANCED
    risk_profile: FundamentalGateProfile = FundamentalGateProfile.BALANCED
    limit: int = Field(default=8, ge=1, le=30)
    force_refresh: bool = False


class DiscoveryAnalyzeRequest(BaseModel):
    """1차 후보 중 최대 세 종목을 투자팀 심층 분석에 넘기는 요청."""

    model_config = ConfigDict(extra="forbid")
    market: MarketId = MarketId.US
    tickers: list[str] = Field(min_length=1, max_length=3)

    @field_validator("tickers", mode="before")
    @classmethod
    def normalize_tickers(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [item.strip().upper() if isinstance(item, str) else item for item in value]

    @model_validator(mode="after")
    def validate_tickers(self) -> Self:
        normalized = [
            normalize_instrument(self.market, ticker).symbol for ticker in self.tickers
        ]
        if len(normalized) != len(set(normalized)):
            raise ValueError("tickers에 중복 종목을 넣을 수 없습니다.")
        self.tickers = normalized
        return self


class ReviewRequest(BaseModel):
    """사람의 승인·보류·기각 결정을 기록하는 요청."""

    model_config = ConfigDict(extra="forbid")
    decision: ReviewDecision
    reason: str = Field(min_length=4, max_length=10_000)


class CreateWorkItemRequest(BaseModel):
    """NPC에게 배정할 수동 분석 업무 요청."""

    model_config = ConfigDict(extra="forbid")
    role: AgentRole
    title: str = Field(min_length=1, max_length=200)
    instructions: str = Field(min_length=1, max_length=20_000)


class StartCommitteeRequest(BaseModel):
    """근거 중심 투자위원회를 소집하는 요청."""

    model_config = ConfigDict(extra="forbid")
    topic: str = Field(min_length=1, max_length=500)
    participants: list[AgentRole] = Field(min_length=2, max_length=6)
    max_turns: int = Field(default=12, ge=2, le=24)


class CommitteeCommandRequest(BaseModel):
    """지정 발언과 회의 종료만 허용하는 사람의 회의 제어 요청."""

    model_config = ConfigDict(extra="forbid")
    command: Literal["request_speech", "directed_speak", "finish", "stop"]
    role: AgentRole | None = None
    prompt: str | None = Field(default=None, max_length=2_000)
    reason: str | None = Field(default=None, max_length=2_000)


async def _probe_codex(command: str) -> dict[str, str]:
    executable = shutil.which(command)
    if executable is None:
        return {
            "name": "Codex CLI",
            "status": "offline",
            "detail": "Codex 실행 파일을 찾을 수 없습니다.",
            "mode": "ChatGPT subscription",
        }
    options: dict[str, Any] = {
        "env": build_codex_child_environment(),
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        process = await asyncio.create_subprocess_exec(
            executable,
            "login",
            "status",
            **options,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
    except (OSError, TimeoutError) as exc:
        return {
            "name": "Codex CLI",
            "status": "degraded",
            "detail": f"인증 상태 확인 실패. {exc}",
            "mode": "ChatGPT subscription",
        }
    detail = (stdout or stderr).decode("utf-8", errors="replace").strip()
    return {
        "name": "Codex CLI",
        "status": "ready" if process.returncode == 0 else "offline",
        "detail": detail or "인증 상태 출력이 없습니다.",
        "mode": "ChatGPT subscription · codex exec",
    }


def create_app(
    *,
    settings: Settings | None = None,
    storage: Storage | None = None,
    provider: AnalysisProvider | None = None,
    market_data: EODMarketDataClient | None = None,
    research_data: ResearchDataClient | None | _DefaultResearchDataMarker = (
        _DEFAULT_RESEARCH_DATA
    ),
    market_overview_service: MarketOverviewService | None = None,
    full_market_discovery_service: FullMarketDiscoveryService | None = None,
    discovery_job_service: DiscoveryJobService | None = None,
    risk_function: RiskFunction = assess_risk,
) -> FastAPI:
    """운영 의존성 또는 테스트 대역으로 애플리케이션을 구성한다."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved_settings = settings or get_settings()
        app.state.settings = resolved_settings
        database_runtime: DatabaseRuntime | None = None
        resolved_storage = storage
        if resolved_storage is None:
            database_runtime = create_database_runtime(resolved_settings.database_url)
            resolved_storage = database_runtime.storage
        resolved_provider = provider or CodexProvider(
            command=resolved_settings.codex_command,
            timeout_seconds=resolved_settings.codex_timeout_seconds,
        )
        resolved_market_data = market_data or build_default_committee_price_gateway(
            yahoo_client=YahooFinanceClient(
                timeout_seconds=resolved_settings.market_data_timeout_seconds
            ),
            tiingo_api_token=resolved_settings.tiingo_api_token,
            korea_service_key=resolved_settings.data_go_kr_service_key,
            timeout_seconds=resolved_settings.market_data_timeout_seconds,
        )
        resolved_research: ResearchDataClient | None
        if isinstance(research_data, _DefaultResearchDataMarker):
            resolved_research = ResearchPipeline(
                macro_client=OfficialMacroContextClient(
                    timeout_seconds=resolved_settings.market_data_timeout_seconds
                ),
                company_client=OfficialCompanyResearchClient(
                    sec_user_agent=resolved_settings.sec_user_agent,
                    dart_api_key=resolved_settings.dart_api_key,
                    timeout_seconds=resolved_settings.market_data_timeout_seconds,
                ),
                ecos_api_key=resolved_settings.bok_ecos_api_key,
            )
        else:
            resolved_research = research_data
        broker = EventBroker()
        provider_semaphore = asyncio.Semaphore(resolved_settings.max_parallel_agents)
        run_semaphore = asyncio.Semaphore(resolved_settings.max_parallel_agents)
        data_collection_semaphore = asyncio.Semaphore(
            resolved_settings.max_parallel_agents
        )
        limited_market_data = ConcurrencyLimitedEODMarketDataClient(
            resolved_market_data,
            data_collection_semaphore,
        )
        limited_research_data = (
            ConcurrencyLimitedResearchDataClient(
                resolved_research,
                data_collection_semaphore,
            )
            if resolved_research is not None
            else None
        )
        resolved_full_market_discovery = full_market_discovery_service
        if resolved_full_market_discovery is None:
            catalog_user_agent = (
                resolved_settings.sec_user_agent
                or "investment-office/0.1 local-analysis"
            )
            universe_catalog = CompositeUniverseCatalogProvider(
                (
                    UsExchangeUniverseCatalogProvider(
                        user_agent=catalog_user_agent,
                        timeout_seconds=resolved_settings.market_data_timeout_seconds,
                    ),
                    KrxKindUniverseCatalogProvider(
                        user_agent=catalog_user_agent,
                        timeout_seconds=resolved_settings.market_data_timeout_seconds,
                    ),
                )
            )
            us_fundamentals = (
                SecCompanyFactsBulkProvider(
                    user_agent=resolved_settings.sec_user_agent,
                    timeout_seconds=max(
                        180.0,
                        resolved_settings.market_data_timeout_seconds,
                    ),
                )
                if resolved_settings.sec_user_agent
                else UnavailableBulkFundamentalsProvider(
                    MarketId.US,
                    (
                        "미국 전체시장 재무 검증에는 연락처가 포함된 "
                        "INVESTMENT_OFFICE_SEC_USER_AGENT 설정이 필요합니다."
                    ),
                )
            )
            kr_fundamentals = DartMultiCompanyBulkProvider(
                timeout_seconds=max(
                    60.0,
                    resolved_settings.market_data_timeout_seconds,
                ),
            )
            resolved_full_market_discovery = FullMarketDiscoveryService(
                universe_catalog=universe_catalog,
                fundamentals=CompositeBulkFundamentalsProvider(
                    (us_fundamentals, kr_fundamentals)
                ),
                market_data=limited_market_data,
                max_price_concurrency=max(1, resolved_settings.max_parallel_agents),
            )
        resolved_discovery_jobs = discovery_job_service or DiscoveryJobService()
        resolved_market_overview = market_overview_service
        if (
            resolved_market_overview is None
            and isinstance(resolved_research, ResearchPipeline)
            and limited_research_data is not None
        ):
            resolved_market_overview = MarketOverviewService(limited_research_data)
        committee_service = InvestmentCommittee(
            storage=resolved_storage,
            provider=resolved_provider,
            market_data=limited_market_data,
            broker=broker,
            max_parallel_agents=resolved_settings.max_parallel_agents,
            risk_function=risk_function,
            research_data=limited_research_data,
            provider_semaphore=provider_semaphore,
            run_semaphore=run_semaphore,
        )
        app.state.committee = committee_service
        app.state.research_pipeline = resolved_research
        app.state.market_overview = resolved_market_overview
        app.state.work_items = WorkItemService(
            storage=resolved_storage,
            provider=committee_service.provider,
            broker=broker,
        )
        app.state.committee_broker = CommitteeBroker(
            storage=resolved_storage,
            provider=committee_service.provider,
            event_broker=broker,
        )
        app.state.candidate_discovery = CandidateDiscoveryService(
            market_data=limited_market_data,
            max_concurrency=max(1, resolved_settings.max_parallel_agents),
        )
        app.state.full_market_discovery = resolved_full_market_discovery
        app.state.discovery_jobs = resolved_discovery_jobs
        app.state.decision_archive = DecisionArchiveService(storage=resolved_storage)
        app.state.scheduled_analyses = ScheduledAnalysisService(
            storage=resolved_storage,
            broker=broker,
        )
        app.state.broker = broker
        app.state.tasks = set()
        app.state.schedule_creation_lock = asyncio.Lock()
        app.state.scheduler_status = {
            "status": "starting",
            "error": None,
            "checked_at": None,
        }
        app.state.provider_info = (
            await _probe_codex(resolved_settings.codex_command)
            if provider is None
            else {
                "name": "Injected analysis provider",
                "status": "ready",
                "detail": "테스트 또는 사용자 지정 provider",
                "mode": "injected",
            }
        )
        app.state.database_version = (
            database_runtime.server_version if database_runtime is not None else "in-memory"
        )
        database_lock: Connection | None = None
        if database_runtime is not None:
            database_lock = database_runtime.engine.connect()
            acquired = database_lock.scalar(
                text("SELECT GET_LOCK(:lock_name, 0)"),
                {"lock_name": "pixel_investment_office_single_writer"},
            )
            if acquired != 1:
                database_lock.close()
                database_runtime.engine.dispose()
                raise RuntimeError(
                    "같은 MariaDB를 사용하는 투자 사무실 서버가 이미 실행 중입니다."
                )
        try:
            await cast(InvestmentCommittee, app.state.committee).recover_interrupted_runs()
            await cast(ScheduledAnalysisService, app.state.scheduled_analyses).recover()
            queued_work_items = await cast(WorkItemService, app.state.work_items).recover()
            for item in queued_work_items:
                schedule_work_items_for_app(
                    app,
                    cast(WorkItemService, app.state.work_items),
                    item.analysis_run_id,
                    item.role,
                )
            scheduler_task = asyncio.create_task(
                schedule_poll_loop(app),
                name="scheduled-analysis-poller",
            )
            track_app_task(app, scheduler_task)
            yield
        finally:
            await resolved_discovery_jobs.close()
            tasks: set[asyncio.Task[None]] = app.state.tasks
            for task in tuple(tasks):
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            try:
                close_method = getattr(resolved_market_data, "aclose", None)
                if callable(close_method):
                    close_result = close_method()
                    if asyncio.iscoroutine(close_result):
                        await close_result
            finally:
                if database_lock is not None:
                    with suppress(Exception):
                        database_lock.scalar(
                            text("SELECT RELEASE_LOCK(:lock_name)"),
                            {"lock_name": "pixel_investment_office_single_writer"},
                        )
                    database_lock.close()
                if database_runtime is not None:
                    database_runtime.engine.dispose()

    app = FastAPI(
        title="Pixel Investment Office",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(LOOPBACK_HOSTS),
        www_redirect=False,
    )

    @app.middleware("http")
    async def reject_cross_origin_mutations(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """브라우저의 교차 출처 요청이 로컬 변경 API를 호출하지 못하게 한다."""

        client_host = request.client.host.casefold() if request.client is not None else None
        if client_host is not None and client_host not in LOOPBACK_HOSTS:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "로컬 컴퓨터 밖에서는 이 API에 접근할 수 없습니다."},
            )
        is_mutation = request.method in {"POST", "PUT", "PATCH", "DELETE"}
        if request.url.path.startswith("/api/") and is_mutation:
            origin = request.headers.get("origin")
            expected_origin = str(request.base_url).rstrip("/").casefold()
            if origin is not None and origin.rstrip("/").casefold() != expected_origin:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "다른 출처에서는 로컬 변경 API를 호출할 수 없습니다."},
                )
            fetch_site = request.headers.get("sec-fetch-site")
            if fetch_site is not None and fetch_site.casefold() not in {"same-origin", "none"}:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "교차 사이트 변경 요청이 차단되었습니다."},
                )
        return await call_next(request)

    @app.middleware("http")
    async def add_browser_security_headers(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """모든 로컬 화면과 API 응답에 최소 브라우저 방어 헤더를 적용한다."""

        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    app.mount("/static", StaticFiles(directory=PACKAGE_ROOT / "static"), name="static")

    def committee(request: Request) -> InvestmentCommittee:
        return cast(InvestmentCommittee, request.app.state.committee)

    def work_items(request: Request) -> WorkItemService:
        return cast(WorkItemService, request.app.state.work_items)

    def committee_meetings(request: Request) -> CommitteeBroker:
        return cast(CommitteeBroker, request.app.state.committee_broker)

    def candidate_discovery(request: Request) -> CandidateDiscoveryService:
        return cast(CandidateDiscoveryService, request.app.state.candidate_discovery)

    def full_market_discovery(request: Request) -> FullMarketDiscoveryService:
        return cast(FullMarketDiscoveryService, request.app.state.full_market_discovery)

    def discovery_jobs(request: Request) -> DiscoveryJobService:
        return cast(DiscoveryJobService, request.app.state.discovery_jobs)

    def decision_archive(request: Request) -> DecisionArchiveService:
        return cast(DecisionArchiveService, request.app.state.decision_archive)

    def scheduled_analyses(request: Request) -> ScheduledAnalysisService:
        return cast(ScheduledAnalysisService, request.app.state.scheduled_analyses)

    def build_schedule_payload(request: Request, item: ScheduledAnalysis) -> dict[str, Any]:
        payload = item.model_dump(mode="json")
        candidate = committee(request).storage.get_candidate(item.candidate_id)
        if candidate is not None:
            instrument = resolve_stored_instrument(candidate.ticker, candidate.attributes)
            payload["ticker"] = instrument.symbol
            payload["market"] = instrument.market.value
            payload["canonical_id"] = instrument.canonical_id
            payload["thesis"] = candidate.thesis
        else:
            payload["thesis"] = None
        return payload

    def find_matching_active_schedule(
        request: Request,
        *,
        market: MarketId,
        ticker: str,
        thesis: str | None,
        scheduled_for: AwareDatetime,
    ) -> ScheduledAnalysis | None:
        active_statuses = {
            ScheduledAnalysisStatus.SCHEDULED,
            ScheduledAnalysisStatus.CLAIMED,
            ScheduledAnalysisStatus.DISPATCHED,
        }
        for item in scheduled_analyses(request).list_schedules():
            if item.status not in active_statuses:
                continue
            if item.scheduled_for != scheduled_for:
                continue
            candidate = committee(request).storage.get_candidate(item.candidate_id)
            if candidate is None:
                continue
            instrument = resolve_stored_instrument(candidate.ticker, candidate.attributes)
            if (
                instrument.market is market
                and instrument.symbol == ticker
                and candidate.thesis == thesis
            ):
                return item
        return None

    def build_run_with_schedule(request: Request, run_id: UUID) -> dict[str, Any]:
        payload = committee(request).build_run_payload(run_id)
        schedules = scheduled_analyses(request).list_schedules(run_id=run_id)
        if not schedules:
            return payload
        latest = max(schedules, key=lambda item: (item.updated_at, item.version))
        payload["schedule"] = latest.model_dump(mode="json")
        if payload["workflow"] == "unknown":
            payload["workflow"] = "scheduled"
        if payload["status"] == "queued":
            payload["status"] = latest.status.value
            payload["message"] = {
                ScheduledAnalysisStatus.SCHEDULED: "예약 시각을 기다리고 있습니다.",
                ScheduledAnalysisStatus.CLAIMED: "예약 실행권을 확보했습니다.",
                ScheduledAnalysisStatus.DISPATCHED: "예약 분석을 시작하고 있습니다.",
                ScheduledAnalysisStatus.CANCELLED: "예약이 취소되었습니다.",
                ScheduledAnalysisStatus.FAILED: "예약 분석이 실패했습니다.",
                ScheduledAnalysisStatus.COMPLETED: "예약 분석이 완료되었습니다.",
            }[latest.status]
        return payload

    async def drain_work_items(
        service: WorkItemService,
        run_id: UUID,
        role: AgentRole,
    ) -> None:
        while True:
            try:
                item = await service.run_next(run_id, role)
            except WorkItemTransitionError as exc:
                run = service.storage.get_analysis_run(run_id)
                if (
                    "시장 데이터 스냅샷" in str(exc)
                    and run is not None
                    and run.status.value in {"queued", "running"}
                ):
                    await asyncio.sleep(1)
                    continue
                return
            if item is None:
                return

    def track_app_task(app: FastAPI, task: asyncio.Task[None]) -> None:
        tasks: set[asyncio.Task[None]] = app.state.tasks
        tasks.add(task)

        def consume_result(completed: asyncio.Task[None]) -> None:
            tasks.discard(completed)
            _log_background_task_failure(completed)

        task.add_done_callback(consume_result)

    def track_background_task(request: Request, task: asyncio.Task[None]) -> None:
        track_app_task(request.app, task)

    def schedule_work_items_for_app(
        app: FastAPI,
        service: WorkItemService,
        run_id: UUID,
        role: AgentRole,
    ) -> None:
        task = asyncio.create_task(
            drain_work_items(service, run_id, role),
            name=f"manual-work-{run_id}-{role.value}",
        )
        track_app_task(app, task)

    def schedule_work_items(
        request: Request,
        service: WorkItemService,
        run_id: UUID,
        role: AgentRole,
    ) -> None:
        schedule_work_items_for_app(request.app, service, run_id, role)

    async def dispatch_scheduled_analysis(
        app: FastAPI,
        schedule: ScheduledAnalysis,
    ) -> None:
        service = cast(ScheduledAnalysisService, app.state.scheduled_analyses)
        investment_service = cast(InvestmentCommittee, app.state.committee)
        try:
            await service.mark_dispatched(schedule.id)
            await investment_service.run_analysis(schedule.analysis_run_id)
            run = investment_service.storage.get_analysis_run(schedule.analysis_run_id)
            if run is not None and run.status is AnalysisRunStatus.COMPLETED:
                await service.mark_completed(schedule.id)
            else:
                detail = (
                    run.error_message
                    if run is not None and run.error_message
                    else "예약 분석 실행이 완료 상태에 도달하지 못했습니다."
                )
                await service.mark_failed(schedule.id, detail)
        except asyncio.CancelledError:
            raise
        except (AnalysisRunConflictError, ScheduledAnalysisError):
            return
        except Exception as exc:
            with suppress(ScheduledAnalysisError):
                await service.mark_failed(schedule.id, str(exc)[:4_000])

    async def schedule_poll_loop(app: FastAPI) -> None:
        service = cast(ScheduledAnalysisService, app.state.scheduled_analyses)
        while True:
            try:
                due = await service.claim_due(limit=8)
                for schedule in due:
                    task = asyncio.create_task(
                        dispatch_scheduled_analysis(app, schedule),
                        name=f"scheduled-analysis-{schedule.id}",
                    )
                    track_app_task(app, task)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                app.state.scheduler_status = {
                    "status": "degraded",
                    "error": str(exc)[:1_000],
                    "checked_at": utc_now().isoformat(),
                }
                await asyncio.sleep(5)
                continue
            app.state.scheduler_status = {
                "status": "ready",
                "error": None,
                "checked_at": utc_now().isoformat(),
            }
            await asyncio.sleep(2)

    async def run_directed_speech(
        service: CommitteeBroker,
        run_id: UUID,
        role: AgentRole,
        prompt: str,
    ) -> None:
        try:
            await service.directed_speak(run_id, role, prompt)
        except CommitteeError:
            return

    async def finish_committee(
        service: CommitteeBroker,
        run_id: UUID,
        *,
        stop_reason: str | None = None,
    ) -> None:
        try:
            if stop_reason is None:
                await service.finalize_meeting(run_id)
            else:
                await service.stop_meeting(run_id, stop_reason)
        except CommitteeError:
            return

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request=request, name="index.html", context={})

    @app.get("/office", response_class=HTMLResponse)
    async def office(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request=request, name="office.html", context={})

    @app.get("/analysis", response_class=HTMLResponse)
    async def analysis_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request=request, name="analysis.html", context={})

    @app.get("/markets", response_class=HTMLResponse)
    async def markets_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request=request, name="markets.html", context={})

    @app.get("/discovery", response_class=HTMLResponse)
    async def discovery_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request=request, name="discovery.html", context={})

    @app.get("/history", response_class=HTMLResponse)
    async def history_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request=request, name="history.html", context={})

    @app.get("/api/state")
    async def api_state(request: Request) -> dict[str, Any]:
        service = committee(request)
        runs = service.storage.list_analysis_runs()
        latest_schedules: dict[UUID, ScheduledAnalysis] = {}
        for schedule in scheduled_analyses(request).list_schedules():
            current = latest_schedules.get(schedule.analysis_run_id)
            if current is None or (schedule.updated_at, schedule.version) > (
                current.updated_at,
                current.version,
            ):
                latest_schedules[schedule.analysis_run_id] = schedule
        visible_runs = [
            run
            for run in runs
            if not (
                run.status is AnalysisRunStatus.QUEUED
                and run.id in latest_schedules
                and latest_schedules[run.id].status
                in {
                    ScheduledAnalysisStatus.SCHEDULED,
                    ScheduledAnalysisStatus.CANCELLED,
                    ScheduledAnalysisStatus.FAILED,
                }
            )
        ]
        selected_run = visible_runs[0] if visible_runs else (runs[0] if runs else None)
        latest_run = (
            build_run_with_schedule(request, selected_run.id)
            if selected_run is not None
            else None
        )
        recent_events = service.storage.list_events()[-20:]
        return {
            "provider": request.app.state.provider_info,
            "database": {
                "engine": "MariaDB",
                "version": request.app.state.database_version,
            },
            "scheduler": request.app.state.scheduler_status,
            "latest_run": latest_run,
            "recent_events": [
                {
                    "id": str(event.id),
                    "type": event.event_type.value,
                    "message": event.message,
                    "run_id": str(event.analysis_run_id) if event.analysis_run_id else None,
                    "created_at": event.created_at.isoformat(),
                    **event.payload,
                }
                for event in recent_events
            ],
        }

    @app.get("/api/data-sources")
    async def api_data_sources(request: Request) -> dict[str, Any]:
        """시장별 데이터 공급원 정책과 현재 인증 준비 상태를 공개한다."""

        active_settings = cast(Settings, request.app.state.settings)
        configured_environment = {
            "DATA_GO_KR_SERVICE_KEY": active_settings.data_go_kr_service_key or "",
            "DART_API_KEY": active_settings.dart_api_key or "",
            "SEC_USER_AGENT": active_settings.sec_user_agent or "",
            "BOK_ECOS_API_KEY": active_settings.bok_ecos_api_key or "",
            "TIINGO_API_TOKEN": active_settings.tiingo_api_token or "",
            "MASSIVE_API_KEY": active_settings.massive_api_key or "",
            "KRX_API_KEY": active_settings.krx_api_key or "",
            "KIS_APP_KEY": active_settings.kis_app_key or "",
            "KIS_APP_SECRET": active_settings.kis_app_secret or "",
            "BIGKINDS_API_KEY": active_settings.bigkinds_api_key or "",
            "NAVER_CLIENT_ID": active_settings.naver_client_id or "",
            "NAVER_CLIENT_SECRET": active_settings.naver_client_secret or "",
            "REUTERS_CONNECT_CLIENT_ID": (
                active_settings.reuters_connect_client_id or ""
            ),
            "REUTERS_CONNECT_CLIENT_SECRET": (
                active_settings.reuters_connect_client_secret or ""
            ),
        }
        sources = []
        for policy in list_source_policies(include_disabled=True):
            validation = validate_source_configuration(
                policy.id,
                configured_environment,
                require_analysis=policy.id
                not in {SourceId.BIGKINDS, SourceId.NAVER_NEWS, SourceId.REUTERS},
            )
            sources.append(
                {
                    "policy": policy.model_dump(mode="json"),
                    "status": validation.model_dump(mode="json"),
                }
            )
        return {"sources": sources}

    @app.get("/api/markets/overview")
    async def api_markets_overview(request: Request) -> dict[str, Any]:
        """공통 거시와 미국·한국 시장 국면을 같은 수집 근거로 반환한다."""

        service = cast(MarketOverviewService | None, request.app.state.market_overview)
        if service is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="시장 개요 수집기가 구성되지 않았습니다.",
            )
        overview = await service.build()
        return overview.model_dump(mode="json")

    @app.post("/api/analyze", status_code=status.HTTP_202_ACCEPTED)
    async def api_analyze(payload: AnalyzeRequest, request: Request) -> dict[str, Any]:
        service = committee(request)
        try:
            run = await service.create_analysis(
                payload.ticker,
                payload.thesis,
                market=payload.market,
                workflow="manual",
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        task = asyncio.create_task(service.run_analysis(run.id), name=f"analysis-{run.id}")
        track_background_task(request, task)
        return {"run_id": str(run.id), "run": build_run_with_schedule(request, run.id)}

    @app.post(
        "/api/discoveries/scans",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def api_create_discovery_scan(
        payload: DiscoveryScreenRequest,
        request: Request,
    ) -> dict[str, Any]:
        runner = full_market_discovery(request).runner(
            market=payload.market,
            strategy=payload.strategy,
            risk_profile=payload.risk_profile,
            limit=payload.limit,
            force_refresh=payload.force_refresh,
        )
        job_id = discovery_jobs(request).create(runner)
        return {"job": discovery_jobs(request).get(job_id).model_dump(mode="json")}

    @app.get("/api/discoveries/scans/{job_id}")
    async def api_get_discovery_scan(
        job_id: UUID,
        request: Request,
    ) -> dict[str, Any]:
        try:
            job = discovery_jobs(request).get(job_id)
        except DiscoveryJobNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"job": job.model_dump(mode="json")}

    @app.post("/api/discoveries/screen")
    async def api_discovery_screen(
        payload: DiscoveryScreenRequest,
        request: Request,
    ) -> dict[str, Any]:
        try:
            result = await candidate_discovery(request).screen(
                strategy=payload.strategy,
                limit=payload.limit,
                market=payload.market,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"discovery": result.model_dump(mode="json")}

    @app.post("/api/discoveries/analyze", status_code=status.HTTP_202_ACCEPTED)
    async def api_discovery_analyze(
        payload: DiscoveryAnalyzeRequest,
        request: Request,
    ) -> dict[str, Any]:
        service = committee(request)
        runs: list[dict[str, Any]] = []
        discovery_batch_id = str(uuid4())
        for ticker in payload.tickers:
            try:
                run = await service.create_analysis(
                    ticker,
                    DISCOVERY_ANALYSIS_THESIS,
                    market=payload.market,
                    workflow="discovery",
                    discovery_batch_id=discovery_batch_id,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            created_run = service.build_run_payload(run.id)
            task = asyncio.create_task(
                service.run_analysis(run.id),
                name=f"discovery-analysis-{run.id}",
            )
            track_background_task(request, task)
            runs.append(
                {
                    "run_id": str(run.id),
                    "ticker": ticker,
                    "company_name": created_run["company_name"],
                    "market": payload.market.value,
                    "status": run.status.value,
                    "workflow": "discovery",
                    "discovery_batch_id": discovery_batch_id,
                }
            )
        return {
            "runs": runs,
            "discovery_batch_id": discovery_batch_id,
            "human_approval_required": True,
            "auto_trade": False,
        }

    @app.get("/api/schedules")
    async def api_schedules(request: Request) -> dict[str, Any]:
        items = scheduled_analyses(request).list_schedules()
        return {"schedules": [build_schedule_payload(request, item) for item in items]}

    @app.post("/api/schedules", status_code=status.HTTP_202_ACCEPTED)
    async def api_create_schedule(
        payload: ScheduleAnalysisRequest,
        request: Request,
    ) -> dict[str, Any]:
        now = utc_now()
        scheduled_utc = payload.scheduled_for.astimezone(UTC)
        if scheduled_utc <= now:
            raise HTTPException(status_code=422, detail="예약 시각은 현재보다 미래여야 합니다.")
        if scheduled_utc > now + timedelta(days=366):
            raise HTTPException(
                status_code=422,
                detail="예약은 1년 이내 시각만 지정할 수 있습니다.",
            )

        investment_service = committee(request)
        schedule_service = scheduled_analyses(request)
        creation_lock = cast(asyncio.Lock, request.app.state.schedule_creation_lock)
        async with creation_lock:
            existing = find_matching_active_schedule(
                request,
                market=payload.market,
                ticker=payload.ticker,
                thesis=payload.thesis,
                scheduled_for=payload.scheduled_for,
            )
            if existing is not None:
                return {
                    "schedule": build_schedule_payload(request, existing),
                    "run": build_run_with_schedule(request, existing.analysis_run_id),
                    "deduplicated": True,
                }
            run = await investment_service.create_analysis(
                payload.ticker,
                payload.thesis,
                market=payload.market,
                workflow="scheduled",
            )
            try:
                item = await schedule_service.schedule_run(
                    run.id,
                    payload.scheduled_for,
                )
            except Exception as exc:
                with suppress(Exception):
                    await investment_service.cancel_queued_analysis(
                        run.id,
                        f"예약 등록 실패. {str(exc)[:3_900]}",
                    )
                if isinstance(exc, ScheduledAnalysisValidationError):
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                if isinstance(exc, ScheduledAnalysisConflictError):
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
                raise
        return {
            "schedule": build_schedule_payload(request, item),
            "run": build_run_with_schedule(request, run.id),
            "deduplicated": False,
        }

    @app.get("/api/schedules/{schedule_id}")
    async def api_schedule(schedule_id: UUID, request: Request) -> dict[str, Any]:
        try:
            item = scheduled_analyses(request).get_schedule(schedule_id)
        except ScheduledAnalysisNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"schedule": build_schedule_payload(request, item)}

    @app.post("/api/schedules/{schedule_id}/cancel")
    async def api_cancel_schedule(schedule_id: UUID, request: Request) -> dict[str, Any]:
        try:
            item = await scheduled_analyses(request).cancel(schedule_id)
        except ScheduledAnalysisNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ScheduledAnalysisTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"schedule": build_schedule_payload(request, item)}

    @app.get("/api/runs")
    async def api_runs(
        request: Request,
        workflow: Literal["manual", "discovery", "scheduled", "unknown"] | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 200:
            raise HTTPException(status_code=422, detail="limit은 1~200이어야 합니다.")

        payloads = [
            build_run_with_schedule(request, run.id)
            for run in committee(request).storage.list_analysis_runs()
        ]
        by_workflow = {name: 0 for name in ("manual", "discovery", "scheduled", "unknown")}
        by_status: dict[str, int] = {}
        for payload in payloads:
            workflow_name = str(payload["workflow"])
            by_workflow[workflow_name] = by_workflow.get(workflow_name, 0) + 1
            status_name = str(payload["status"])
            by_status[status_name] = by_status.get(status_name, 0) + 1

        normalized_status = status.strip().lower() if status else None
        filtered = [
            payload
            for payload in payloads
            if (workflow is None or payload["workflow"] == workflow)
            and (normalized_status is None or payload["status"] == normalized_status)
        ]
        selected = filtered[:limit]
        return {
            "runs": selected,
            "summary": {
                "total": len(payloads),
                "filtered_total": len(filtered),
                "returned": len(selected),
                "by_workflow": by_workflow,
                "by_status": dict(sorted(by_status.items())),
            },
        }

    @app.get("/api/runs/{run_id}")
    async def api_run(run_id: UUID, request: Request) -> dict[str, Any]:
        try:
            return {"run": build_run_with_schedule(request, run_id)}
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/decisions")
    async def api_decisions(
        request: Request,
        ticker: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 200:
            raise HTTPException(status_code=422, detail="limit은 1~200이어야 합니다.")
        try:
            entries = decision_archive(request).list_entries(ticker=ticker, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except DecisionArchiveNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"decisions": [entry.model_dump(mode="json") for entry in entries]}

    @app.get("/api/decisions/{run_id}")
    async def api_decision(run_id: UUID, request: Request) -> dict[str, Any]:
        try:
            entry = decision_archive(request).get_entry(run_id)
        except DecisionArchiveNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"decision": entry.model_dump(mode="json")}

    @app.get("/api/runs/{run_id}/tasks")
    async def api_work_items(run_id: UUID, request: Request) -> dict[str, Any]:
        service = work_items(request)
        try:
            items = service.list_work_items(run_id)
        except WorkItemNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"tasks": [item.model_dump(mode="json") for item in items]}

    @app.post("/api/runs/{run_id}/tasks", status_code=status.HTTP_202_ACCEPTED)
    async def api_create_work_item(
        run_id: UUID,
        payload: CreateWorkItemRequest,
        request: Request,
    ) -> dict[str, Any]:
        service = work_items(request)
        try:
            item = await service.create_work_item(
                run_id=run_id,
                role=payload.role,
                title=payload.title,
                instructions=payload.instructions,
            )
        except WorkItemNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (WorkItemTransitionError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        schedule_work_items(request, service, run_id, payload.role)
        return {"task": item.model_dump(mode="json")}

    @app.post("/api/tasks/{task_id}/report-requests")
    async def api_request_work_report(task_id: UUID, request: Request) -> dict[str, Any]:
        service = work_items(request)
        item = service.find_work_item(task_id)
        if item is None:
            raise HTTPException(status_code=404, detail="수동 업무 항목을 찾을 수 없습니다.")
        report = service.request_report(item.analysis_run_id, item.id)
        return {"report": report.model_dump(mode="json")}

    @app.post("/api/tasks/{task_id}/resume", status_code=status.HTTP_202_ACCEPTED)
    async def api_resume_work_item(task_id: UUID, request: Request) -> dict[str, Any]:
        service = work_items(request)
        item = service.find_work_item(task_id)
        if item is None:
            raise HTTPException(status_code=404, detail="수동 업무 항목을 찾을 수 없습니다.")
        try:
            resumed = await service.resume_work_item(item.analysis_run_id, item.id)
        except WorkItemTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        schedule_work_items(request, service, resumed.analysis_run_id, resumed.role)
        return {"task": resumed.model_dump(mode="json")}

    @app.post("/api/tasks/{task_id}/cancel")
    async def api_cancel_work_item(task_id: UUID, request: Request) -> dict[str, Any]:
        service = work_items(request)
        item = service.find_work_item(task_id)
        if item is None:
            raise HTTPException(status_code=404, detail="수동 업무 항목을 찾을 수 없습니다.")
        try:
            cancelled = await service.cancel_work_item(item.analysis_run_id, item.id)
        except WorkItemTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"task": cancelled.model_dump(mode="json")}

    @app.get("/api/runs/{run_id}/committee")
    async def api_latest_committee(run_id: UUID, request: Request) -> dict[str, Any]:
        if committee(request).storage.get_analysis_run(run_id) is None:
            raise HTTPException(status_code=404, detail="분석 실행을 찾을 수 없습니다.")
        state = committee_meetings(request).get_latest_state(run_id)
        return {"committee": state.model_dump(mode="json") if state is not None else None}

    @app.post(
        "/api/runs/{run_id}/committee/start",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def api_start_committee(
        run_id: UUID,
        payload: StartCommitteeRequest,
        request: Request,
    ) -> dict[str, Any]:
        service = committee_meetings(request)
        try:
            state = await service.start_meeting(
                run_id,
                topic=payload.topic,
                roles=payload.participants,
                max_turns=payload.max_turns,
            )
        except CommitteeNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except CommitteeConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except CommitteeValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"committee": state.model_dump(mode="json")}

    @app.get("/api/committee/{session_id}")
    async def api_committee(session_id: UUID, request: Request) -> dict[str, Any]:
        state = committee_meetings(request).get_state(session_id)
        if state is None:
            raise HTTPException(status_code=404, detail="투자위원회 회의를 찾을 수 없습니다.")
        return {"committee": state.model_dump(mode="json")}

    @app.post(
        "/api/committee/{session_id}/commands",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def api_committee_command(
        session_id: UUID,
        payload: CommitteeCommandRequest,
        request: Request,
    ) -> dict[str, Any]:
        service = committee_meetings(request)
        state = service.get_state(session_id)
        if state is None:
            raise HTTPException(status_code=404, detail="투자위원회 회의를 찾을 수 없습니다.")
        if not service.is_active(state.analysis_run_id):
            raise HTTPException(
                status_code=409,
                detail="이미 종료된 회의에는 명령을 보낼 수 없습니다.",
            )

        if payload.command in {"request_speech", "directed_speak"}:
            prompt = (payload.prompt or "").strip()
            if payload.role is None or not prompt:
                raise HTTPException(status_code=422, detail="추가 발언의 역할과 질문이 필요합니다.")
            if payload.role not in state.selected_roles:
                raise HTTPException(
                    status_code=422,
                    detail="선택된 참가 역할만 발언할 수 있습니다.",
                )
            if len(state.turns) >= state.max_turns:
                raise HTTPException(status_code=409, detail="회의의 최대 발언 수에 도달했습니다.")
            task = asyncio.create_task(
                run_directed_speech(
                    service,
                    state.analysis_run_id,
                    payload.role,
                    prompt,
                ),
                name=f"committee-speech-{session_id}-{payload.role.value}",
            )
        else:
            stop_reason = None
            if payload.command == "stop":
                stop_reason = (
                    payload.reason or "사용자가 게임 화면에서 회의를 중단했습니다."
                ).strip()
            task = asyncio.create_task(
                finish_committee(
                    service,
                    state.analysis_run_id,
                    stop_reason=stop_reason,
                ),
                name=f"committee-{payload.command}-{session_id}",
            )
        track_background_task(request, task)
        await asyncio.sleep(0)
        current = service.get_latest_state(state.analysis_run_id) or state
        return {"accepted": True, "committee": current.model_dump(mode="json")}

    @app.get("/api/committee/{session_id}/minutes")
    async def api_committee_minutes(session_id: UUID, request: Request) -> dict[str, Any]:
        service = committee_meetings(request)
        state = service.get_state(session_id)
        if state is None:
            raise HTTPException(status_code=404, detail="투자위원회 회의를 찾을 수 없습니다.")
        minutes = service.get_minutes(session_id)
        return {"minutes": minutes.model_dump(mode="json") if minutes is not None else None}

    @app.post("/api/runs/{run_id}/review")
    async def api_review(
        run_id: UUID,
        payload: ReviewRequest,
        request: Request,
    ) -> dict[str, Any]:
        service = committee(request)
        try:
            review = await service.record_review(run_id, payload.decision, payload.reason)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "review": review.model_dump(mode="json"),
            "run": service.build_run_payload(run_id),
        }

    @app.get("/api/events")
    async def api_events(request: Request) -> StreamingResponse:
        broker = cast(EventBroker, request.app.state.broker)

        async def stream() -> AsyncIterator[str]:
            initial = {
                "type": "provider",
                "provider": request.app.state.provider_info,
            }
            yield f"event: provider\ndata: {json.dumps(initial, ensure_ascii=False)}\n\n"
            async with broker.subscribe() as queue:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        heartbeat = json.dumps(
                            {"type": "heartbeat", "message": "연결 유지"},
                            ensure_ascii=False,
                        )
                        yield f"event: heartbeat\ndata: {heartbeat}\n\n"
                        continue
                    event_name = str(event.get("type", "message"))
                    event_id = str(event.get("event_id", ""))
                    encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    yield f"id: {event_id}\nevent: {event_name}\ndata: {encoded}\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return app


app = create_app()


def run() -> None:
    """설정된 로컬 주소에서 개발 서버를 실행한다."""

    settings = get_settings()
    uvicorn.run(
        "investment_office.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        run()
