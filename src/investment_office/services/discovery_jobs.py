# 전체시장 종목 발굴 작업의 비동기 진행 상태와 결과를 메모리에서 관리한다.
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator


def utc_now() -> datetime:
    """현재 UTC 시각을 반환한다."""

    return datetime.now(UTC)


class DiscoveryJobStatus(StrEnum):
    """종목 발굴 작업의 실행 상태다."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class DiscoveryStage(StrEnum):
    """전체시장 종목 발굴의 고정 처리 단계다."""

    UNIVERSE = "universe"
    FUNDAMENTALS = "fundamentals"
    LIQUIDITY = "liquidity"
    SECTOR = "sector"
    RANKING = "ranking"


DISCOVERY_STAGE_ORDER: tuple[DiscoveryStage, ...] = (
    DiscoveryStage.UNIVERSE,
    DiscoveryStage.FUNDAMENTALS,
    DiscoveryStage.LIQUIDITY,
    DiscoveryStage.SECTOR,
    DiscoveryStage.RANKING,
)


class DiscoveryStageProgress(BaseModel):
    """한 발굴 단계의 누적 처리 수와 시각 정보다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: DiscoveryStage
    total: int = Field(default=0, ge=0)
    processed: int = Field(default=0, ge=0)
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    cached: int = Field(default=0, ge=0)
    message: str | None = Field(default=None, max_length=1_000)
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_counts_and_timestamps(self) -> DiscoveryStageProgress:
        if self.processed > self.total:
            raise ValueError("처리 수는 전체 수를 초과할 수 없습니다.")
        if self.passed + self.failed > self.processed:
            raise ValueError("통과 수와 실패 수의 합은 처리 수를 초과할 수 없습니다.")
        if self.cached > self.processed:
            raise ValueError("캐시 사용 수는 처리 수를 초과할 수 없습니다.")
        if self.completed_at is not None and self.started_at is None:
            raise ValueError("단계 완료 시각에는 시작 시각이 필요합니다.")
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("단계 완료 시각은 시작 시각보다 빠를 수 없습니다.")
        return self


class DiscoveryProgressUpdate(BaseModel):
    """실행기가 원장에 전달하는 한 단계의 부분 갱신이다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: DiscoveryStage
    total: int | None = Field(default=None, ge=0)
    processed: int | None = Field(default=None, ge=0)
    passed: int | None = Field(default=None, ge=0)
    failed: int | None = Field(default=None, ge=0)
    cached: int | None = Field(default=None, ge=0)
    message: str | None = Field(default=None, max_length=1_000)
    completed: bool = False


class DiscoveryJobOutcome(BaseModel):
    """실행기가 반환하는 완료 또는 부분 완료 결과다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: DiscoveryJobStatus = DiscoveryJobStatus.COMPLETE
    result: JsonValue
    message: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_terminal_status(self) -> DiscoveryJobOutcome:
        if self.status not in {
            DiscoveryJobStatus.COMPLETE,
            DiscoveryJobStatus.PARTIAL,
        }:
            raise ValueError("실행 결과 상태는 complete 또는 partial이어야 합니다.")
        return self


class DiscoveryJob(BaseModel):
    """API에 직렬화할 수 있는 종목 발굴 작업 스냅샷이다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    status: DiscoveryJobStatus
    current_stage: DiscoveryStage | None = None
    stages: tuple[DiscoveryStageProgress, ...]
    result: JsonValue | None = None
    message: str | None = Field(default=None, max_length=1_000)
    error: str | None = Field(default=None, max_length=2_000)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_stage_order_and_timestamps(self) -> DiscoveryJob:
        if tuple(item.stage for item in self.stages) != DISCOVERY_STAGE_ORDER:
            raise ValueError("발굴 작업 단계가 고정 순서와 일치하지 않습니다.")
        if self.updated_at < self.created_at:
            raise ValueError("작업 갱신 시각은 생성 시각보다 빠를 수 없습니다.")
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("작업 시작 시각은 생성 시각보다 빠를 수 없습니다.")
        if self.completed_at is not None and self.started_at is None:
            raise ValueError("작업 완료 시각에는 시작 시각이 필요합니다.")
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("작업 완료 시각은 시작 시각보다 빠를 수 없습니다.")
        return self


type DiscoveryProgressCallback = Callable[[DiscoveryProgressUpdate], Awaitable[None]]
type DiscoveryRunnerResult = DiscoveryJobOutcome | JsonValue
type DiscoveryRunner = Callable[
    [DiscoveryProgressCallback], Awaitable[DiscoveryRunnerResult]
]


class DiscoveryJobNotFoundError(KeyError):
    """요청한 종목 발굴 작업이 메모리 원장에 없을 때 발생한다."""


class DiscoveryJobService:
    """비동기 실행기를 예약하고 불변 작업 스냅샷을 보관한다."""

    def __init__(self, now_factory: Callable[[], datetime] | None = None) -> None:
        self._now_factory = now_factory or utc_now
        self._jobs: dict[UUID, DiscoveryJob] = {}
        self._tasks: dict[UUID, asyncio.Task[None]] = {}

    def create(self, runner: DiscoveryRunner) -> UUID:
        """실행기를 백그라운드에 예약하고 대기 상태 작업 ID를 즉시 반환한다."""

        job_id = uuid4()
        created_at = self._now()
        self._jobs[job_id] = DiscoveryJob(
            id=job_id,
            status=DiscoveryJobStatus.QUEUED,
            stages=tuple(
                DiscoveryStageProgress(stage=stage) for stage in DISCOVERY_STAGE_ORDER
            ),
            message="전체시장 종목 발굴 작업이 대기열에 등록되었습니다.",
            created_at=created_at,
            updated_at=created_at,
        )
        task = asyncio.create_task(
            self._run(job_id, runner),
            name=f"discovery-job-{job_id}",
        )
        self._tasks[job_id] = task

        def discard_completed_task(completed: asyncio.Task[None]) -> None:
            if self._tasks.get(job_id) is completed:
                self._tasks.pop(job_id, None)

        task.add_done_callback(discard_completed_task)
        return job_id

    def get(self, job_id: UUID | str) -> DiscoveryJob:
        """현재 작업 스냅샷을 조회한다."""

        resolved_id = self._resolve_id(job_id)
        try:
            return self._jobs[resolved_id]
        except KeyError as exc:
            raise DiscoveryJobNotFoundError(
                f"종목 발굴 작업을 찾을 수 없습니다. id={resolved_id}"
            ) from exc

    async def wait(self, job_id: UUID | str) -> DiscoveryJob:
        """작업이 끝날 때까지 기다린 뒤 최종 스냅샷을 반환한다."""

        resolved_id = self._resolve_id(job_id)
        self.get(resolved_id)
        task = self._tasks.get(resolved_id)
        if task is not None:
            await asyncio.shield(task)
        return self.get(resolved_id)

    async def close(self) -> None:
        """서버 종료 시 실행 중인 발굴 작업을 취소하고 정리한다."""

        tasks = tuple(self._tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def _run(self, job_id: UUID, runner: DiscoveryRunner) -> None:
        started_at = self._now()
        self._replace_job(
            job_id,
            status=DiscoveryJobStatus.RUNNING,
            message="전체시장 종목 발굴 작업을 시작했습니다.",
            started_at=started_at,
            updated_at=started_at,
        )

        async def report(update: DiscoveryProgressUpdate) -> None:
            self._apply_progress(job_id, update)

        try:
            raw_outcome = await runner(report)
            outcome = (
                raw_outcome
                if isinstance(raw_outcome, DiscoveryJobOutcome)
                else DiscoveryJobOutcome(result=raw_outcome)
            )
        except asyncio.CancelledError:
            self._mark_failed(job_id, "종목 발굴 작업이 취소되었습니다.")
            raise
        except Exception as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            self._mark_failed(job_id, detail[:2_000])
            return

        completed_at = self._now()
        self._replace_job(
            job_id,
            status=outcome.status,
            result=outcome.result,
            message=outcome.message
            or (
                "일부 자료 공백과 함께 종목 발굴 작업을 마쳤습니다."
                if outcome.status is DiscoveryJobStatus.PARTIAL
                else "종목 발굴 작업을 마쳤습니다."
            ),
            error=None,
            completed_at=completed_at,
            updated_at=completed_at,
        )

    def _apply_progress(self, job_id: UUID, update: DiscoveryProgressUpdate) -> None:
        job = self.get(job_id)
        if job.status not in {DiscoveryJobStatus.QUEUED, DiscoveryJobStatus.RUNNING}:
            raise ValueError("종료된 종목 발굴 작업은 진행 상태를 갱신할 수 없습니다.")

        now = self._now()
        stage_index = DISCOVERY_STAGE_ORDER.index(update.stage)
        current = job.stages[stage_index]
        total = current.total if update.total is None else update.total
        processed = current.processed if update.processed is None else update.processed
        passed = current.passed if update.passed is None else update.passed
        failed = current.failed if update.failed is None else update.failed
        cached = current.cached if update.cached is None else update.cached
        completed = update.completed or (total > 0 and processed == total)
        next_stage = DiscoveryStageProgress(
            stage=update.stage,
            total=total,
            processed=processed,
            passed=passed,
            failed=failed,
            cached=cached,
            message=current.message if update.message is None else update.message,
            started_at=current.started_at or now,
            completed_at=(current.completed_at or now) if completed else None,
        )
        stages = list(job.stages)
        stages[stage_index] = next_stage
        self._replace_job(
            job_id,
            status=DiscoveryJobStatus.RUNNING,
            current_stage=update.stage,
            stages=tuple(stages),
            message=next_stage.message or job.message,
            started_at=job.started_at or now,
            updated_at=now,
        )

    def _mark_failed(self, job_id: UUID, detail: str) -> None:
        completed_at = self._now()
        job = self.get(job_id)
        self._replace_job(
            job_id,
            status=DiscoveryJobStatus.FAILED,
            message="종목 발굴 작업이 실패했습니다.",
            error=detail,
            started_at=job.started_at or completed_at,
            completed_at=completed_at,
            updated_at=completed_at,
        )

    def _replace_job(self, job_id: UUID, **updates: object) -> None:
        self._jobs[job_id] = self.get(job_id).model_copy(update=updates)

    def _now(self) -> datetime:
        now = self._now_factory()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now_factory는 시간대가 있는 datetime을 반환해야 합니다.")
        return now.astimezone(UTC)

    @staticmethod
    def _resolve_id(job_id: UUID | str) -> UUID:
        if isinstance(job_id, UUID):
            return job_id
        try:
            return UUID(job_id)
        except (TypeError, ValueError) as exc:
            raise DiscoveryJobNotFoundError(
                f"종목 발굴 작업 ID 형식이 올바르지 않습니다. id={job_id}"
            ) from exc
