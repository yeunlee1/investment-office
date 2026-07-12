# 과거 분석 실행의 의사결정 카드와 사람 승인 상태를 읽기 전용으로 조합한다.
from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from investment_office.domain import (
    AnalysisRun,
    AnalysisRunStatus,
    Candidate,
    CandidateStatus,
    HumanReview,
    ReviewDecision,
    Snapshot,
    SnapshotKind,
)
from investment_office.services.candidate_discovery import find_universe_company_name
from investment_office.services.instrument_identity import resolve_stored_instrument
from investment_office.storage import Storage

SCHEDULE_RECORD_TYPE = "scheduled_analysis"


class ScheduledAnalysisSummary(BaseModel):
    """예약 분석 스냅샷에서 의사결정 카드에 필요한 메타데이터."""

    model_config = ConfigDict(extra="allow", frozen=True)

    id: UUID
    run_id: UUID = Field(validation_alias=AliasChoices("run_id", "analysis_run_id"))
    candidate_id: UUID
    status: str = Field(min_length=1, max_length=32)
    scheduled_for: AwareDatetime
    timezone: str = Field(default="Asia/Seoul", min_length=1, max_length=64)
    sequence: int = Field(ge=1)
    version: int = Field(ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    claimed_at: AwareDatetime | None = None
    dispatched_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    error: str | None = Field(default=None, max_length=4_000)


class DecisionArchiveEntry(BaseModel):
    """한 분석 실행과 연결된 과거 의사결정 카드."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    candidate_id: UUID
    ticker: str
    company_name: str | None
    thesis: str | None
    candidate_status: CandidateStatus
    run_status: AnalysisRunStatus
    effective_status: str
    as_of_date: date
    requested_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    updated_at: AwareDatetime
    error: str | None
    decision: dict[str, JsonValue] | None
    decision_snapshot_id: UUID | None
    decision_captured_at: AwareDatetime | None
    scheduled_analysis: ScheduledAnalysisSummary | None
    latest_human_review: HumanReview | None
    human_review_count: int = Field(ge=0)
    human_approval_required: Literal[True] = True
    human_approved: bool
    auto_trade: Literal[False] = False


class DecisionArchiveNotFoundError(LookupError):
    """요청한 분석 실행 또는 연결 후보가 없을 때 발생한다."""


class DecisionArchiveService:
    """저장된 실행을 변경하지 않고 의사결정 카드 목록과 상세를 제공한다."""

    def __init__(self, *, storage: Storage) -> None:
        self.storage = storage

    def list_entries(
        self,
        *,
        ticker: str | None = None,
        limit: int | None = None,
    ) -> list[DecisionArchiveEntry]:
        """최신 실행부터 카드로 조합하고 선택적으로 종목과 개수를 제한한다."""

        if limit is not None and limit < 1:
            raise ValueError("limit은 1 이상이어야 합니다.")
        normalized_ticker = ticker.strip().upper() if ticker is not None else None
        if normalized_ticker == "":
            raise ValueError("ticker는 공백일 수 없습니다.")

        entries: list[DecisionArchiveEntry] = []
        for run in self.storage.list_analysis_runs():
            candidate = self.storage.get_candidate(run.candidate_id)
            if candidate is None:
                raise DecisionArchiveNotFoundError(
                    f"분석 실행 {run.id}의 후보 종목을 찾을 수 없습니다."
                )
            if normalized_ticker is not None and candidate.ticker != normalized_ticker:
                continue
            entries.append(self._build_entry(run, candidate))
            if limit is not None and len(entries) >= limit:
                break
        return entries

    def get_entry(self, run_id: UUID) -> DecisionArchiveEntry:
        """실행 식별자로 카드 한 건을 조회한다."""

        run = self.storage.get_analysis_run(run_id)
        if run is None:
            raise DecisionArchiveNotFoundError(f"분석 실행 {run_id}을 찾을 수 없습니다.")
        candidate = self.storage.get_candidate(run.candidate_id)
        if candidate is None:
            raise DecisionArchiveNotFoundError(
                f"분석 실행 {run.id}의 후보 종목을 찾을 수 없습니다."
            )
        return self._build_entry(run, candidate)

    def _build_entry(self, run: AnalysisRun, candidate: Candidate) -> DecisionArchiveEntry:
        decision_snapshots = self.storage.list_snapshots(run.id, kind=SnapshotKind.DECISION)
        decision_snapshot = decision_snapshots[0] if decision_snapshots else None
        reviews = self.storage.list_human_reviews(run.id)
        latest_review = reviews[0] if reviews else None
        scheduled_analysis = self._latest_schedule(run.id)
        instrument = resolve_stored_instrument(candidate.ticker, candidate.attributes)
        company_name = candidate.company_name or find_universe_company_name(
            instrument.market,
            instrument.symbol,
        )
        return DecisionArchiveEntry(
            run_id=run.id,
            candidate_id=candidate.id,
            ticker=candidate.ticker,
            company_name=company_name,
            thesis=candidate.thesis,
            candidate_status=candidate.status,
            run_status=run.status,
            effective_status=self._effective_status(run, scheduled_analysis),
            as_of_date=run.as_of_date,
            requested_at=run.requested_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            updated_at=run.updated_at,
            error=run.error_message or (scheduled_analysis.error if scheduled_analysis else None),
            decision=decision_snapshot.data if decision_snapshot is not None else None,
            decision_snapshot_id=decision_snapshot.id if decision_snapshot is not None else None,
            decision_captured_at=(
                decision_snapshot.captured_at if decision_snapshot is not None else None
            ),
            scheduled_analysis=scheduled_analysis,
            latest_human_review=latest_review,
            human_review_count=len(reviews),
            human_approved=(
                latest_review is not None
                and latest_review.decision == ReviewDecision.APPROVED
            ),
        )

    def _latest_schedule(self, run_id: UUID) -> ScheduledAnalysisSummary | None:
        snapshots = self.storage.list_snapshots(run_id, kind=SnapshotKind.AGENT_STATE)
        latest_by_id: dict[UUID, ScheduledAnalysisSummary] = {}
        for snapshot in snapshots:
            schedule = self._parse_schedule(snapshot)
            if schedule is None:
                continue
            current = latest_by_id.get(schedule.id)
            if current is None or schedule.version > current.version:
                latest_by_id[schedule.id] = schedule
        if not latest_by_id:
            return None
        return max(
            latest_by_id.values(),
            key=lambda item: (item.updated_at, item.version),
        )

    @staticmethod
    def _parse_schedule(snapshot: Snapshot) -> ScheduledAnalysisSummary | None:
        if snapshot.data.get("record_type") != SCHEDULE_RECORD_TYPE:
            return None
        payload = snapshot.data.get("schedule")
        if not isinstance(payload, dict):
            return None
        return ScheduledAnalysisSummary.model_validate(payload)

    @staticmethod
    def _effective_status(
        run: AnalysisRun,
        scheduled_analysis: ScheduledAnalysisSummary | None,
    ) -> str:
        if run.status == AnalysisRunStatus.QUEUED and scheduled_analysis is not None:
            return scheduled_analysis.status
        return run.status.value
