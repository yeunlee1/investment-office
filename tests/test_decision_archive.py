# 과거 의사결정 카드의 정렬, 상태, 필터와 사람 승인 정보를 검증한다.
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

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
from investment_office.services.decision_archive import (
    DecisionArchiveNotFoundError,
    DecisionArchiveService,
)
from investment_office.storage import InMemoryStorage


def save_run(
    storage: InMemoryStorage,
    *,
    ticker: str,
    requested_at: datetime,
    status: AnalysisRunStatus,
    error: str | None = None,
) -> tuple[Candidate, AnalysisRun]:
    candidate = Candidate(
        ticker=ticker,
        company_name=f"{ticker} 회사",
        thesis=f"{ticker} 투자 가설",
        status=(
            CandidateStatus.READY_FOR_REVIEW
            if status == AnalysisRunStatus.COMPLETED
            else CandidateStatus.QUEUED
        ),
        created_at=requested_at,
        updated_at=requested_at,
    )
    run = AnalysisRun(
        candidate_id=candidate.id,
        status=status,
        as_of_date=date(2026, 7, 11),
        error_message=error,
        requested_at=requested_at,
        updated_at=requested_at,
    )
    storage.save_candidate(candidate)
    storage.save_analysis_run(run)
    return candidate, run


def test_lists_all_runs_newest_first_and_preserves_previous_decision() -> None:
    storage = InMemoryStorage()
    service = DecisionArchiveService(storage=storage)
    now = datetime(2026, 7, 11, 5, tzinfo=UTC)
    candidate, completed = save_run(
        storage,
        ticker="AAPL",
        requested_at=now,
        status=AnalysisRunStatus.COMPLETED,
    )
    storage.save_snapshot(
        Snapshot(
            candidate_id=candidate.id,
            analysis_run_id=completed.id,
            kind=SnapshotKind.DECISION,
            data={"action": "watch", "confidence": 0.72},
            captured_at=now + timedelta(minutes=5),
        )
    )
    newer_candidate, failed = save_run(
        storage,
        ticker="MSFT",
        requested_at=now + timedelta(hours=1),
        status=AnalysisRunStatus.FAILED,
        error="시장 데이터 부족",
    )
    queued_candidate, queued = save_run(
        storage,
        ticker="NVDA",
        requested_at=now + timedelta(hours=2),
        status=AnalysisRunStatus.QUEUED,
    )

    entries = service.list_entries()

    assert [entry.run_id for entry in entries] == [queued.id, failed.id, completed.id]
    assert entries[0].decision is None
    assert entries[0].effective_status == "queued"
    assert entries[1].ticker == newer_candidate.ticker
    assert entries[1].error == "시장 데이터 부족"
    assert entries[2].decision == {"action": "watch", "confidence": 0.72}
    assert entries[2].auto_trade is False
    assert entries[2].human_approval_required is True
    assert queued_candidate.ticker == entries[0].ticker


def test_uses_latest_decision_and_latest_human_review() -> None:
    storage = InMemoryStorage()
    service = DecisionArchiveService(storage=storage)
    now = datetime(2026, 7, 11, 5, tzinfo=UTC)
    candidate, run = save_run(
        storage,
        ticker="AAPL",
        requested_at=now,
        status=AnalysisRunStatus.COMPLETED,
    )
    storage.save_snapshot(
        Snapshot(
            candidate_id=candidate.id,
            analysis_run_id=run.id,
            kind=SnapshotKind.DECISION,
            data={"action": "avoid"},
            captured_at=now + timedelta(minutes=1),
        )
    )
    latest_snapshot = storage.save_snapshot(
        Snapshot(
            candidate_id=candidate.id,
            analysis_run_id=run.id,
            kind=SnapshotKind.DECISION,
            data={"action": "buy_later"},
            captured_at=now + timedelta(minutes=2),
        )
    )
    storage.save_human_review(
        HumanReview(
            candidate_id=candidate.id,
            analysis_run_id=run.id,
            decision=ReviewDecision.REJECTED,
            rationale="근거 부족",
            created_at=now + timedelta(minutes=3),
        )
    )
    latest_review = storage.save_human_review(
        HumanReview(
            candidate_id=candidate.id,
            analysis_run_id=run.id,
            decision=ReviewDecision.APPROVED,
            rationale="보완 조건 충족",
            approved_position_pct=3,
            created_at=now + timedelta(minutes=4),
        )
    )

    entry = service.get_entry(run.id)

    assert entry.decision == {"action": "buy_later"}
    assert entry.decision_snapshot_id == latest_snapshot.id
    assert entry.latest_human_review == latest_review
    assert entry.human_review_count == 2
    assert entry.human_approved is True


def test_combines_scheduled_analysis_metadata_for_queued_run() -> None:
    storage = InMemoryStorage()
    service = DecisionArchiveService(storage=storage)
    now = datetime(2026, 7, 11, 5, tzinfo=UTC)
    candidate, run = save_run(
        storage,
        ticker="AAPL",
        requested_at=now,
        status=AnalysisRunStatus.QUEUED,
    )
    schedule_id = uuid4()
    base_schedule = {
        "id": str(schedule_id),
        "analysis_run_id": str(run.id),
        "candidate_id": str(candidate.id),
        "status": "scheduled",
        "scheduled_for": (now + timedelta(days=1)).isoformat(),
        "timezone": "Asia/Seoul",
        "sequence": 1,
        "version": 1,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "claimed_at": None,
        "dispatched_at": None,
        "completed_at": None,
        "error": None,
    }
    storage.save_snapshot(
        Snapshot(
            candidate_id=candidate.id,
            analysis_run_id=run.id,
            kind=SnapshotKind.AGENT_STATE,
            data={
                "record_type": "scheduled_analysis",
                "schema_version": 1,
                "schedule": base_schedule,
            },
            captured_at=now,
        )
    )
    storage.save_snapshot(
        Snapshot(
            candidate_id=candidate.id,
            analysis_run_id=run.id,
            kind=SnapshotKind.AGENT_STATE,
            data={
                "record_type": "scheduled_analysis",
                "schema_version": 1,
                "schedule": {
                    **base_schedule,
                    "status": "claimed",
                    "version": 2,
                    "updated_at": (now + timedelta(minutes=1)).isoformat(),
                    "claimed_at": (now + timedelta(minutes=1)).isoformat(),
                },
            },
            captured_at=now - timedelta(minutes=1),
        )
    )

    entry = service.get_entry(run.id)

    assert entry.effective_status == "claimed"
    assert entry.scheduled_analysis is not None
    assert entry.scheduled_analysis.id == schedule_id
    assert entry.scheduled_analysis.version == 2
    assert entry.scheduled_analysis.timezone == "Asia/Seoul"
    assert entry.decision is None
    assert entry.human_approved is False


def test_filters_ticker_case_insensitively_and_applies_limit() -> None:
    storage = InMemoryStorage()
    service = DecisionArchiveService(storage=storage)
    now = datetime(2026, 7, 11, 5, tzinfo=UTC)
    _, older = save_run(
        storage,
        ticker="AAPL",
        requested_at=now,
        status=AnalysisRunStatus.COMPLETED,
    )
    _, newer = save_run(
        storage,
        ticker="AAPL",
        requested_at=now + timedelta(hours=1),
        status=AnalysisRunStatus.RUNNING,
    )
    save_run(
        storage,
        ticker="MSFT",
        requested_at=now + timedelta(hours=2),
        status=AnalysisRunStatus.COMPLETED,
    )

    entries = service.list_entries(ticker=" aapl ", limit=1)

    assert [entry.run_id for entry in entries] == [newer.id]
    assert older.id != entries[0].run_id


def test_rejects_invalid_filters_and_missing_run() -> None:
    service = DecisionArchiveService(storage=InMemoryStorage())

    with pytest.raises(ValueError, match="limit"):
        service.list_entries(limit=0)
    with pytest.raises(ValueError, match="ticker"):
        service.list_entries(ticker="   ")
    with pytest.raises(DecisionArchiveNotFoundError, match="찾을 수 없습니다"):
        service.get_entry(uuid4())
