# NPC 수동 업무 항목을 스냅샷으로 저장하고 순차 실행하는 서비스다.
from __future__ import annotations

import asyncio
import logging
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from investment_office.domain import (
    AgentRole,
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
from investment_office.services.instrument_identity import resolve_stored_instrument
from investment_office.services.orchestrator import (
    AnalysisProvider,
    attach_chart_analysis,
    build_technical_data_gap_result,
    technical_input_is_missing,
)
from investment_office.storage import Storage

STATE_RECORD_TYPE = "manual_work_item"
STATE_SCHEMA_VERSION = 1
RESUME_SEMANTICS = (
    "실패하거나 취소된 업무를 이전에 저장된 결과 문맥으로 새로 실행하는 시도입니다. "
    "중단된 프로세스나 대화 세션을 이어서 실행하지 않습니다."
)

JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])
JSON_CONTEXT_ADAPTER = TypeAdapter(list[dict[str, JsonValue]])
logger = logging.getLogger(__name__)


class WorkItemStatus(StrEnum):
    """수동 업무 항목의 영속 상태."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkItemError(RuntimeError):
    """수동 업무 서비스의 명시적 오류."""


class WorkItemNotFoundError(WorkItemError):
    """요청한 업무 항목이나 분석 실행이 없을 때 발생한다."""


class WorkItemTransitionError(WorkItemError):
    """허용되지 않은 상태 전이를 요청했을 때 발생한다."""


class WorkItemDataError(WorkItemError):
    """서비스 소유 스냅샷이 현재 스키마와 맞지 않을 때 발생한다."""


class WorkItem(BaseModel):
    """SnapshotKind.AGENT_STATE에 저장되는 수동 업무 항목."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    analysis_run_id: UUID
    candidate_id: UUID
    role: AgentRole
    title: str = Field(min_length=1, max_length=200)
    instructions: str = Field(min_length=1, max_length=20_000)
    status: WorkItemStatus = WorkItemStatus.QUEUED
    attempt: int = Field(default=1, ge=1)
    version: int = Field(default=1, ge=1)
    queue_sequence: int = Field(default=1, ge=1)
    context: list[dict[str, JsonValue]] = Field(default_factory=list)
    resume_context: dict[str, JsonValue] | None = None
    progress: dict[str, JsonValue] | None = None
    result: dict[str, JsonValue] | None = None
    error: str | None = Field(default=None, max_length=4_000)
    created_at: AwareDatetime = Field(default_factory=utc_now)
    queued_at: AwareDatetime = Field(default_factory=utc_now)
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    updated_at: AwareDatetime = Field(default_factory=utc_now)

    @field_validator("title", "instructions")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("값은 공백일 수 없습니다.")
        return normalized


class WorkItemReport(BaseModel):
    """추가 LLM 호출 없이 저장된 상태만 노출하는 업무 보고."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    work_item_id: UUID
    analysis_run_id: UUID
    role: AgentRole
    status: WorkItemStatus
    attempt: int
    progress: dict[str, JsonValue] | None
    result: dict[str, JsonValue] | None
    error: str | None
    updated_at: AwareDatetime
    completed_at: AwareDatetime | None
    source: str = "stored_state"
    resume_semantics: str | None = None


class WorkItemService:
    """수동 업무를 역할별로 한 번에 하나만 실행하고 상태를 스냅샷으로 남긴다."""

    def __init__(
        self,
        *,
        storage: Storage,
        provider: AnalysisProvider,
        broker: EventBroker,
    ) -> None:
        self.storage = storage
        self.provider = provider
        self.broker = broker
        self._locks: dict[tuple[UUID, AgentRole], asyncio.Lock] = {}

    async def create_work_item(
        self,
        *,
        run_id: UUID,
        role: AgentRole | str,
        title: str,
        instructions: str,
        context: list[dict[str, Any]] | None = None,
    ) -> WorkItem:
        """새 업무를 대기열에 추가한다."""

        run = self._require_run(run_id)
        self._require_candidate(run.candidate_id)
        resolved_role = self._coerce_role(role)
        normalized_context = JSON_CONTEXT_ADAPTER.validate_python(context or [])
        async with self._lock_for(run.id, resolved_role):
            queue_sequence = self._next_queue_sequence(run.id, resolved_role)
            now = utc_now()
            item = WorkItem(
                analysis_run_id=run.id,
                candidate_id=run.candidate_id,
                role=resolved_role,
                title=title,
                instructions=instructions,
                context=normalized_context,
                queue_sequence=queue_sequence,
                created_at=now,
                queued_at=now,
                updated_at=now,
            )
            await self._persist(item, "수동 업무가 대기열에 등록되었습니다.")
        return item

    def list_work_items(
        self,
        run_id: UUID,
        *,
        role: AgentRole | str | None = None,
    ) -> list[WorkItem]:
        """한 분석 실행의 최신 업무 상태를 대기열 순서로 반환한다."""

        self._require_run(run_id)
        resolved_role = self._coerce_role(role) if role is not None else None
        items = [
            item
            for item in self._latest_items(run_id)
            if resolved_role is None or item.role is resolved_role
        ]
        return sorted(
            items,
            key=lambda item: (item.queue_sequence, item.queued_at, str(item.id)),
        )

    def get_work_item(self, run_id: UUID, work_item_id: UUID) -> WorkItem:
        """업무 항목의 최신 저장 상태를 반환한다."""

        self._require_run(run_id)
        for item in self._latest_items(run_id):
            if item.id == work_item_id:
                return item
        raise WorkItemNotFoundError("수동 업무 항목을 찾을 수 없습니다.")

    def find_work_item(self, work_item_id: UUID) -> WorkItem | None:
        """모든 분석 실행에서 업무 ID에 해당하는 최신 저장 상태를 찾는다."""

        for run in self.storage.list_analysis_runs():
            for item in self._latest_items(run.id):
                if item.id == work_item_id:
                    return item
        return None

    async def run_next(
        self,
        run_id: UUID,
        role: AgentRole | str,
    ) -> WorkItem | None:
        """역할의 다음 대기 업무 하나를 실행한다.

        같은 분석 실행과 역할에 이미 실행 중인 업무가 있으면 아무것도 시작하지 않고
        ``None``을 반환한다. 완료 뒤 다시 호출하면 다음 대기 업무를 실행할 수 있다.
        """

        run = self._require_run(run_id)
        candidate = self._require_candidate(run.candidate_id)
        resolved_role = self._coerce_role(role)
        lock = self._lock_for(run.id, resolved_role)

        async with lock:
            role_items = self.list_work_items(run.id, role=resolved_role)
            if any(item.status is WorkItemStatus.RUNNING for item in role_items):
                return None
            queued = [item for item in role_items if item.status is WorkItemStatus.QUEUED]
            if not queued:
                return None
            item = queued[0]
            market_snapshots = self.storage.list_snapshots(
                run.id,
                kind=SnapshotKind.MARKET_DATA,
            )
            if not market_snapshots:
                if run.status not in {
                    AnalysisRunStatus.QUEUED,
                    AnalysisRunStatus.RUNNING,
                }:
                    failed = self._transition(
                        item,
                        status=WorkItemStatus.FAILED,
                        error="종료된 분석에 시장 데이터 스냅샷이 없어 업무를 실행할 수 없습니다.",
                        completed_at=utc_now(),
                    )
                    await self._persist(
                        failed,
                        "시장 데이터가 없는 종료 분석의 수동 업무를 실패로 확정했습니다.",
                    )
                    return failed
                raise WorkItemTransitionError(
                    "수동 업무 실행에 필요한 시장 데이터 스냅샷이 없습니다."
                )
            running = self._transition(
                item,
                status=WorkItemStatus.RUNNING,
                started_at=utc_now(),
                completed_at=None,
                error=None,
            )
            await self._persist(running, "수동 업무 실행이 시작되었습니다.")

        provider_snapshot = JSON_OBJECT_ADAPTER.validate_python(market_snapshots[0].data)
        provider_context = list(running.context)
        provider_context.append(
            JSON_OBJECT_ADAPTER.validate_python(
                {
                    "manual_work_request": {
                        "id": str(running.id),
                        "title": running.title,
                        "instructions": running.instructions,
                        "attempt": running.attempt,
                        "resume_semantics": (
                            RESUME_SEMANTICS if running.resume_context is not None else None
                        ),
                    }
                }
            )
        )
        if running.resume_context is not None:
            provider_context.append(
                JSON_OBJECT_ADAPTER.validate_python(
                    {
                        "manual_work_item_resume": running.resume_context,
                    }
                )
            )

        try:
            provider_ticker = resolve_stored_instrument(
                candidate.ticker,
                candidate.attributes,
            ).symbol
            if (
                resolved_role is AgentRole.TECHNICAL
                and technical_input_is_missing(provider_snapshot)
            ):
                raw_result = build_technical_data_gap_result(provider_ticker)
            else:
                raw_result = await self.provider.analyze(
                    resolved_role.value,
                    provider_ticker,
                    provider_snapshot,
                    provider_context,
                )
            result = JSON_OBJECT_ADAPTER.validate_python(
                attach_chart_analysis(resolved_role, provider_snapshot, raw_result)
            )
        except asyncio.CancelledError:
            await self._finish_cancelled_execution(run.id, running.id, resolved_role)
            raise
        except Exception as exc:
            async with lock:
                current = self.get_work_item(run.id, running.id)
                if current.status is not WorkItemStatus.RUNNING:
                    raise WorkItemTransitionError(
                        "실행 중이 아닌 업무를 실패 상태로 바꿀 수 없습니다."
                    ) from exc
                failed = self._transition(
                    current,
                    status=WorkItemStatus.FAILED,
                    error=str(exc)[:4_000],
                    completed_at=utc_now(),
                )
                await self._persist(failed, "수동 업무 실행이 실패했습니다.")
                return failed

        async with lock:
            current = self.get_work_item(run.id, running.id)
            if current.status is not WorkItemStatus.RUNNING:
                raise WorkItemTransitionError("실행 중이 아닌 업무를 완료 상태로 바꿀 수 없습니다.")
            completed = self._transition(
                current,
                status=WorkItemStatus.COMPLETED,
                result=result,
                error=None,
                completed_at=utc_now(),
            )
            await self._persist(completed, "수동 업무 실행이 완료되었습니다.")
            return completed

    async def record_progress(
        self,
        run_id: UUID,
        work_item_id: UUID,
        progress: dict[str, Any],
    ) -> WorkItem:
        """실행기에서 실제로 관찰한 진행 데이터만 저장한다."""

        item = self.get_work_item(run_id, work_item_id)
        lock = self._lock_for(item.analysis_run_id, item.role)
        normalized = JSON_OBJECT_ADAPTER.validate_python(progress)
        async with lock:
            current = self.get_work_item(run_id, work_item_id)
            if current.status is not WorkItemStatus.RUNNING:
                raise WorkItemTransitionError("실행 중인 업무에만 진행 상태를 기록할 수 있습니다.")
            updated = self._transition(current, progress=normalized)
            await self._persist(updated, "저장된 실제 진행 상태가 갱신되었습니다.")
            return updated

    async def cancel_work_item(self, run_id: UUID, work_item_id: UUID) -> WorkItem:
        """아직 시작하지 않은 업무를 취소한다."""

        item = self.get_work_item(run_id, work_item_id)
        lock = self._lock_for(item.analysis_run_id, item.role)
        async with lock:
            current = self.get_work_item(run_id, work_item_id)
            if current.status is not WorkItemStatus.QUEUED:
                raise WorkItemTransitionError(
                    "현재 실행기를 안전하게 중단할 수 없으므로 대기 업무만 취소할 수 있습니다."
                )
            cancelled = self._transition(
                current,
                status=WorkItemStatus.CANCELLED,
                completed_at=utc_now(),
            )
            await self._persist(cancelled, "수동 업무가 취소되었습니다.")
            return cancelled

    async def resume_work_item(self, run_id: UUID, work_item_id: UUID) -> WorkItem:
        """실패하거나 취소된 업무를 이전 저장 결과 문맥으로 새 시도에 넣는다."""

        item = self.get_work_item(run_id, work_item_id)
        lock = self._lock_for(item.analysis_run_id, item.role)
        async with lock:
            current = self.get_work_item(run_id, work_item_id)
            if current.status not in {WorkItemStatus.FAILED, WorkItemStatus.CANCELLED}:
                raise WorkItemTransitionError(
                    "실패하거나 취소된 업무만 새 시도로 재개할 수 있습니다."
                )
            resume_context = JSON_OBJECT_ADAPTER.validate_python(
                {
                    "semantics": RESUME_SEMANTICS,
                    "previous_attempt": current.attempt,
                    "previous_status": current.status.value,
                    "previous_progress": current.progress,
                    "previous_result": current.result,
                    "previous_error": current.error,
                }
            )
            now = utc_now()
            resumed = self._transition(
                current,
                status=WorkItemStatus.QUEUED,
                attempt=current.attempt + 1,
                queue_sequence=self._next_queue_sequence(current.analysis_run_id, current.role),
                queued_at=now,
                started_at=None,
                completed_at=None,
                progress=None,
                result=None,
                error=None,
                resume_context=resume_context,
            )
            await self._persist(
                resumed,
                "이전 저장 결과 문맥을 사용하는 새 업무 시도가 대기열에 등록되었습니다.",
            )
            return resumed

    def request_report(self, run_id: UUID, work_item_id: UUID) -> WorkItemReport:
        """Provider를 호출하지 않고 최신 저장 상태와 결과만 반환한다."""

        item = self.get_work_item(run_id, work_item_id)
        return WorkItemReport(
            work_item_id=item.id,
            analysis_run_id=item.analysis_run_id,
            role=item.role,
            status=item.status,
            attempt=item.attempt,
            progress=item.progress,
            result=item.result,
            error=item.error,
            updated_at=item.updated_at,
            completed_at=item.completed_at,
            resume_semantics=(RESUME_SEMANTICS if item.attempt > 1 else None),
        )

    async def recover(self) -> list[WorkItem]:
        """재시작으로 끊긴 실행을 실패 처리하고 실행 가능한 대기 업무를 반환한다."""

        queued: list[WorkItem] = []
        for run in self.storage.list_analysis_runs():
            for item in self._latest_items(run.id):
                if item.status not in {WorkItemStatus.RUNNING, WorkItemStatus.QUEUED}:
                    continue
                lock = self._lock_for(run.id, item.role)
                async with lock:
                    current = self.get_work_item(run.id, item.id)
                    if current.status is WorkItemStatus.RUNNING:
                        failed = self._transition(
                            current,
                            status=WorkItemStatus.FAILED,
                            error=(
                                "서버 재시작으로 실행 중이던 수동 업무가 중단되었습니다. "
                                "저장된 상태를 확인한 뒤 재개하세요."
                            ),
                            completed_at=utc_now(),
                        )
                        await self._persist(
                            failed,
                            "재시작 복구 중 실행 중이던 수동 업무를 실패로 확정했습니다.",
                        )
                        continue
                    market_snapshots = self.storage.list_snapshots(
                        run.id,
                        kind=SnapshotKind.MARKET_DATA,
                    )
                    if not market_snapshots and run.status not in {
                        AnalysisRunStatus.QUEUED,
                        AnalysisRunStatus.RUNNING,
                    }:
                        failed = self._transition(
                            current,
                            status=WorkItemStatus.FAILED,
                            error=(
                                "종료된 분석에 시장 데이터 스냅샷이 없어 "
                                "대기 업무를 복구할 수 없습니다."
                            ),
                            completed_at=utc_now(),
                        )
                        await self._persist(
                            failed,
                            "재시작 복구 중 실행 불가능한 대기 업무를 실패로 확정했습니다.",
                        )
                        continue
                    queued.append(current)
        return queued

    async def _finish_cancelled_execution(
        self,
        run_id: UUID,
        work_item_id: UUID,
        role: AgentRole,
    ) -> None:
        lock = self._lock_for(run_id, role)
        async with lock:
            current = self.get_work_item(run_id, work_item_id)
            if current.status is not WorkItemStatus.RUNNING:
                return
            cancelled = self._transition(
                current,
                status=WorkItemStatus.CANCELLED,
                error="실행 태스크가 취소되었습니다.",
                completed_at=utc_now(),
            )
            await self._persist(cancelled, "수동 업무 실행 태스크가 취소되었습니다.")

    def _latest_items(self, run_id: UUID) -> list[WorkItem]:
        latest: dict[UUID, WorkItem] = {}
        snapshots = self.storage.list_snapshots(run_id, kind=SnapshotKind.AGENT_STATE)
        for snapshot in snapshots:
            if snapshot.data.get("record_type") != STATE_RECORD_TYPE:
                continue
            if snapshot.data.get("schema_version") != STATE_SCHEMA_VERSION:
                continue
            payload = snapshot.data.get("work_item")
            if not isinstance(payload, dict):
                raise WorkItemDataError("수동 업무 스냅샷에 work_item 객체가 없습니다.")
            try:
                item = WorkItem.model_validate(payload)
            except ValidationError as exc:
                raise WorkItemDataError("수동 업무 스냅샷을 읽을 수 없습니다.") from exc
            existing = latest.get(item.id)
            if existing is None or item.version > existing.version:
                latest[item.id] = item
        return list(latest.values())

    async def _persist(self, item: WorkItem, message: str) -> None:
        state = JSON_OBJECT_ADAPTER.validate_python(
            {
                "record_type": STATE_RECORD_TYPE,
                "schema_version": STATE_SCHEMA_VERSION,
                "work_item": item.model_dump(mode="json"),
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
        event_payload = JSON_OBJECT_ADAPTER.validate_python(
            {
                "work_item_id": str(item.id),
                "role": item.role.value,
                "status": item.status.value,
                "attempt": item.attempt,
                "version": item.version,
            }
        )
        event = Event(
            event_type=EventType.STATUS_CHANGED,
            message=message,
            candidate_id=item.candidate_id,
            analysis_run_id=item.analysis_run_id,
            payload=event_payload,
        )
        try:
            self.storage.append_event(event)
        except Exception:
            logger.exception(
                "수동 업무 이벤트 저장에 실패했습니다.",
                extra={"analysis_run_id": str(item.analysis_run_id)},
            )
        try:
            await self.broker.publish(
                {
                    "event_id": str(event.id),
                    "type": "work_item",
                    "event_type": event.event_type.value,
                    "message": event.message,
                    "candidate_id": str(item.candidate_id),
                    "run_id": str(item.analysis_run_id),
                    "created_at": event.created_at.isoformat(),
                    **event_payload,
                }
            )
        except Exception:
            logger.exception(
                "수동 업무 실시간 이벤트 발행에 실패했습니다.",
                extra={"analysis_run_id": str(item.analysis_run_id)},
            )

    @staticmethod
    def _transition(item: WorkItem, **updates: Any) -> WorkItem:
        payload = item.model_dump(mode="python")
        payload.update(updates)
        payload["version"] = item.version + 1
        payload["updated_at"] = utc_now()
        return WorkItem.model_validate(payload)

    def _lock_for(self, run_id: UUID, role: AgentRole) -> asyncio.Lock:
        key = (run_id, role)
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def _next_queue_sequence(self, run_id: UUID, role: AgentRole) -> int:
        existing = self.list_work_items(run_id, role=role)
        return max((item.queue_sequence for item in existing), default=0) + 1

    def _require_run(self, run_id: UUID) -> AnalysisRun:
        run = self.storage.get_analysis_run(run_id)
        if run is None:
            raise WorkItemNotFoundError("분석 실행을 찾을 수 없습니다.")
        return run

    def _require_candidate(self, candidate_id: UUID) -> Candidate:
        candidate = self.storage.get_candidate(candidate_id)
        if candidate is None:
            raise WorkItemNotFoundError("투자 후보를 찾을 수 없습니다.")
        return candidate

    @staticmethod
    def _coerce_role(role: AgentRole | str) -> AgentRole:
        try:
            return role if isinstance(role, AgentRole) else AgentRole(role)
        except ValueError as exc:
            raise WorkItemTransitionError(f"지원하지 않는 에이전트 역할입니다. {role}") from exc
