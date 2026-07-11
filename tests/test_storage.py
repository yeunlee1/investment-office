# MariaDB 연결 없이 도메인 직렬화와 저장 계층 계약을 검증하는 테스트
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from investment_office.domain import (
    AgentOutput,
    AgentOutputStatus,
    AgentRole,
    AnalysisRun,
    AnalysisRunStatus,
    Candidate,
    CandidateStatus,
    Event,
    EventType,
    HumanReview,
    ReviewDecision,
    Snapshot,
    SnapshotKind,
)
from investment_office.storage import (
    DATABASE_NAME,
    MARIADB_METADATA,
    AnalysisRunRecord,
    InMemoryStorage,
    MariaDBStorage,
    deserialize_domain,
    serialize_domain,
)

NOW = datetime(2026, 7, 11, 0, 0, tzinfo=UTC)


def _candidate() -> Candidate:
    return Candidate(
        ticker=" nvda ",
        company_name="NVIDIA",
        thesis="AI 인프라 수요를 검토한다.",
        created_at=NOW,
        updated_at=NOW,
    )


def test_domain_payload_round_trip_preserves_types() -> None:
    candidate = _candidate()

    restored = deserialize_domain(Candidate, serialize_domain(candidate))

    assert restored == candidate
    assert restored.ticker == "NVDA"
    assert restored.id == candidate.id
    assert restored.created_at.tzinfo is not None


def test_metadata_contains_only_approved_mariadb_tables() -> None:
    tables = set(MARIADB_METADATA.tables)

    assert tables == {
        f"{DATABASE_NAME}.candidates",
        f"{DATABASE_NAME}.analysis_runs",
        f"{DATABASE_NAME}.agent_outputs",
        f"{DATABASE_NAME}.events",
        f"{DATABASE_NAME}.reviews",
        f"{DATABASE_NAME}.snapshots",
    }
    assert all(table.schema == DATABASE_NAME for table in MARIADB_METADATA.tables.values())


def test_mariadb_ddl_compiles_without_opening_a_database() -> None:
    sql = str(CreateTable(AnalysisRunRecord.__table__).compile(dialect=mysql.dialect()))

    assert "CREATE TABLE pixel_investment_office.analysis_runs" in sql
    assert "FOREIGN KEY(candidate_id)" in sql
    assert "pixel_investment_office.candidates" in sql
    assert "JSON" in sql


def test_mariadb_storage_constructor_does_not_open_a_session() -> None:
    calls = 0

    def forbidden_session_factory() -> Session:
        nonlocal calls
        calls += 1
        raise AssertionError("생성 중에는 DB 세션을 열면 안 됩니다.")

    storage = MariaDBStorage(forbidden_session_factory)

    assert storage.database_name == DATABASE_NAME
    assert calls == 0


def test_in_memory_storage_supports_full_review_flow_without_database() -> None:
    storage = InMemoryStorage()
    candidate = storage.save_candidate(_candidate())
    run = storage.save_analysis_run(
        AnalysisRun(
            candidate_id=candidate.id,
            status=AnalysisRunStatus.RUNNING,
            requested_at=NOW,
            started_at=NOW,
            updated_at=NOW,
        )
    )
    output = storage.save_agent_output(
        AgentOutput(
            analysis_run_id=run.id,
            role=AgentRole.FUNDAMENTAL,
            status=AgentOutputStatus.COMPLETED,
            content="매출 성장과 밸류에이션을 함께 검토했다.",
            confidence=0.7,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    event = storage.append_event(
        Event(
            event_type=EventType.AGENT_OUTPUT_RECORDED,
            message="기본적 분석이 완료되었다.",
            candidate_id=candidate.id,
            analysis_run_id=run.id,
            created_at=NOW,
        )
    )
    review = storage.save_human_review(
        HumanReview(
            candidate_id=candidate.id,
            analysis_run_id=run.id,
            decision=ReviewDecision.DEFERRED,
            rationale="실적 발표 이후 다시 판단한다.",
            created_at=NOW,
        )
    )
    snapshot = storage.save_snapshot(
        Snapshot(
            candidate_id=candidate.id,
            analysis_run_id=run.id,
            kind=SnapshotKind.DECISION,
            data={"decision": "deferred"},
            captured_at=NOW,
        )
    )

    assert storage.get_candidate(candidate.id) == candidate
    assert storage.get_analysis_run(run.id) == run
    assert storage.list_agent_outputs(run.id) == [output]
    assert storage.list_events(analysis_run_id=run.id) == [event]
    assert storage.list_human_reviews(run.id) == [review]
    assert storage.list_snapshots(run.id) == [snapshot]


def test_in_memory_storage_filters_and_returns_defensive_copies() -> None:
    storage = InMemoryStorage()
    queued = storage.save_candidate(_candidate())
    approved = storage.save_candidate(
        _candidate().model_copy(
            update={
                "id": uuid4(),
                "ticker": "AAPL",
                "status": CandidateStatus.APPROVED,
            }
        )
    )

    fetched = storage.get_candidate(queued.id)
    assert fetched is not None
    fetched.thesis = "호출자가 바꾼 값"

    assert storage.get_candidate(queued.id) == queued
    assert storage.list_candidates(status=CandidateStatus.APPROVED) == [approved]
