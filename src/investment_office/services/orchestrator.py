# 여섯 투자 에이전트와 리스크 정책을 순서대로 실행해 사람 검토안을 만든다.
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any, Literal, Protocol, cast
from uuid import UUID

from pydantic import JsonValue, TypeAdapter

from investment_office.domain import (
    AgentOutput,
    AgentOutputStatus,
    AgentRole,
    AnalysisRun,
    AnalysisRunStatus,
    Candidate,
    CandidateSource,
    CandidateStatus,
    Event,
    EventType,
    Evidence,
    HumanReview,
    ReviewDecision,
    Snapshot,
    SnapshotKind,
    utc_now,
)
from investment_office.services.event_broker import EventBroker
from investment_office.services.instrument_identity import (
    InstrumentIdentity,
    normalize_instrument,
    resolve_stored_instrument,
)
from investment_office.services.market_data import EODSnapshot
from investment_office.services.research_contracts import InstrumentRef, MarketId
from investment_office.services.research_pipeline import ResearchPipelineResult
from investment_office.services.risk import RiskAssessment, assess_risk
from investment_office.storage import Storage

JsonDict = dict[str, JsonValue]
JSON_DICT_ADAPTER = TypeAdapter(JsonDict)
AnalysisWorkflow = Literal["manual", "discovery", "scheduled"]
AnalysisWorkflowView = Literal["manual", "discovery", "scheduled", "unknown"]
DISCOVERY_ANALYSIS_THESIS = (
    "가격·거래량 기반 1차 후보 발굴을 통과했다. 매수 보장이 아니므로 "
    "실적·밸류에이션·뉴스 데이터 공백과 무효화 조건까지 심층 검토한다."
)
logger = logging.getLogger(__name__)


class AnalysisProvider(Protocol):
    async def analyze(
        self,
        role: str,
        ticker: str,
        snapshot: dict[str, Any],
        context: list[dict[str, Any]],
    ) -> dict[str, Any]: ...


class EODMarketDataClient(Protocol):
    async def fetch_eod_snapshot(self, ticker: str) -> EODSnapshot: ...


class ResearchDataClient(Protocol):
    async def collect(
        self,
        instrument: InstrumentRef,
        snapshot: EODSnapshot,
    ) -> ResearchPipelineResult: ...


RiskFunction = Callable[[EODSnapshot, dict[str, Any]], RiskAssessment]


class AnalysisRunConflictError(RuntimeError):
    """대기 중이 아닌 분석 실행을 중복 시작하려 할 때 발생한다."""


class InvestmentCommittee:
    """시장 스냅샷부터 사람 검토 직전 결정 카드까지 생성한다."""

    def __init__(
        self,
        *,
        storage: Storage,
        provider: AnalysisProvider,
        market_data: EODMarketDataClient,
        broker: EventBroker,
        max_parallel_agents: int = 3,
        risk_function: RiskFunction = assess_risk,
        research_data: ResearchDataClient | None = None,
    ) -> None:
        self.storage = storage
        self.provider = provider
        self.market_data = market_data
        self.broker = broker
        self._semaphore = asyncio.Semaphore(max_parallel_agents)
        self._risk_function = risk_function
        self.research_data = research_data

    async def create_analysis(
        self,
        ticker: str,
        thesis: str | None = None,
        *,
        market: MarketId | str = MarketId.US,
        workflow: AnalysisWorkflow = "manual",
        discovery_batch_id: str | None = None,
    ) -> AnalysisRun:
        """사용자 후보와 대기 중인 분석 실행을 기록한다."""

        if workflow not in {"manual", "discovery", "scheduled"}:
            raise ValueError("workflow는 manual, discovery, scheduled 중 하나여야 합니다.")
        normalized_batch_id = discovery_batch_id.strip() if discovery_batch_id else None
        if discovery_batch_id is not None and not normalized_batch_id:
            raise ValueError("discovery_batch_id는 공백일 수 없습니다.")

        instrument = normalize_instrument(market, ticker)
        candidate = Candidate(
            ticker=instrument.storage_ticker,
            thesis=thesis,
            source=CandidateSource.USER,
            attributes={
                "market": instrument.market.value,
                "local_symbol": instrument.symbol,
                "canonical_id": instrument.canonical_id,
                "currency": instrument.currency,
                "data_contract_version": "1.0",
            },
        )
        self.storage.save_candidate(candidate)
        configuration: JsonDict = {
            "execution": "human_in_the_loop",
            "auto_trade": False,
            "agent_count": 6,
            "workflow": workflow,
            "market": instrument.market.value,
            "local_symbol": instrument.symbol,
            "canonical_id": instrument.canonical_id,
            "data_contract_version": "1.0",
        }
        if normalized_batch_id is not None:
            configuration["discovery_batch_id"] = normalized_batch_id
        run = AnalysisRun(
            candidate_id=candidate.id,
            configuration=configuration,
        )
        self.storage.save_analysis_run(run)
        self.storage.save_snapshot(
            Snapshot(
                candidate_id=candidate.id,
                analysis_run_id=run.id,
                kind=SnapshotKind.INPUT,
                data=JSON_DICT_ADAPTER.validate_python(
                    {
                        "ticker": instrument.symbol,
                        "market": instrument.market.value,
                        "canonical_id": instrument.canonical_id,
                        "thesis": candidate.thesis,
                    }
                ),
            )
        )
        await self._record_event(
            EventType.CANDIDATE_CREATED,
            f"{instrument.symbol} 후보가 접수되었습니다.",
            candidate=candidate,
            run=run,
            stream_type="analysis",
        )
        await self._record_event(
            EventType.ANALYSIS_QUEUED,
            "투자위원회 분석이 대기열에 등록되었습니다.",
            candidate=candidate,
            run=run,
            stream_type="run",
        )
        return run

    async def cancel_queued_analysis(self, run_id: UUID, reason: str) -> AnalysisRun:
        """후속 등록 실패로 실행할 수 없는 대기 분석을 취소 상태로 확정한다."""

        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("분석 취소 사유는 비어 있을 수 없습니다.")
        run = self._require_run(run_id)
        candidate = self._require_candidate(run.candidate_id)
        if run.status is not AnalysisRunStatus.QUEUED:
            raise AnalysisRunConflictError("대기 중인 분석만 등록 실패로 취소할 수 있습니다.")
        cancelled_at = utc_now()
        run.status = AnalysisRunStatus.CANCELLED
        run.error_message = normalized_reason[:4_000]
        run.completed_at = cancelled_at
        run.updated_at = cancelled_at
        candidate.status = CandidateStatus.ARCHIVED
        candidate.updated_at = cancelled_at
        self.storage.save_analysis_run(run)
        self.storage.save_candidate(candidate)
        await self._record_event(
            EventType.STATUS_CHANGED,
            "후속 등록 실패로 대기 분석을 취소했습니다.",
            candidate=candidate,
            run=run,
            stream_type="fault",
            payload={"status": "cancelled", "error": run.error_message},
        )
        return run

    async def run_analysis(self, run_id: UUID) -> None:
        """한 분석 실행을 완료하거나 실패 상태로 확정한다."""

        run = self._require_run(run_id)
        if run.status is not AnalysisRunStatus.QUEUED:
            raise AnalysisRunConflictError(
                f"대기 중인 분석만 시작할 수 있습니다. 현재 상태는 {run.status.value}입니다."
            )
        candidate = self._require_candidate(run.candidate_id)
        now = utc_now()
        run.status = AnalysisRunStatus.RUNNING
        run.started_at = now
        run.updated_at = now
        candidate.status = CandidateStatus.ANALYZING
        candidate.updated_at = now
        self.storage.save_analysis_run(run)
        self.storage.save_candidate(candidate)
        await self._record_event(
            EventType.ANALYSIS_STARTED,
            "시장 데이터 수집을 시작했습니다.",
            candidate=candidate,
            run=run,
            stream_type="run",
        )

        try:
            instrument = self._candidate_instrument(candidate)
            market_snapshot = await self.market_data.fetch_eod_snapshot(
                instrument.storage_ticker
            )
            market_payload = market_snapshot.model_dump(mode="json")
            market_payload.update(
                {
                    "market": instrument.market.value,
                    "canonical_id": instrument.canonical_id,
                    "local_symbol": instrument.symbol,
                }
            )
            if self.research_data is not None:
                research_instrument = InstrumentRef(
                    market=instrument.market,
                    symbol=instrument.symbol,
                    exchange=market_snapshot.exchange,
                    currency=market_snapshot.currency,
                )
                research = await self.research_data.collect(
                    research_instrument,
                    market_snapshot,
                )
                market_payload.update(
                    {
                        "research_bundle": research.bundle.model_dump(mode="json"),
                        "research_quality": research.bundle.quality.model_dump(mode="json"),
                        "market_regime": research.regime.model_dump(mode="json"),
                        "fundamentals": research.fundamentals,
                        "news": research.news,
                        "macro": research.macro,
                        "observation_cutoff": research.observation_cutoff.isoformat(),
                    }
                )
            self.storage.save_snapshot(
                Snapshot(
                    candidate_id=candidate.id,
                    analysis_run_id=run.id,
                    kind=SnapshotKind.MARKET_DATA,
                    data=JSON_DICT_ADAPTER.validate_python(market_payload),
                )
            )

            first_stage = await self._run_agent_stage(
                self._run_agent(run, candidate, AgentRole.FUNDAMENTAL, market_payload, []),
                self._run_agent(run, candidate, AgentRole.TECHNICAL, market_payload, []),
                self._run_agent(run, candidate, AgentRole.NEWS, market_payload, []),
            )
            first_context = [result.model_dump(mode="json") for result in first_stage]
            debate = await self._run_agent_stage(
                self._run_agent(run, candidate, AgentRole.BULL, market_payload, first_context),
                self._run_agent(run, candidate, AgentRole.BEAR, market_payload, first_context),
            )
            committee_context = first_context + [
                result.model_dump(mode="json") for result in debate
            ]
            chairman = await self._run_agent(
                run,
                candidate,
                AgentRole.HEAD_TRADER,
                market_payload,
                committee_context,
            )
            agent_outputs = [*first_stage, *debate, chairman]
            chairman_payload = dict(cast(dict[str, Any], chairman.data))
            chairman_payload["data_gaps"] = self._merge_data_gaps(
                *(cast(dict[str, Any], output.data) for output in agent_outputs)
            )
            risk = self._risk_function(market_snapshot, chairman_payload)
            risk_payload = risk.model_dump(mode="json")
            risk_payload["data_gaps"] = self._merge_data_gaps(
                chairman_payload,
                risk_payload,
            )
            risk_payload = self._apply_research_risk_gates(
                risk_payload,
                market_payload,
            )
            missing_required_roles = [
                role
                for role in (AgentRole.FUNDAMENTAL, AgentRole.NEWS)
                if self._role_input_is_missing(role, market_payload)
            ]
            if missing_required_roles:
                role_names = [
                    "재무·공시" if role is AgentRole.FUNDAMENTAL else "뉴스"
                    for role in missing_required_roles
                ]
                warning = (
                    f"필수 분석 자료({', '.join(role_names)})가 없어 "
                    "신규 포지션을 차단합니다."
                )
                if str(risk_payload.get("action", "")).strip().casefold() == "size_position":
                    risk_payload["action"] = "watch"
                risk_payload["eligible"] = False
                risk_payload["position_cap_pct"] = 0.0
                risk_payload["warnings"] = list(
                    dict.fromkeys(
                        [
                            *(
                                str(item)
                                for item in risk_payload.get("warnings", [])
                                if str(item).strip()
                            ),
                            warning,
                        ]
                    )
                )
            risk_output = AgentOutput(
                analysis_run_id=run.id,
                role=AgentRole.RISK_MANAGER,
                status=AgentOutputStatus.COMPLETED,
                content="결정론적 리스크 정책이 비중과 무효화 조건을 계산했습니다.",
                data=JSON_DICT_ADAPTER.validate_python(risk_payload),
            )
            self.storage.save_agent_output(risk_output)

            decision = self._build_decision(
                candidate,
                chairman_payload,
                risk_payload,
                research_quality=market_payload.get("research_quality"),
                market_regime=market_payload.get("market_regime"),
            )
            self.storage.save_snapshot(
                Snapshot(
                    candidate_id=candidate.id,
                    analysis_run_id=run.id,
                    kind=SnapshotKind.DECISION,
                    data=JSON_DICT_ADAPTER.validate_python(decision),
                )
            )
            finished = utc_now()
            run.status = AnalysisRunStatus.COMPLETED
            run.completed_at = finished
            run.updated_at = finished
            candidate.status = CandidateStatus.READY_FOR_REVIEW
            candidate.updated_at = finished
            self.storage.save_analysis_run(run)
            self.storage.save_candidate(candidate)
            await self._record_event(
                EventType.ANALYSIS_COMPLETED,
                "위원장 초안이 도착했습니다. 사람의 검토가 필요합니다.",
                candidate=candidate,
                run=run,
                stream_type="run",
                payload={"decision": decision},
            )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                raise
            failed_at = utc_now()
            run.status = AnalysisRunStatus.FAILED
            run.error_message = str(exc)[:4_000]
            run.completed_at = failed_at
            run.updated_at = failed_at
            candidate.status = CandidateStatus.QUEUED
            candidate.updated_at = failed_at
            self.storage.save_analysis_run(run)
            self.storage.save_candidate(candidate)
            await self._record_event(
                EventType.ANALYSIS_FAILED,
                f"분석이 실패했습니다. {str(exc)[:500]}",
                candidate=candidate,
                run=run,
                stream_type="fault",
            )

    async def recover_interrupted_runs(self) -> list[AnalysisRun]:
        """서버 재시작 전에 실행 중이던 분석을 명시적인 실패 상태로 복구한다."""

        recovered: list[AnalysisRun] = []
        for run in self.storage.list_analysis_runs(status=AnalysisRunStatus.RUNNING):
            candidate = self._require_candidate(run.candidate_id)
            failed_at = utc_now()
            detail = (
                "서버 재시작으로 분석 실행이 중단되었습니다. 저장된 부분 결과를 확인한 뒤 "
                "필요하면 새 분석을 요청하세요."
            )
            for output in self.storage.list_agent_outputs(run.id):
                if output.status is not AgentOutputStatus.RUNNING:
                    continue
                output.status = AgentOutputStatus.FAILED
                output.error_message = detail
                output.updated_at = failed_at
                self.storage.save_agent_output(output)
            run.status = AnalysisRunStatus.FAILED
            run.error_message = detail
            run.completed_at = failed_at
            run.updated_at = failed_at
            candidate.status = CandidateStatus.QUEUED
            candidate.updated_at = failed_at
            self.storage.save_analysis_run(run)
            self.storage.save_candidate(candidate)
            await self._record_event(
                EventType.ANALYSIS_FAILED,
                detail,
                candidate=candidate,
                run=run,
                stream_type="fault",
            )
            recovered.append(run)
        return recovered

    async def record_review(
        self,
        run_id: UUID,
        decision: ReviewDecision,
        reason: str,
    ) -> HumanReview:
        """완료된 초안에 대한 사람의 최종 게이트 결정을 기록한다."""

        run = self._require_run(run_id)
        candidate = self._require_candidate(run.candidate_id)
        if run.status is not AnalysisRunStatus.COMPLETED:
            raise ValueError("완료된 분석만 검토할 수 있습니다.")
        if self.storage.list_human_reviews(run.id):
            raise ValueError("이 분석에는 이미 사람의 결정이 기록되었습니다.")
        review = HumanReview(
            candidate_id=candidate.id,
            analysis_run_id=run.id,
            decision=decision,
            rationale=reason,
        )
        self.storage.save_human_review(review)
        if decision is ReviewDecision.APPROVED:
            candidate.status = CandidateStatus.APPROVED
        elif decision is ReviewDecision.REJECTED:
            candidate.status = CandidateStatus.REJECTED
        else:
            candidate.status = CandidateStatus.READY_FOR_REVIEW
        candidate.updated_at = utc_now()
        self.storage.save_candidate(candidate)
        await self._record_event(
            EventType.HUMAN_REVIEW_RECORDED,
            f"사람의 결정이 기록되었습니다. {decision.value}",
            candidate=candidate,
            run=run,
            stream_type="review",
            payload={"decision": decision.value, "reason": reason},
        )
        return review

    def build_run_payload(self, run_id: UUID) -> dict[str, Any]:
        """프런트엔드가 바로 소비할 수 있는 실행 상태를 조립한다."""

        run = self._require_run(run_id)
        candidate = self._require_candidate(run.candidate_id)
        outputs = self.storage.list_agent_outputs(run.id)
        visible_outputs = [
            output for output in outputs if output.role is not AgentRole.RISK_MANAGER
        ]
        reviews = self.storage.list_human_reviews(run.id)
        decisions = self.storage.list_snapshots(run.id, kind=SnapshotKind.DECISION)
        review = reviews[0] if reviews else None
        decision = decisions[0].data if decisions else None
        workflow, discovery_batch_id = self._workflow_metadata(run, candidate)
        instrument = self._candidate_instrument(candidate)

        status = run.status.value
        if run.status is AnalysisRunStatus.COMPLETED:
            if review is None:
                status = "review"
            elif review.decision is ReviewDecision.APPROVED:
                status = "approved"
            elif review.decision is ReviewDecision.REJECTED:
                status = "rejected"
            else:
                status = "hold"

        agents = [self._output_payload(output) for output in visible_outputs]
        completed_count = len([item for item in agents if item["status"] == "done"])
        progress = min(100, round(completed_count / 6 * 100))
        return {
            "run_id": str(run.id),
            "candidate_id": str(candidate.id),
            "ticker": instrument.symbol,
            "market": instrument.market.value,
            "canonical_id": instrument.canonical_id,
            "thesis": candidate.thesis,
            "workflow": workflow,
            "discovery_batch_id": discovery_batch_id,
            "status": status,
            "progress": progress,
            "message": self._status_message(status),
            "created_at": run.requested_at.isoformat(),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "agents": agents,
            "decision": decision,
            "human_review": (
                {
                    "decision": review.decision.value,
                    "reason": review.rationale,
                    "created_at": review.created_at.isoformat(),
                }
                if review
                else None
            ),
            "error": run.error_message,
        }

    def _workflow_metadata(
        self,
        run: AnalysisRun,
        candidate: Candidate,
    ) -> tuple[AnalysisWorkflowView, str | None]:
        configured_workflow = run.configuration.get("workflow")
        if configured_workflow == "manual":
            workflow: AnalysisWorkflowView = "manual"
        elif configured_workflow == "discovery":
            workflow = "discovery"
        elif configured_workflow == "scheduled" or self._has_schedule_snapshot(run.id):
            workflow = "scheduled"
        elif candidate.thesis == DISCOVERY_ANALYSIS_THESIS:
            workflow = "discovery"
        else:
            workflow = "unknown"

        configured_batch_id = run.configuration.get("discovery_batch_id")
        discovery_batch_id = (
            configured_batch_id.strip()
            if isinstance(configured_batch_id, str) and configured_batch_id.strip()
            else None
        )
        return workflow, discovery_batch_id

    def _has_schedule_snapshot(self, run_id: UUID) -> bool:
        return any(
            snapshot.data.get("record_type") == "scheduled_analysis"
            for snapshot in self.storage.list_snapshots(run_id, kind=SnapshotKind.AGENT_STATE)
        )

    @staticmethod
    async def _run_agent_stage(
        *jobs: Coroutine[Any, Any, AgentOutput],
    ) -> list[AgentOutput]:
        """한 단계가 실패하면 아직 실행 중인 형제 에이전트를 모두 회수한다."""

        tasks = [asyncio.create_task(job) for job in jobs]
        try:
            return await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def _run_agent(
        self,
        run: AnalysisRun,
        candidate: Candidate,
        role: AgentRole,
        snapshot: dict[str, Any],
        context: list[dict[str, Any]],
    ) -> AgentOutput:
        output = AgentOutput(
            analysis_run_id=run.id,
            role=role,
            status=AgentOutputStatus.RUNNING,
        )
        self.storage.save_agent_output(output)
        await self._record_event(
            EventType.STATUS_CHANGED,
            f"{role.value} 에이전트가 분석을 시작했습니다.",
            candidate=candidate,
            run=run,
            stream_type="agent",
            payload={"role": role.value, "status": "running"},
        )
        try:
            instrument = self._candidate_instrument(candidate)
            if self._role_input_is_missing(role, snapshot):
                result = self._data_gap_result(role, instrument.symbol)
            else:
                async with self._semaphore:
                    result = await self.provider.analyze(
                        role.value, instrument.symbol, snapshot, context
                    )
            validated = JSON_DICT_ADAPTER.validate_python(result)
            evidence = [
                Evidence(
                    title=str(item.get("claim", "근거")),
                    fact_id=item.get("fact_id"),
                    url=item.get("source_url"),
                    published_at=item.get("published_at"),
                )
                for item in result.get("evidence", [])
                if isinstance(item, dict)
            ]
            output.status = AgentOutputStatus.COMPLETED
            output.content = str(result.get("summary", ""))
            output.confidence = float(result["confidence"])
            output.evidence = evidence
            output.data = validated
            output.updated_at = utc_now()
            self.storage.save_agent_output(output)
            await self._record_event(
                EventType.AGENT_OUTPUT_RECORDED,
                f"{role.value} 에이전트가 의견을 제출했습니다.",
                candidate=candidate,
                run=run,
                stream_type="agent",
                payload={
                    "role": role.value,
                    "status": "done",
                    "summary": output.content,
                },
            )
            return output
        except asyncio.CancelledError:
            detail = "에이전트 실행 태스크가 취소되었습니다."
            output.status = AgentOutputStatus.FAILED
            output.error_message = detail
            output.updated_at = utc_now()
            self.storage.save_agent_output(output)
            await self._record_event(
                EventType.AGENT_OUTPUT_RECORDED,
                f"{role.value} 에이전트 실행이 취소되었습니다.",
                candidate=candidate,
                run=run,
                stream_type="fault",
                payload={"role": role.value, "status": "failed", "error": detail},
            )
            raise
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            output.status = AgentOutputStatus.FAILED
            output.error_message = str(exc)[:4_000]
            output.updated_at = utc_now()
            self.storage.save_agent_output(output)
            await self._record_event(
                EventType.AGENT_OUTPUT_RECORDED,
                f"{role.value} 에이전트가 실패했습니다. {str(exc)[:300]}",
                candidate=candidate,
                run=run,
                stream_type="fault",
                payload={"role": role.value, "status": "failed", "error": str(exc)[:500]},
            )
            raise

    @staticmethod
    def _role_input_is_missing(role: AgentRole, snapshot: dict[str, Any]) -> bool:
        required_key = {
            AgentRole.FUNDAMENTAL: "fundamentals",
            AgentRole.NEWS: "news",
        }.get(role)
        if required_key is None:
            return False
        value = snapshot.get(required_key)
        return not isinstance(value, (dict, list)) or not value

    @staticmethod
    def _apply_research_risk_gates(
        risk: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        warnings = [
            str(item)
            for item in risk.get("warnings", [])
            if isinstance(item, str) and item.strip()
        ]
        data_gaps = [
            str(item)
            for item in risk.get("data_gaps", [])
            if isinstance(item, str) and item.strip()
        ]
        blocked = False

        quality = snapshot.get("research_quality")
        if isinstance(quality, dict):
            quality_warnings = quality.get("warnings", [])
            if isinstance(quality_warnings, list):
                warnings.extend(
                    str(item)
                    for item in quality_warnings
                    if isinstance(item, str) and item.strip()
                )
            if quality.get("analysis_eligible") is not True:
                raw_reasons = quality.get("blocking_reasons", [])
                reasons = (
                    [
                        str(item)
                        for item in raw_reasons
                        if isinstance(item, str) and item.strip()
                    ]
                    if isinstance(raw_reasons, list)
                    else []
                )
                if not reasons:
                    reasons = ["필수 연구 자료 품질 기준을 충족하지 못했습니다."]
                data_gaps.extend(reasons)
                warnings.append("연구 자료 품질 게이트가 신규 포지션을 차단했습니다.")
                blocked = True

        regime = snapshot.get("market_regime")
        if isinstance(regime, dict):
            regime_warnings = regime.get("warnings", [])
            if isinstance(regime_warnings, list):
                warnings.extend(
                    str(item)
                    for item in regime_warnings
                    if isinstance(item, str) and item.strip()
                )
            raw_multiplier = regime.get("position_cap_multiplier")
            if (
                isinstance(raw_multiplier, (int, float))
                and not isinstance(raw_multiplier, bool)
                and 0 <= float(raw_multiplier) <= 1
            ):
                multiplier = float(raw_multiplier)
                raw_cap = risk.get("position_cap_pct")
                if (
                    risk.get("eligible") is True
                    and isinstance(raw_cap, (int, float))
                    and not isinstance(raw_cap, bool)
                ):
                    risk["position_cap_pct"] = round(float(raw_cap) * multiplier, 6)
                    if multiplier < 1:
                        warnings.append(
                            f"시장 국면에 따라 포지션 상한을 {multiplier:.2f}배로 축소했습니다."
                        )
                    if risk["position_cap_pct"] <= 0:
                        blocked = True

        if blocked:
            if str(risk.get("action", "")).strip().casefold() == "size_position":
                risk["action"] = "watch"
            risk["eligible"] = False
            risk["position_cap_pct"] = 0.0
        risk["warnings"] = list(dict.fromkeys(warnings))
        risk["data_gaps"] = list(dict.fromkeys(data_gaps))
        return risk

    @staticmethod
    def _data_gap_result(role: AgentRole, ticker: str) -> dict[str, Any]:
        source_name = "재무·공시" if role is AgentRole.FUNDAMENTAL else "뉴스"
        data_gap = f"검증 가능한 {source_name} 원문과 출처가 입력되지 않았습니다."
        return {
            "role": role.value,
            "ticker": ticker,
            "stance": "neutral",
            "confidence": 0.0,
            "summary": f"{data_gap} 이 역할의 방향성 판단을 중립으로 고정합니다.",
            "key_points": ["제공된 가격·거래량 자료만으로 역할 범위를 추정하지 않았습니다."],
            "evidence": [],
            "risks": ["자료 없이 결론을 만들면 투자 판단이 왜곡될 수 있습니다."],
            "recommendation": "검증 가능한 자료가 공급될 때까지 최종 판단에서 제외합니다.",
            "data_gaps": [data_gap],
            "invalidations": [f"검증 가능한 {source_name} 자료가 공급되면 다시 분석합니다."],
        }

    async def _record_event(
        self,
        event_type: EventType,
        message: str,
        *,
        candidate: Candidate,
        run: AnalysisRun,
        stream_type: str,
        payload: dict[str, Any] | None = None,
    ) -> Event:
        event = Event(
            event_type=event_type,
            message=message,
            candidate_id=candidate.id,
            analysis_run_id=run.id,
            payload=JSON_DICT_ADAPTER.validate_python(payload or {}),
        )
        try:
            self.storage.append_event(event)
        except Exception:
            logger.exception(
                "분석 이벤트 저장에 실패했습니다.",
                extra={"analysis_run_id": str(run.id), "event_type": event_type.value},
            )
        stream_payload: dict[str, Any] = {
            "event_id": str(event.id),
            "type": stream_type,
            "event_type": event.event_type.value,
            "message": event.message,
            "candidate_id": str(candidate.id),
            "run_id": str(run.id),
            "created_at": event.created_at.isoformat(),
            **(payload or {}),
        }
        try:
            await self.broker.publish(stream_payload)
        except Exception:
            logger.exception(
                "분석 실시간 이벤트 발행에 실패했습니다.",
                extra={"analysis_run_id": str(run.id), "event_type": event_type.value},
            )
        return event

    def _require_run(self, run_id: UUID) -> AnalysisRun:
        run = self.storage.get_analysis_run(run_id)
        if run is None:
            raise LookupError("분석 실행을 찾을 수 없습니다.")
        return run

    def _require_candidate(self, candidate_id: UUID) -> Candidate:
        candidate = self.storage.get_candidate(candidate_id)
        if candidate is None:
            raise LookupError("투자 후보를 찾을 수 없습니다.")
        return candidate

    @staticmethod
    def _output_payload(output: AgentOutput) -> dict[str, Any]:
        status = {
            AgentOutputStatus.QUEUED: "queued",
            AgentOutputStatus.RUNNING: "running",
            AgentOutputStatus.COMPLETED: "done",
            AgentOutputStatus.FAILED: "failed",
        }[output.status]
        return {
            "id": str(output.id),
            "role": output.role.value,
            "status": status,
            "summary": output.content,
            "confidence": output.confidence,
            "result": output.data,
            "error": output.error_message,
            "updated_at": output.updated_at.isoformat(),
        }

    @staticmethod
    def _build_decision(
        candidate: Candidate,
        chairman: dict[str, Any],
        risk: dict[str, Any],
        *,
        research_quality: object = None,
        market_regime: object = None,
    ) -> dict[str, Any]:
        instrument = InvestmentCommittee._candidate_instrument(candidate)
        stance = str(chairman.get("stance", "neutral"))
        risk_action = str(risk.get("action", "avoid")).strip().casefold()
        raw_position_cap = risk.get("position_cap_pct", 0.0)
        position_cap_pct = (
            float(raw_position_cap)
            if isinstance(raw_position_cap, (int, float)) and not isinstance(raw_position_cap, bool)
            else 0.0
        )
        risk_eligible = (
            risk.get("eligible") is True
            and risk_action == "size_position"
            and position_cap_pct > 0
        )
        recommendation = {
            "bullish": "conditional buy",
            "neutral": "hold and watch",
            "bearish": "avoid",
        }.get(stance, "hold and watch")
        if not risk_eligible:
            recommendation = (
                "avoid" if risk_action == "avoid" or stance == "bearish" else "hold and watch"
            )
        risk_warnings = risk.get("warnings", [])
        risks = [str(item) for item in chairman.get("risks", [])]
        if isinstance(risk_warnings, list):
            risks.extend(
                str(item)
                for item in risk_warnings
                if not str(item).startswith(("의장 위험:", "의장 무효화 조건:"))
            )
        if not risk_eligible:
            risks.insert(0, "위험 정책이 신규 포지션을 허용하지 않습니다.")
        risks = list(dict.fromkeys(risks))
        data_gaps = InvestmentCommittee._merge_data_gaps(chairman, risk)
        return {
            "ticker": instrument.symbol,
            "market": instrument.market.value,
            "canonical_id": instrument.canonical_id,
            "recommendation": recommendation,
            "stance": stance,
            "confidence": chairman.get("confidence"),
            "summary": chairman.get("summary"),
            "key_points": chairman.get("key_points", []),
            "risks": risks,
            "invalidations": chairman.get("invalidations", []),
            "data_gaps": data_gaps,
            "chairman_recommendation": chairman.get("recommendation"),
            "risk_plan": risk,
            "risk_eligible": risk_eligible,
            "position_cap_pct": position_cap_pct,
            "research_quality": research_quality,
            "market_regime": market_regime,
            "human_approval_required": True,
            "auto_trade": False,
        }

    @staticmethod
    def _merge_data_gaps(*payloads: dict[str, Any]) -> list[str]:
        data_gaps: list[str] = []
        for payload in payloads:
            raw_data_gaps = payload.get("data_gaps", [])
            if not isinstance(raw_data_gaps, list):
                continue
            data_gaps.extend(
                item.strip()
                for item in raw_data_gaps
                if isinstance(item, str) and item.strip()
            )
        return list(dict.fromkeys(data_gaps))

    @staticmethod
    def _candidate_instrument(candidate: Candidate) -> InstrumentIdentity:
        return resolve_stored_instrument(candidate.ticker, candidate.attributes)

    @staticmethod
    def _status_message(status: str) -> str:
        return {
            "queued": "분석 대기 중입니다.",
            "running": "에이전트 팀이 분석 중입니다.",
            "review": "위원장 초안이 도착했습니다. 사람이 결정해야 합니다.",
            "approved": "사람이 승인한 분석입니다.",
            "rejected": "사람이 기각한 분석입니다.",
            "hold": "사람이 보류한 분석입니다.",
            "failed": "분석이 실패했습니다.",
        }.get(status, status)
