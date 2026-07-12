# 전체시장 종목 발굴 작업의 비동기 상태 전이와 오류 격리를 검증한다.
from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest

from investment_office.services.discovery_jobs import (
    DISCOVERY_STAGE_ORDER,
    DiscoveryJobNotFoundError,
    DiscoveryJobOutcome,
    DiscoveryJobService,
    DiscoveryJobStatus,
    DiscoveryProgressCallback,
    DiscoveryProgressUpdate,
    DiscoveryStage,
)


@pytest.mark.asyncio
async def test_create_returns_queued_id_before_runner_finishes() -> None:
    service = DiscoveryJobService()
    runner_started = asyncio.Event()
    release_runner = asyncio.Event()

    async def runner(progress: DiscoveryProgressCallback) -> dict[str, bool]:
        del progress
        runner_started.set()
        await release_runner.wait()
        return {"ready": True}

    job_id = service.create(runner)
    queued = service.get(str(job_id))

    assert queued.status is DiscoveryJobStatus.QUEUED
    assert not runner_started.is_set()
    assert tuple(stage.stage for stage in queued.stages) == DISCOVERY_STAGE_ORDER

    await asyncio.wait_for(runner_started.wait(), timeout=1)
    assert service.get(job_id).status is DiscoveryJobStatus.RUNNING

    release_runner.set()
    completed = await asyncio.wait_for(service.wait(job_id), timeout=1)

    assert completed.status is DiscoveryJobStatus.COMPLETE
    assert completed.result == {"ready": True}
    assert completed.started_at is not None
    assert completed.completed_at is not None
    payload = completed.model_dump(mode="json")
    assert payload["status"] == "complete"
    assert [stage["stage"] for stage in payload["stages"]] == [
        stage.value for stage in DISCOVERY_STAGE_ORDER
    ]
    json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_progress_callback_updates_stage_counts_and_timestamps() -> None:
    service = DiscoveryJobService()
    progress_recorded = asyncio.Event()
    release_runner = asyncio.Event()

    async def runner(progress: DiscoveryProgressCallback) -> dict[str, int]:
        await progress(
            DiscoveryProgressUpdate(
                stage=DiscoveryStage.FUNDAMENTALS,
                total=10,
                processed=4,
                passed=2,
                failed=1,
                cached=2,
                message="재무제표 4개를 확인했습니다.",
            )
        )
        progress_recorded.set()
        await release_runner.wait()
        await progress(
            DiscoveryProgressUpdate(
                stage=DiscoveryStage.FUNDAMENTALS,
                total=10,
                processed=10,
                passed=7,
                failed=3,
                cached=4,
                message="재무제표 검사를 마쳤습니다.",
            )
        )
        return {"qualified": 7}

    job_id = service.create(runner)
    await asyncio.wait_for(progress_recorded.wait(), timeout=1)
    running = service.get(job_id)
    fundamentals = running.stages[DISCOVERY_STAGE_ORDER.index(DiscoveryStage.FUNDAMENTALS)]

    assert running.current_stage is DiscoveryStage.FUNDAMENTALS
    assert fundamentals.total == 10
    assert fundamentals.processed == 4
    assert fundamentals.passed == 2
    assert fundamentals.failed == 1
    assert fundamentals.cached == 2
    assert fundamentals.started_at is not None
    assert fundamentals.completed_at is None

    release_runner.set()
    completed = await asyncio.wait_for(service.wait(job_id), timeout=1)
    fundamentals = completed.stages[
        DISCOVERY_STAGE_ORDER.index(DiscoveryStage.FUNDAMENTALS)
    ]

    assert fundamentals.processed == 10
    assert fundamentals.completed_at is not None
    assert fundamentals.message == "재무제표 검사를 마쳤습니다."


@pytest.mark.asyncio
async def test_runner_can_finish_with_partial_result() -> None:
    service = DiscoveryJobService()

    async def runner(progress: DiscoveryProgressCallback) -> DiscoveryJobOutcome:
        await progress(
            DiscoveryProgressUpdate(
                stage=DiscoveryStage.RANKING,
                total=5,
                processed=3,
                passed=3,
                completed=True,
                message="가격 자료가 있는 후보만 순위를 계산했습니다.",
            )
        )
        return DiscoveryJobOutcome(
            status=DiscoveryJobStatus.PARTIAL,
            result={"candidates": 3, "missing": 2},
            message="두 종목의 가격 자료가 부족합니다.",
        )

    completed = await asyncio.wait_for(service.wait(service.create(runner)), timeout=1)

    assert completed.status is DiscoveryJobStatus.PARTIAL
    assert completed.result == {"candidates": 3, "missing": 2}
    assert completed.message == "두 종목의 가격 자료가 부족합니다."
    assert completed.error is None


@pytest.mark.asyncio
async def test_runner_exception_is_isolated_as_failed_job() -> None:
    service = DiscoveryJobService()

    async def runner(progress: DiscoveryProgressCallback) -> dict[str, bool]:
        del progress
        raise RuntimeError("재무 공급원이 응답하지 않았습니다.")

    failed = await asyncio.wait_for(service.wait(service.create(runner)), timeout=1)

    assert failed.status is DiscoveryJobStatus.FAILED
    assert failed.result is None
    assert failed.message == "종목 발굴 작업이 실패했습니다."
    assert failed.error == "재무 공급원이 응답하지 않았습니다."
    assert failed.completed_at is not None


def test_missing_job_id_raises_domain_error() -> None:
    service = DiscoveryJobService()

    with pytest.raises(DiscoveryJobNotFoundError):
        service.get(uuid4())

    with pytest.raises(DiscoveryJobNotFoundError):
        service.get("not-a-uuid")
