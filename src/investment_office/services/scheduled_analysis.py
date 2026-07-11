# 일회성 분석 예약을 기존 스냅샷과 이벤트로 영속 관리한다.
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from investment_office.domain import (
    AnalysisRun,
    AnalysisRunStatus,
    Candidate,
    Event,
    EventType,
    Snapshot,
    SnapshotKind,
    utc_now,
)
from investment_office.services.event_broker import EventBroker
from investment_office.storage import Storage

STATE_RECORD_TYPE = "scheduled_analysis"
STATE_SCHEMA_VERSION = 1
SCHEDULE_TIMEZONE: Literal["Asia/Seoul"] = "Asia/Seoul"
KST = timezone(timedelta(hours=9), name="KST")

JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])


class ScheduledAnalysisStatus(StrEnum):
    """일회성 분석 예약의 영속 상태."""

    SCHEDULED = "scheduled"
    CLAIMED = "claimed"
    DISPATCHED = "dispatched"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_STATUSES = frozenset(
    {
        ScheduledAnalysisStatus.SCHEDULED,
        ScheduledAnalysisStatus.CLAIMED,
        ScheduledAnalysisStatus.DISPATCHED,
    }
)


class ScheduledAnalysisError(RuntimeError):
    """예약 서비스의 명시적 오류."""


class ScheduledAnalysisNotFoundError(ScheduledAnalysisError):
    """예약, 분석 실행 또는 후보를 찾지 못했을 때 발생한다."""


class ScheduledAnalysisValidationError(ScheduledAnalysisError):
    """예약 입력값이 유효하지 않을 때 발생한다."""


class ScheduledAnalysisConflictError(ScheduledAnalysisError):
    """같은 분석 실행에 활성 예약이 이미 있을 때 발생한다."""


class ScheduledAnalysisTransitionError(ScheduledAnalysisError):
    """허용되지 않은 예약 상태 전이를 요청했을 때 발생한다."""


class ScheduledAnalysisDataError(ScheduledAnalysisError):
    """서비스 소유 스냅샷이 현재 스키마와 맞지 않을 때 발생한다."""


class ScheduledAnalysis(BaseModel):
    """SnapshotKind.AGENT_STATE에 저장되는 일회성 분석 예약."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    candidate_id: UUID
    ticker: str = Field(min_length=1, max_length=15)
    status: ScheduledAnalysisStatus = ScheduledAnalysisStatus.SCHEDULED
    scheduled_for: AwareDatetime
    timezone: Literal["Asia/Seoul"] = SCHEDULE_TIMEZONE
    sequence: int = Field(ge=1)
    version: int = Field(default=1, ge=1)
    claim_count: int = Field(default=0, ge=0)
    error: str | None = Field(default=None, max_length=4_000)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    claimed_at: AwareDatetime | None = None
    dispatched_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None

    @property
    def analysis_run_id(self) -> UUID:
        """기존 분석 서비스와 명시적으로 연결되는 호환 속성."""

        return self.run_id


class ScheduledAnalysisService:
    """예약 시각이 된 분석을 한 번만 claim할 수 있게 조정한다."""

    def __init__(
        self,
        *,
        storage: Storage,
        broker: EventBroker,
        now_factory: Callable[[], datetime] = utc_now,
    ) -> None:
        self.storage = storage
        self.broker = broker
        self._now_factory = now_factory
        self._lock = asyncio.Lock()
        self._schedule_cache: dict[UUID, ScheduledAnalysis] | None = None

    async def schedule_run(
        self,
        run_id: UUID,
        scheduled_for: datetime,
    ) -> ScheduledAnalysis:
        """대기 중인 분석 실행을 미래의 KST 시각에 한 번 예약한다."""

        normalized_for = self._normalize_scheduled_for(scheduled_for)
        now = self._now()
        if normalized_for <= now:
            raise ScheduledAnalysisValidationError("예약 시각은 현재보다 미래여야 합니다.")

        async with self._lock:
            run = self._require_run(run_id)
            candidate = self._require_candidate(run.candidate_id)
            if run.status is not AnalysisRunStatus.QUEUED:
                raise ScheduledAnalysisValidationError("대기 중인 분석 실행만 예약할 수 있습니다.")
            active = [
                item
                for item in self._latest_schedules()
                if item.analysis_run_id == run.id and item.status in ACTIVE_STATUSES
            ]
            if active:
                raise ScheduledAnalysisConflictError(
                    "이 분석 실행에는 이미 활성 예약이 있습니다."
                )
            item = ScheduledAnalysis(
                run_id=run.id,
                candidate_id=candidate.id,
                ticker=candidate.ticker,
                scheduled_for=normalized_for,
                sequence=self._next_sequence(),
                created_at=now,
                updated_at=now,
            )
            await self._persist(item, "분석 예약이 등록되었습니다.")
            return item

    def list_schedules(
        self,
        *,
        status: ScheduledAnalysisStatus | str | None = None,
        run_id: UUID | None = None,
    ) -> list[ScheduledAnalysis]:
        """최신 예약 상태를 예정 시각과 등록 순서 기준으로 반환한다."""

        resolved_status = self._coerce_status(status) if status is not None else None
        items = [
            item
            for item in self._latest_schedules()
            if (resolved_status is None or item.status is resolved_status)
            and (run_id is None or item.analysis_run_id == run_id)
        ]
        return sorted(items, key=self._fifo_key)

    def get_schedule(self, schedule_id: UUID) -> ScheduledAnalysis:
        """예약 ID에 해당하는 최신 영속 상태를 반환한다."""

        for item in self._latest_schedules():
            if item.id == schedule_id:
                return item
        raise ScheduledAnalysisNotFoundError("분석 예약을 찾을 수 없습니다.")

    async def cancel(self, schedule_id: UUID) -> ScheduledAnalysis:
        """아직 claim되지 않은 예약을 취소한다."""

        async with self._lock:
            current = self.get_schedule(schedule_id)
            if current.status is not ScheduledAnalysisStatus.SCHEDULED:
                raise ScheduledAnalysisTransitionError(
                    "대기 중인 분석 예약만 취소할 수 있습니다."
                )
            cancelled = self._transition(
                current,
                status=ScheduledAnalysisStatus.CANCELLED,
                completed_at=self._now(),
            )
            await self._persist(cancelled, "분석 예약이 취소되었습니다.")
            return cancelled

    async def claim_due(
        self,
        *,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> list[ScheduledAnalysis]:
        """예약 시각이 지난 항목을 FIFO 순서로 원자적으로 claim한다."""

        if limit is not None and limit < 1:
            raise ScheduledAnalysisValidationError("claim limit은 1 이상이어야 합니다.")
        claim_time = self._normalize_now(now) if now is not None else self._now()

        async with self._lock:
            due = [
                item
                for item in self._latest_schedules()
                if item.status is ScheduledAnalysisStatus.SCHEDULED
                and item.scheduled_for <= claim_time
            ]
            due.sort(key=self._fifo_key)
            claimed: list[ScheduledAnalysis] = []
            for item in due:
                if limit is not None and len(claimed) >= limit:
                    break
                reconciled = await self._reconcile_nonqueued_run(item, claim_time)
                if reconciled is not None:
                    continue
                next_item = self._transition(
                    item,
                    status=ScheduledAnalysisStatus.CLAIMED,
                    claim_count=item.claim_count + 1,
                    claimed_at=claim_time,
                    dispatched_at=None,
                    completed_at=None,
                    error=None,
                )
                await self._persist(next_item, "예약 시각이 되어 분석 실행권을 claim했습니다.")
                claimed.append(next_item)
            return claimed

    async def mark_dispatched(self, schedule_id: UUID) -> ScheduledAnalysis:
        """claim된 예약이 실제 실행 콜백에 전달됐음을 기록한다."""

        async with self._lock:
            current = self.get_schedule(schedule_id)
            if current.status is not ScheduledAnalysisStatus.CLAIMED:
                raise ScheduledAnalysisTransitionError(
                    "claim된 분석 예약만 dispatch 상태로 바꿀 수 있습니다."
                )
            dispatched = self._transition(
                current,
                status=ScheduledAnalysisStatus.DISPATCHED,
                dispatched_at=self._now(),
            )
            await self._persist(dispatched, "예약 분석이 실행 콜백에 전달되었습니다.")
            return dispatched

    async def mark_completed(self, schedule_id: UUID) -> ScheduledAnalysis:
        """실제 분석 실행이 완료된 예약을 완료 상태로 확정한다."""

        async with self._lock:
            current = self.get_schedule(schedule_id)
            self._require_dispatching(current)
            run = self._require_run(current.analysis_run_id)
            if run.status is not AnalysisRunStatus.COMPLETED:
                raise ScheduledAnalysisTransitionError(
                    "완료된 분석 실행만 예약 완료로 기록할 수 있습니다."
                )
            completed = self._transition(
                current,
                status=ScheduledAnalysisStatus.COMPLETED,
                completed_at=run.completed_at or self._now(),
                error=None,
            )
            await self._persist(completed, "예약 분석 실행이 완료되었습니다.")
            return completed

    async def mark_failed(
        self,
        schedule_id: UUID,
        error: str,
    ) -> ScheduledAnalysis:
        """실행 콜백 또는 실제 분석의 실패를 예약 상태에 기록한다."""

        normalized_error = error.strip()
        if not normalized_error:
            raise ScheduledAnalysisValidationError("실패 사유는 비어 있을 수 없습니다.")
        async with self._lock:
            current = self.get_schedule(schedule_id)
            self._require_dispatching(current)
            failed = self._transition(
                current,
                status=ScheduledAnalysisStatus.FAILED,
                completed_at=self._now(),
                error=normalized_error[:4_000],
            )
            await self._persist(failed, "예약 분석 실행이 실패했습니다.")
            return failed

    async def mark_dispatch_completed(self, schedule_id: UUID) -> ScheduledAnalysis:
        """main의 dispatch 완료 기록용 명시적 별칭."""

        return await self.mark_completed(schedule_id)

    async def mark_dispatch_failed(
        self,
        schedule_id: UUID,
        error: str,
    ) -> ScheduledAnalysis:
        """main의 dispatch 실패 기록용 명시적 별칭."""

        return await self.mark_failed(schedule_id, error)

    async def recover(self) -> list[ScheduledAnalysis]:
        """재시작 전 claim 및 dispatch 중이던 예약을 저장 상태와 대조한다."""

        async with self._lock:
            recovered: list[ScheduledAnalysis] = []
            now = self._now()
            interrupted = [
                item
                for item in self._latest_schedules()
                if item.status
                in {
                    ScheduledAnalysisStatus.CLAIMED,
                    ScheduledAnalysisStatus.DISPATCHED,
                }
            ]
            interrupted.sort(key=self._fifo_key)
            for item in interrupted:
                run = self._require_run(item.analysis_run_id)
                if run.status is AnalysisRunStatus.COMPLETED:
                    next_item = self._transition(
                        item,
                        status=ScheduledAnalysisStatus.COMPLETED,
                        completed_at=run.completed_at or now,
                        error=None,
                    )
                    message = "재시작 복구 중 완료된 예약 분석을 확인했습니다."
                elif run.status in {
                    AnalysisRunStatus.FAILED,
                    AnalysisRunStatus.CANCELLED,
                    AnalysisRunStatus.RUNNING,
                }:
                    detail = (
                        run.error_message
                        or "서버 재시작으로 실행 연속성을 확인할 수 없습니다."
                    )
                    next_item = self._transition(
                        item,
                        status=ScheduledAnalysisStatus.FAILED,
                        completed_at=run.completed_at or now,
                        error=detail[:4_000],
                    )
                    message = "재시작 복구 중 중단된 예약 분석을 실패로 확정했습니다."
                else:
                    next_item = self._transition(
                        item,
                        status=ScheduledAnalysisStatus.SCHEDULED,
                        claimed_at=None,
                        dispatched_at=None,
                        completed_at=None,
                        error=None,
                    )
                    message = "재시작 복구 후 예약 분석을 다시 대기 상태로 전환했습니다."
                await self._persist(next_item, message)
                recovered.append(next_item)
            return recovered

    async def _reconcile_nonqueued_run(
        self,
        item: ScheduledAnalysis,
        now: datetime,
    ) -> ScheduledAnalysis | None:
        run = self._require_run(item.analysis_run_id)
        if run.status is AnalysisRunStatus.QUEUED:
            return None
        if run.status is AnalysisRunStatus.COMPLETED:
            reconciled = self._transition(
                item,
                status=ScheduledAnalysisStatus.COMPLETED,
                completed_at=run.completed_at or now,
                error=None,
            )
            message = "예약 시각 전에 완료된 분석 실행을 확인했습니다."
        else:
            detail = run.error_message or f"분석 실행 상태가 {run.status.value}입니다."
            reconciled = self._transition(
                item,
                status=ScheduledAnalysisStatus.FAILED,
                completed_at=run.completed_at or now,
                error=detail[:4_000],
            )
            message = "예약 실행 전에 분석 실행 상태 충돌을 확인했습니다."
        await self._persist(reconciled, message)
        return reconciled

    def _latest_schedules(self) -> list[ScheduledAnalysis]:
        if self._schedule_cache is not None:
            return list(self._schedule_cache.values())

        latest: dict[UUID, ScheduledAnalysis] = {}
        for run in self.storage.list_analysis_runs():
            snapshots = self.storage.list_snapshots(run.id, kind=SnapshotKind.AGENT_STATE)
            for snapshot in snapshots:
                if snapshot.data.get("record_type") != STATE_RECORD_TYPE:
                    continue
                if snapshot.data.get("schema_version") != STATE_SCHEMA_VERSION:
                    continue
                payload = snapshot.data.get("schedule")
                if not isinstance(payload, dict):
                    raise ScheduledAnalysisDataError(
                        "분석 예약 스냅샷에 schedule 객체가 없습니다."
                    )
                try:
                    item = ScheduledAnalysis.model_validate(payload)
                except ValueError as exc:
                    raise ScheduledAnalysisDataError(
                        "분석 예약 스냅샷을 읽을 수 없습니다."
                    ) from exc
                existing = latest.get(item.id)
                if existing is None or (item.version, item.updated_at) > (
                    existing.version,
                    existing.updated_at,
                ):
                    latest[item.id] = item
        self._schedule_cache = latest
        return list(latest.values())

    async def _persist(self, item: ScheduledAnalysis, message: str) -> None:
        state = JSON_OBJECT_ADAPTER.validate_python(
            {
                "record_type": STATE_RECORD_TYPE,
                "schema_version": STATE_SCHEMA_VERSION,
                "schedule": item.model_dump(mode="json"),
            }
        )
        self.storage.save_snapshot(
            Snapshot(
                candidate_id=item.candidate_id,
                analysis_run_id=item.analysis_run_id,
                kind=SnapshotKind.AGENT_STATE,
                data=state,
            )
        )
        if self._schedule_cache is None:
            self._latest_schedules()
        if self._schedule_cache is None:
            raise ScheduledAnalysisDataError("분석 예약 캐시를 초기화하지 못했습니다.")
        self._schedule_cache[item.id] = item
        event_payload = JSON_OBJECT_ADAPTER.validate_python(
            {
                "schedule_id": str(item.id),
                "ticker": item.ticker,
                "status": item.status.value,
                "scheduled_for": item.scheduled_for.isoformat(),
                "timezone": item.timezone,
                "sequence": item.sequence,
                "version": item.version,
                "claim_count": item.claim_count,
                "error": item.error,
            }
        )
        event = Event(
            event_type=EventType.STATUS_CHANGED,
            message=message,
            candidate_id=item.candidate_id,
            analysis_run_id=item.analysis_run_id,
            payload=event_payload,
        )
        self.storage.append_event(event)
        await self.broker.publish(
            {
                "event_id": str(event.id),
                "type": STATE_RECORD_TYPE,
                "event_type": event.event_type.value,
                "message": event.message,
                "candidate_id": str(item.candidate_id),
                "run_id": str(item.analysis_run_id),
                "created_at": event.created_at.isoformat(),
                **event_payload,
            }
        )

    def _transition(self, item: ScheduledAnalysis, **updates: Any) -> ScheduledAnalysis:
        payload = item.model_dump(mode="python")
        payload.update(updates)
        payload["version"] = item.version + 1
        payload["updated_at"] = self._now()
        return ScheduledAnalysis.model_validate(payload)

    def _next_sequence(self) -> int:
        return max((item.sequence for item in self._latest_schedules()), default=0) + 1

    def _now(self) -> datetime:
        return self._normalize_now(self._now_factory())

    @staticmethod
    def _normalize_now(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ScheduledAnalysisValidationError("현재 시각은 timezone-aware 값이어야 합니다.")
        return value

    @staticmethod
    def _normalize_scheduled_for(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ScheduledAnalysisValidationError("예약 시각은 timezone-aware 값이어야 합니다.")
        return value.astimezone(KST)

    @staticmethod
    def _fifo_key(item: ScheduledAnalysis) -> tuple[datetime, int, datetime, str]:
        return (item.scheduled_for, item.sequence, item.created_at, str(item.id))

    def _require_run(self, run_id: UUID) -> AnalysisRun:
        run = self.storage.get_analysis_run(run_id)
        if run is None:
            raise ScheduledAnalysisNotFoundError("분석 실행을 찾을 수 없습니다.")
        return run

    def _require_candidate(self, candidate_id: UUID) -> Candidate:
        candidate = self.storage.get_candidate(candidate_id)
        if candidate is None:
            raise ScheduledAnalysisNotFoundError("투자 후보를 찾을 수 없습니다.")
        return candidate

    @staticmethod
    def _require_dispatching(item: ScheduledAnalysis) -> None:
        if item.status not in {
            ScheduledAnalysisStatus.CLAIMED,
            ScheduledAnalysisStatus.DISPATCHED,
        }:
            raise ScheduledAnalysisTransitionError(
                "claim 또는 dispatch 중인 예약만 실행 결과를 기록할 수 있습니다."
            )

    @staticmethod
    def _coerce_status(
        status: ScheduledAnalysisStatus | str,
    ) -> ScheduledAnalysisStatus:
        try:
            return (
                status
                if isinstance(status, ScheduledAnalysisStatus)
                else ScheduledAnalysisStatus(status)
            )
        except ValueError as exc:
            raise ScheduledAnalysisValidationError(
                f"지원하지 않는 예약 상태입니다. {status}"
            ) from exc


ScheduleStatus = ScheduledAnalysisStatus
ScheduledAnalysisItem = ScheduledAnalysis
