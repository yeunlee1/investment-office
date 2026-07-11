# 일회성 분석 예약의 영속성, FIFO claim과 재시작 복구를 검증한다.
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from investment_office.domain import AnalysisRun, AnalysisRunStatus, Candidate, SnapshotKind
from investment_office.services.event_broker import EventBroker
from investment_office.services.scheduled_analysis import (
    ScheduledAnalysisConflictError,
    ScheduledAnalysisService,
    ScheduledAnalysisStatus,
    ScheduledAnalysisTransitionError,
    ScheduledAnalysisValidationError,
)
from investment_office.storage import InMemoryStorage

NOW = datetime(2026, 7, 11, 6, 0, tzinfo=UTC)


def add_run(storage: InMemoryStorage, ticker: str) -> AnalysisRun:
    candidate = Candidate(ticker=ticker)
    run = AnalysisRun(
        candidate_id=candidate.id,
        requested_at=NOW,
        updated_at=NOW,
    )
    storage.save_candidate(candidate)
    storage.save_analysis_run(run)
    return run


def make_service(
    storage: InMemoryStorage | None = None,
) -> tuple[ScheduledAnalysisService, InMemoryStorage, EventBroker]:
    resolved_storage = storage or InMemoryStorage()
    broker = EventBroker()
    service = ScheduledAnalysisService(
        storage=resolved_storage,
        broker=broker,
        now_factory=lambda: NOW,
    )
    return service, resolved_storage, broker


@pytest.mark.asyncio
async def test_schedule_requires_aware_future_time_and_persists_kst_event() -> None:
    service, storage, broker = make_service()
    run = add_run(storage, "AAPL")

    with pytest.raises(ScheduledAnalysisValidationError, match="timezone-aware"):
        await service.schedule_run(run.id, datetime(2026, 7, 12, 9, 0))
    with pytest.raises(ScheduledAnalysisValidationError, match="미래"):
        await service.schedule_run(run.id, NOW)

    async with broker.subscribe() as events:
        item = await service.schedule_run(run.id, NOW + timedelta(hours=1))
        stream_event = await asyncio.wait_for(events.get(), timeout=1)

    assert item.scheduled_for.isoformat() == "2026-07-11T16:00:00+09:00"
    assert item.timezone == "Asia/Seoul"
    assert item.ticker == "AAPL"
    assert stream_event["type"] == "scheduled_analysis"
    assert stream_event["status"] == "scheduled"
    snapshots = storage.list_snapshots(run.id, kind=SnapshotKind.AGENT_STATE)
    assert snapshots[0].data["record_type"] == "scheduled_analysis"
    schedule_payload = cast(dict[str, object], snapshots[0].data["schedule"])
    assert schedule_payload["ticker"] == "AAPL"
    assert schedule_payload["run_id"] == str(run.id)

    with pytest.raises(ScheduledAnalysisConflictError, match="활성 예약"):
        await service.schedule_run(run.id, NOW + timedelta(hours=2))


@pytest.mark.asyncio
async def test_concurrent_schedule_requests_create_only_one_active_item() -> None:
    service, storage, _ = make_service()
    run = add_run(storage, "TSLA")

    results = await asyncio.gather(
        service.schedule_run(run.id, NOW + timedelta(hours=1)),
        service.schedule_run(run.id, NOW + timedelta(hours=2)),
        return_exceptions=True,
    )

    assert len(service.list_schedules(run_id=run.id)) == 1
    assert sum(isinstance(result, ScheduledAnalysisConflictError) for result in results) == 1


@pytest.mark.asyncio
async def test_claim_due_uses_scheduled_time_then_global_sequence_fifo() -> None:
    service, storage, _ = make_service()
    first_run = add_run(storage, "AAPL")
    second_run = add_run(storage, "MSFT")
    third_run = add_run(storage, "NVDA")
    same_time = NOW + timedelta(minutes=30)

    first = await service.schedule_run(first_run.id, same_time)
    second = await service.schedule_run(second_run.id, same_time)
    earlier = await service.schedule_run(third_run.id, NOW + timedelta(minutes=10))

    assert await service.claim_due(now=NOW + timedelta(minutes=9)) == []
    claimed = await service.claim_due(now=NOW + timedelta(hours=1), limit=2)

    assert [item.id for item in claimed] == [earlier.id, first.id]
    assert [item.status for item in claimed] == [
        ScheduledAnalysisStatus.CLAIMED,
        ScheduledAnalysisStatus.CLAIMED,
    ]
    assert all(item.version == 2 for item in claimed)
    assert all(item.claim_count == 1 for item in claimed)
    remaining = await service.claim_due(now=NOW + timedelta(hours=1))
    assert [item.id for item in remaining] == [second.id]

    with pytest.raises(ScheduledAnalysisValidationError, match="1 이상"):
        await service.claim_due(now=NOW + timedelta(hours=1), limit=0)


@pytest.mark.asyncio
async def test_cancel_and_dispatch_terminal_records_enforce_transitions() -> None:
    service, storage, _ = make_service()
    cancelled_run = add_run(storage, "AMD")
    completed_run = add_run(storage, "INTC")
    failed_run = add_run(storage, "QCOM")
    due_at = NOW + timedelta(minutes=1)
    cancelled_item = await service.schedule_run(cancelled_run.id, due_at)
    completed_item = await service.schedule_run(completed_run.id, due_at)
    failed_item = await service.schedule_run(failed_run.id, due_at)

    cancelled = await service.cancel(cancelled_item.id)
    assert cancelled.status is ScheduledAnalysisStatus.CANCELLED
    with pytest.raises(ScheduledAnalysisTransitionError, match="대기 중"):
        await service.cancel(cancelled_item.id)

    claimed = await service.claim_due(now=NOW + timedelta(minutes=2))
    assert {item.id for item in claimed} == {completed_item.id, failed_item.id}
    dispatched = await service.mark_dispatched(completed_item.id)
    assert dispatched.status is ScheduledAnalysisStatus.DISPATCHED

    with pytest.raises(ScheduledAnalysisTransitionError, match="완료된 분석"):
        await service.mark_dispatch_completed(completed_item.id)

    run = storage.get_analysis_run(completed_run.id)
    assert run is not None
    run.status = AnalysisRunStatus.COMPLETED
    run.completed_at = NOW + timedelta(minutes=3)
    run.updated_at = NOW + timedelta(minutes=3)
    storage.save_analysis_run(run)
    completed = await service.mark_dispatch_completed(completed_item.id)
    assert completed.status is ScheduledAnalysisStatus.COMPLETED
    assert completed.completed_at == run.completed_at

    failed = await service.mark_dispatch_failed(failed_item.id, "시장 데이터 부족")
    assert failed.status is ScheduledAnalysisStatus.FAILED
    assert failed.error == "시장 데이터 부족"


@pytest.mark.asyncio
async def test_new_service_recovers_persisted_claim_and_reconciles_dispatch() -> None:
    service, storage, _ = make_service()
    claimed_run = add_run(storage, "META")
    dispatched_run = add_run(storage, "GOOGL")
    completed_run = add_run(storage, "AMZN")
    due_at = NOW + timedelta(minutes=1)
    claimed_item = await service.schedule_run(claimed_run.id, due_at)
    dispatched_item = await service.schedule_run(dispatched_run.id, due_at)
    completed_item = await service.schedule_run(completed_run.id, due_at)
    await service.claim_due(now=NOW + timedelta(minutes=2))
    await service.mark_dispatched(dispatched_item.id)
    await service.mark_dispatched(completed_item.id)

    dispatched = storage.get_analysis_run(dispatched_run.id)
    assert dispatched is not None
    dispatched.status = AnalysisRunStatus.RUNNING
    dispatched.started_at = NOW + timedelta(minutes=2)
    dispatched.updated_at = NOW + timedelta(minutes=2)
    storage.save_analysis_run(dispatched)
    completed = storage.get_analysis_run(completed_run.id)
    assert completed is not None
    completed.status = AnalysisRunStatus.COMPLETED
    completed.started_at = NOW + timedelta(minutes=2)
    completed.completed_at = NOW + timedelta(minutes=3)
    completed.updated_at = NOW + timedelta(minutes=3)
    storage.save_analysis_run(completed)

    restarted, _, _ = make_service(storage)
    recovered = await restarted.recover()
    recovered_by_id = {item.id: item for item in recovered}

    assert recovered_by_id[claimed_item.id].status is ScheduledAnalysisStatus.SCHEDULED
    assert recovered_by_id[dispatched_item.id].status is ScheduledAnalysisStatus.FAILED
    assert "재시작" in (recovered_by_id[dispatched_item.id].error or "")
    assert recovered_by_id[completed_item.id].status is ScheduledAnalysisStatus.COMPLETED
    claimed_again = await restarted.claim_due(now=NOW + timedelta(minutes=4))
    assert [item.id for item in claimed_again] == [claimed_item.id]
    assert claimed_again[0].claim_count == 2
    assert restarted.get_schedule(claimed_item.id).version == 4


@pytest.mark.asyncio
async def test_due_schedule_reconciles_run_that_was_completed_before_dispatch() -> None:
    service, storage, _ = make_service()
    run = add_run(storage, "NFLX")
    item = await service.schedule_run(run.id, NOW + timedelta(minutes=1))
    stored_run = storage.get_analysis_run(run.id)
    assert stored_run is not None
    stored_run.status = AnalysisRunStatus.COMPLETED
    stored_run.started_at = NOW
    stored_run.completed_at = NOW + timedelta(seconds=30)
    stored_run.updated_at = NOW + timedelta(seconds=30)
    storage.save_analysis_run(stored_run)

    assert await service.claim_due(now=NOW + timedelta(minutes=2)) == []
    reconciled = service.get_schedule(item.id)
    assert reconciled.status is ScheduledAnalysisStatus.COMPLETED
    assert reconciled.completed_at == stored_run.completed_at
