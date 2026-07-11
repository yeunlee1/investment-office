# NPC 수동 업무 항목의 순차 실행, 저장 보고와 새 시도 재개를 검증한다.
from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from investment_office.domain import (
    AgentRole,
    AnalysisRun,
    AnalysisRunStatus,
    Candidate,
    EventType,
    Snapshot,
    SnapshotKind,
)
from investment_office.services.event_broker import EventBroker
from investment_office.services.orchestrator import AnalysisProvider
from investment_office.services.work_items import (
    RESUME_SEMANTICS,
    WorkItemService,
    WorkItemStatus,
    WorkItemTransitionError,
)
from investment_office.storage import InMemoryStorage


class GateProvider:
    def __init__(self, *, fail_first: bool = False, block_first: bool = False) -> None:
        self.fail_first = fail_first
        self.block_first = block_first
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls: list[dict[str, Any]] = []
        self.active = 0
        self.max_active = 0

    async def analyze(
        self,
        role: str,
        ticker: str,
        snapshot: dict[str, Any],
        context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        call_index = len(self.calls)
        self.calls.append(
            {
                "role": role,
                "ticker": ticker,
                "snapshot": snapshot,
                "context": context,
            }
        )
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if call_index == 0:
                self.started.set()
                if self.block_first:
                    await self.release.wait()
                if self.fail_first:
                    raise RuntimeError("실제 실행기 실패")
            manual_request = next(
                item["manual_work_request"] for item in context if "manual_work_request" in item
            )
            return {
                "role": role,
                "ticker": ticker,
                "summary": f"실제 저장 결과 {call_index + 1}",
                "attempt": manual_request["attempt"],
            }
        finally:
            self.active -= 1


def make_service(
    provider: GateProvider,
    *,
    with_market_snapshot: bool = True,
    candidate: Candidate | None = None,
) -> tuple[WorkItemService, InMemoryStorage, EventBroker, AnalysisRun]:
    storage = InMemoryStorage()
    resolved_candidate = candidate or Candidate(ticker="AAPL")
    run = AnalysisRun(candidate_id=resolved_candidate.id)
    storage.save_candidate(resolved_candidate)
    storage.save_analysis_run(run)
    if with_market_snapshot:
        storage.save_snapshot(
            Snapshot(
                candidate_id=resolved_candidate.id,
                analysis_run_id=run.id,
                kind=SnapshotKind.MARKET_DATA,
                data={
                    "ticker": resolved_candidate.attributes.get(
                        "local_symbol",
                        resolved_candidate.ticker,
                    ),
                    "close": 215.0,
                    "source_url": "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
                },
            )
        )
    broker = EventBroker()
    service = WorkItemService(
        storage=storage,
        provider=cast(AnalysisProvider, provider),
        broker=broker,
    )
    return service, storage, broker, run


@pytest.mark.asyncio
async def test_korean_work_item_passes_local_symbol_to_provider() -> None:
    provider = GateProvider()
    candidate = Candidate(
        ticker="KR-005930",
        attributes={
            "market": "kr",
            "local_symbol": "005930",
            "canonical_id": "kr:005930",
            "currency": "KRW",
        },
    )
    service, _, _, run = make_service(provider, candidate=candidate)
    await service.create_work_item(
        run_id=run.id,
        role=AgentRole.FUNDAMENTAL,
        title="한국 기업 재무 확인",
        instructions="공식 재무 사실만 다시 확인한다.",
    )

    result = await service.run_next(run.id, AgentRole.FUNDAMENTAL)

    assert result is not None
    assert result.status is WorkItemStatus.COMPLETED
    assert provider.calls[0]["ticker"] == "005930"


@pytest.mark.asyncio
async def test_report_reads_only_persisted_state_without_provider_call() -> None:
    provider = GateProvider()
    service, storage, broker, run = make_service(provider)

    async with broker.subscribe() as events:
        item = await service.create_work_item(
            run_id=run.id,
            role=AgentRole.NEWS,
            title="뉴스 촉매 확인",
            instructions="저장된 시장 자료에서 확인 가능한 촉매만 정리한다.",
        )
        broker_event = await asyncio.wait_for(events.get(), timeout=1)

    report = service.request_report(run.id, item.id)

    assert provider.calls == []
    assert report.source == "stored_state"
    assert report.status is WorkItemStatus.QUEUED
    assert report.progress is None
    assert report.result is None
    assert broker_event["type"] == "work_item"
    assert broker_event["status"] == "queued"
    snapshots = storage.list_snapshots(run.id, kind=SnapshotKind.AGENT_STATE)
    assert len(snapshots) == 1
    assert snapshots[0].data["record_type"] == "manual_work_item"
    assert all(event.event_type is EventType.STATUS_CHANGED for event in storage.list_events())
    assert service.find_work_item(item.id) == item
    assert service.find_work_item(run.id) is None


@pytest.mark.asyncio
async def test_same_run_and_role_executes_only_one_item_then_next_queue_item() -> None:
    provider = GateProvider(block_first=True)
    service, _, _, run = make_service(provider)
    first = await service.create_work_item(
        run_id=run.id,
        role="technical",
        title="첫 번째 차트 점검",
        instructions="추세 지표를 점검한다.",
    )
    second = await service.create_work_item(
        run_id=run.id,
        role="technical",
        title="두 번째 차트 점검",
        instructions="변동성 지표를 점검한다.",
    )

    first_execution = asyncio.create_task(service.run_next(run.id, AgentRole.TECHNICAL))
    await asyncio.wait_for(provider.started.wait(), timeout=1)

    assert await service.run_next(run.id, AgentRole.TECHNICAL) is None
    assert service.get_work_item(run.id, first.id).status is WorkItemStatus.RUNNING
    assert service.get_work_item(run.id, second.id).status is WorkItemStatus.QUEUED

    provider.release.set()
    first_result = await asyncio.wait_for(first_execution, timeout=1)
    assert first_result is not None
    assert first_result.id == first.id
    assert first_result.status is WorkItemStatus.COMPLETED
    assert provider.calls[0]["snapshot"]["close"] == 215.0
    assert provider.calls[0]["snapshot"]["source_url"].startswith("https://query1")
    manual_request = provider.calls[0]["context"][-1]["manual_work_request"]
    assert manual_request["title"] == "첫 번째 차트 점검"
    assert manual_request["instructions"] == "추세 지표를 점검한다."

    second_result = await service.run_next(run.id, AgentRole.TECHNICAL)
    assert second_result is not None
    assert second_result.id == second.id
    assert second_result.status is WorkItemStatus.COMPLETED
    assert provider.max_active == 1
    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_failure_report_and_resume_use_stored_previous_context_for_new_attempt() -> None:
    provider = GateProvider(fail_first=True, block_first=True)
    service, storage, _, run = make_service(provider)
    item = await service.create_work_item(
        run_id=run.id,
        role=AgentRole.FUNDAMENTAL,
        title="수익성 근거 확인",
        instructions="입력 자료에 있는 마진 근거만 확인한다.",
        context=[{"source": "stored-market-snapshot"}],
    )

    first_execution = asyncio.create_task(service.run_next(run.id, AgentRole.FUNDAMENTAL))
    await asyncio.wait_for(provider.started.wait(), timeout=1)
    actual_progress = {
        "message": "실행기에서 실제로 받은 부분 결과",
        "observations": ["매출총이익률 항목을 찾았습니다."],
    }
    await service.record_progress(run.id, item.id, actual_progress)

    report_while_running = service.request_report(run.id, item.id)
    assert report_while_running.progress == actual_progress
    assert len(provider.calls) == 1

    provider.release.set()
    failed = await asyncio.wait_for(first_execution, timeout=1)
    assert failed is not None
    assert failed.status is WorkItemStatus.FAILED
    assert failed.error == "실제 실행기 실패"
    assert service.request_report(run.id, item.id).progress == actual_progress

    resumed = await service.resume_work_item(run.id, item.id)
    assert resumed.status is WorkItemStatus.QUEUED
    assert resumed.attempt == 2
    assert resumed.resume_context is not None
    assert resumed.resume_context["semantics"] == RESUME_SEMANTICS
    assert service.request_report(run.id, item.id).resume_semantics == RESUME_SEMANTICS

    completed = await service.run_next(run.id, AgentRole.FUNDAMENTAL)
    assert completed is not None
    assert completed.status is WorkItemStatus.COMPLETED
    assert completed.result == {
        "role": "fundamental",
        "ticker": "AAPL",
        "summary": "실제 저장 결과 2",
        "attempt": 2,
    }
    resume_payload = provider.calls[1]["context"][-1]["manual_work_item_resume"]
    assert resume_payload["semantics"] == RESUME_SEMANTICS
    assert resume_payload["previous_progress"] == actual_progress
    assert resume_payload["previous_error"] == "실제 실행기 실패"
    assert all(event.event_type is EventType.STATUS_CHANGED for event in storage.list_events())


@pytest.mark.asyncio
async def test_cancelled_queue_item_can_resume_as_new_attempt_only() -> None:
    provider = GateProvider()
    service, _, _, run = make_service(provider)
    item = await service.create_work_item(
        run_id=run.id,
        role=AgentRole.BEAR,
        title="하방 위험 점검",
        instructions="확인 가능한 하방 위험을 정리한다.",
    )

    cancelled = await service.cancel_work_item(run.id, item.id)
    assert cancelled.status is WorkItemStatus.CANCELLED

    resumed = await service.resume_work_item(run.id, item.id)
    assert resumed.status is WorkItemStatus.QUEUED
    assert resumed.attempt == 2
    assert resumed.resume_context is not None
    assert resumed.resume_context["previous_status"] == "cancelled"

    completed = await service.run_next(run.id, AgentRole.BEAR)
    assert completed is not None
    assert completed.status is WorkItemStatus.COMPLETED
    with pytest.raises(WorkItemTransitionError, match="실패하거나 취소된 업무"):
        await service.resume_work_item(run.id, item.id)


@pytest.mark.asyncio
async def test_run_requires_stored_market_snapshot_without_calling_provider() -> None:
    provider = GateProvider()
    service, _, _, run = make_service(provider, with_market_snapshot=False)
    item = await service.create_work_item(
        run_id=run.id,
        role=AgentRole.NEWS,
        title="시장 자료 없는 요청",
        instructions="시장 자료가 없으면 실행하지 않는다.",
    )

    with pytest.raises(WorkItemTransitionError, match="시장 데이터 스냅샷"):
        await service.run_next(run.id, AgentRole.NEWS)

    assert provider.calls == []
    assert service.get_work_item(run.id, item.id).status is WorkItemStatus.QUEUED


@pytest.mark.asyncio
async def test_terminal_run_without_market_snapshot_fails_queued_work_item() -> None:
    provider = GateProvider()
    service, storage, _, run = make_service(provider, with_market_snapshot=False)
    await service.create_work_item(
        run_id=run.id,
        role=AgentRole.NEWS,
        title="종료 분석의 실행 불가 업무",
        instructions="시장 자료가 없으면 실패 상태로 확정한다.",
    )
    stored_run = storage.get_analysis_run(run.id)
    assert stored_run is not None
    stored_run.status = AnalysisRunStatus.FAILED
    storage.save_analysis_run(stored_run)

    failed = await service.run_next(run.id, AgentRole.NEWS)

    assert failed is not None
    assert failed.status is WorkItemStatus.FAILED
    assert "시장 데이터 스냅샷" in (failed.error or "")
    assert provider.calls == []


@pytest.mark.asyncio
async def test_restart_recovery_fails_running_item_and_returns_valid_queue() -> None:
    provider = GateProvider()
    service, storage, broker, run = make_service(provider)
    running_item = await service.create_work_item(
        run_id=run.id,
        role=AgentRole.FUNDAMENTAL,
        title="재시작 전 실행 업무",
        instructions="재시작 시 실패로 복구한다.",
    )
    queued_item = await service.create_work_item(
        run_id=run.id,
        role=AgentRole.NEWS,
        title="재시작 뒤 대기 업무",
        instructions="유효한 대기열로 돌려준다.",
    )
    interrupted = running_item.model_copy(
        update={
            "status": WorkItemStatus.RUNNING,
            "version": running_item.version + 1,
            "started_at": running_item.updated_at,
            "updated_at": running_item.updated_at,
        }
    )
    storage.save_snapshot(
        Snapshot(
            candidate_id=interrupted.candidate_id,
            analysis_run_id=interrupted.analysis_run_id,
            kind=SnapshotKind.AGENT_STATE,
            data={
                "record_type": "manual_work_item",
                "schema_version": 1,
                "work_item": interrupted.model_dump(mode="json"),
            },
        )
    )
    restarted = WorkItemService(
        storage=storage,
        provider=cast(AnalysisProvider, provider),
        broker=broker,
    )

    queued = await restarted.recover()

    recovered = restarted.get_work_item(run.id, running_item.id)
    assert recovered.status is WorkItemStatus.FAILED
    assert "서버 재시작" in (recovered.error or "")
    assert [item.id for item in queued] == [queued_item.id]
    assert provider.calls == []
