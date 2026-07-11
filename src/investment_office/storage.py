# MariaDB 전용 스키마 메타데이터와 주입형 저장소를 제공하는 저장 계층
from __future__ import annotations

from collections.abc import Callable, Mapping
from threading import RLock
from typing import Any, Protocol, cast, runtime_checkable
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import JSON, Date, ForeignKey, Index, MetaData, String, select
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from investment_office.domain import (
    AgentOutput,
    AgentOutputStatus,
    AgentRole,
    AnalysisRun,
    AnalysisRunStatus,
    Candidate,
    CandidateStatus,
    DomainModel,
    Event,
    HumanReview,
    Snapshot,
    SnapshotKind,
)

DATABASE_NAME = "pixel_investment_office"

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


TABLE_OPTIONS: dict[str, str] = {
    "schema": DATABASE_NAME,
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
}


class CandidateRecord(Base):
    __tablename__ = "candidates"
    __table_args__ = (
        Index("ix_candidates_status_updated", "status", "updated_at"),
        Index("ix_candidates_ticker_created", "ticker", "created_at"),
        TABLE_OPTIONS,
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(15), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[Any] = mapped_column(DATETIME(fsp=6), nullable=False)
    updated_at: Mapped[Any] = mapped_column(DATETIME(fsp=6), nullable=False)


class AnalysisRunRecord(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        Index("ix_analysis_runs_candidate_requested", "candidate_id", "requested_at"),
        Index("ix_analysis_runs_status_updated", "status", "updated_at"),
        TABLE_OPTIONS,
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{DATABASE_NAME}.candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    as_of_date: Mapped[Any] = mapped_column(Date, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    requested_at: Mapped[Any] = mapped_column(DATETIME(fsp=6), nullable=False)
    updated_at: Mapped[Any] = mapped_column(DATETIME(fsp=6), nullable=False)


class AgentOutputRecord(Base):
    __tablename__ = "agent_outputs"
    __table_args__ = (
        Index("ix_agent_outputs_run_role_created", "analysis_run_id", "role", "created_at"),
        TABLE_OPTIONS,
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{DATABASE_NAME}.analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[Any] = mapped_column(DATETIME(fsp=6), nullable=False)
    updated_at: Mapped[Any] = mapped_column(DATETIME(fsp=6), nullable=False)


class EventRecord(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_candidate_created", "candidate_id", "created_at"),
        Index("ix_events_run_created", "analysis_run_id", "created_at"),
        TABLE_OPTIONS,
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(f"{DATABASE_NAME}.candidates.id", ondelete="CASCADE"),
        nullable=True,
    )
    analysis_run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(f"{DATABASE_NAME}.analysis_runs.id", ondelete="CASCADE"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[Any] = mapped_column(DATETIME(fsp=6), nullable=False)


class ReviewRecord(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        Index("ix_reviews_run_created", "analysis_run_id", "created_at"),
        TABLE_OPTIONS,
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{DATABASE_NAME}.candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    analysis_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{DATABASE_NAME}.analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[Any] = mapped_column(DATETIME(fsp=6), nullable=False)


class SnapshotRecord(Base):
    __tablename__ = "snapshots"
    __table_args__ = (
        Index("ix_snapshots_run_kind_captured", "analysis_run_id", "kind", "captured_at"),
        TABLE_OPTIONS,
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{DATABASE_NAME}.candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    analysis_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{DATABASE_NAME}.analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    captured_at: Mapped[Any] = mapped_column(DATETIME(fsp=6), nullable=False)


MARIADB_METADATA = Base.metadata

SessionFactory = Callable[[], Session]


def serialize_domain(model: DomainModel) -> dict[str, JsonValue]:
    """Pydantic 도메인 객체를 MariaDB JSON 컬럼에 안전한 값으로 바꾼다."""

    return cast(dict[str, JsonValue], model.model_dump(mode="json"))


def deserialize_domain[ModelT: DomainModel](
    model_type: type[ModelT], payload: Mapping[str, JsonValue]
) -> ModelT:
    """MariaDB JSON 컬럼 값을 지정한 도메인 객체로 복원한다."""

    return model_type.model_validate(dict(payload))


def _payload(record: Any) -> Mapping[str, JsonValue]:
    return cast(Mapping[str, JsonValue], record.payload)


def _clone[ModelT: DomainModel](model: ModelT) -> ModelT:
    return model.model_copy(deep=True)


@runtime_checkable
class Storage(Protocol):
    def save_candidate(self, candidate: Candidate) -> Candidate: ...

    def get_candidate(self, candidate_id: UUID) -> Candidate | None: ...

    def list_candidates(self, *, status: CandidateStatus | None = None) -> list[Candidate]: ...

    def save_analysis_run(self, run: AnalysisRun) -> AnalysisRun: ...

    def get_analysis_run(self, run_id: UUID) -> AnalysisRun | None: ...

    def list_analysis_runs(
        self,
        *,
        candidate_id: UUID | None = None,
        status: AnalysisRunStatus | None = None,
    ) -> list[AnalysisRun]: ...

    def save_agent_output(self, output: AgentOutput) -> AgentOutput: ...

    def list_agent_outputs(
        self,
        analysis_run_id: UUID,
        *,
        role: AgentRole | None = None,
        status: AgentOutputStatus | None = None,
    ) -> list[AgentOutput]: ...

    def append_event(self, event: Event) -> Event: ...

    def list_events(
        self,
        *,
        candidate_id: UUID | None = None,
        analysis_run_id: UUID | None = None,
    ) -> list[Event]: ...

    def save_human_review(self, review: HumanReview) -> HumanReview: ...

    def list_human_reviews(self, analysis_run_id: UUID) -> list[HumanReview]: ...

    def save_snapshot(self, snapshot: Snapshot) -> Snapshot: ...

    def list_snapshots(
        self,
        analysis_run_id: UUID,
        *,
        kind: SnapshotKind | None = None,
    ) -> list[Snapshot]: ...


class InMemoryStorage:
    """DB 스키마 적용 전에도 동일 인터페이스를 제공하는 프로세스 내 저장소."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._candidates: dict[UUID, Candidate] = {}
        self._runs: dict[UUID, AnalysisRun] = {}
        self._outputs: dict[UUID, AgentOutput] = {}
        self._events: dict[UUID, Event] = {}
        self._reviews: dict[UUID, HumanReview] = {}
        self._snapshots: dict[UUID, Snapshot] = {}

    def save_candidate(self, candidate: Candidate) -> Candidate:
        with self._lock:
            self._candidates[candidate.id] = _clone(candidate)
        return _clone(candidate)

    def get_candidate(self, candidate_id: UUID) -> Candidate | None:
        with self._lock:
            candidate = self._candidates.get(candidate_id)
            return _clone(candidate) if candidate is not None else None

    def list_candidates(self, *, status: CandidateStatus | None = None) -> list[Candidate]:
        with self._lock:
            values = [
                candidate
                for candidate in self._candidates.values()
                if status is None or candidate.status == status
            ]
            values.sort(key=lambda item: item.updated_at, reverse=True)
            return [_clone(value) for value in values]

    def save_analysis_run(self, run: AnalysisRun) -> AnalysisRun:
        with self._lock:
            self._runs[run.id] = _clone(run)
        return _clone(run)

    def get_analysis_run(self, run_id: UUID) -> AnalysisRun | None:
        with self._lock:
            run = self._runs.get(run_id)
            return _clone(run) if run is not None else None

    def list_analysis_runs(
        self,
        *,
        candidate_id: UUID | None = None,
        status: AnalysisRunStatus | None = None,
    ) -> list[AnalysisRun]:
        with self._lock:
            values = [
                run
                for run in self._runs.values()
                if (candidate_id is None or run.candidate_id == candidate_id)
                and (status is None or run.status == status)
            ]
            values.sort(key=lambda item: item.requested_at, reverse=True)
            return [_clone(value) for value in values]

    def save_agent_output(self, output: AgentOutput) -> AgentOutput:
        with self._lock:
            self._outputs[output.id] = _clone(output)
        return _clone(output)

    def list_agent_outputs(
        self,
        analysis_run_id: UUID,
        *,
        role: AgentRole | None = None,
        status: AgentOutputStatus | None = None,
    ) -> list[AgentOutput]:
        with self._lock:
            values = [
                output
                for output in self._outputs.values()
                if output.analysis_run_id == analysis_run_id
                and (role is None or output.role == role)
                and (status is None or output.status == status)
            ]
            values.sort(key=lambda item: item.created_at)
            return [_clone(value) for value in values]

    def append_event(self, event: Event) -> Event:
        with self._lock:
            self._events[event.id] = _clone(event)
        return _clone(event)

    def list_events(
        self,
        *,
        candidate_id: UUID | None = None,
        analysis_run_id: UUID | None = None,
    ) -> list[Event]:
        with self._lock:
            values = [
                event
                for event in self._events.values()
                if (candidate_id is None or event.candidate_id == candidate_id)
                and (analysis_run_id is None or event.analysis_run_id == analysis_run_id)
            ]
            values.sort(key=lambda item: item.created_at)
            return [_clone(value) for value in values]

    def save_human_review(self, review: HumanReview) -> HumanReview:
        with self._lock:
            self._reviews[review.id] = _clone(review)
        return _clone(review)

    def list_human_reviews(self, analysis_run_id: UUID) -> list[HumanReview]:
        with self._lock:
            values = [
                review
                for review in self._reviews.values()
                if review.analysis_run_id == analysis_run_id
            ]
            values.sort(key=lambda item: item.created_at, reverse=True)
            return [_clone(value) for value in values]

    def save_snapshot(self, snapshot: Snapshot) -> Snapshot:
        with self._lock:
            self._snapshots[snapshot.id] = _clone(snapshot)
        return _clone(snapshot)

    def list_snapshots(
        self,
        analysis_run_id: UUID,
        *,
        kind: SnapshotKind | None = None,
    ) -> list[Snapshot]:
        with self._lock:
            values = [
                snapshot
                for snapshot in self._snapshots.values()
                if snapshot.analysis_run_id == analysis_run_id
                and (kind is None or snapshot.kind == kind)
            ]
            values.sort(key=lambda item: item.captured_at, reverse=True)
            return [_clone(value) for value in values]


class MariaDBStorage:
    """호출자가 제공한 SQLAlchemy Session 팩토리만 사용하는 MariaDB 저장소."""

    database_name = DATABASE_NAME

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def save_candidate(self, candidate: Candidate) -> Candidate:
        row = CandidateRecord(
            id=str(candidate.id),
            ticker=candidate.ticker,
            source=candidate.source.value,
            status=candidate.status.value,
            payload=serialize_domain(candidate),
            created_at=candidate.created_at,
            updated_at=candidate.updated_at,
        )
        self._merge(row)
        return _clone(candidate)

    def get_candidate(self, candidate_id: UUID) -> Candidate | None:
        with self._session_factory() as session:
            row = session.get(CandidateRecord, str(candidate_id))
            return deserialize_domain(Candidate, _payload(row)) if row is not None else None

    def list_candidates(self, *, status: CandidateStatus | None = None) -> list[Candidate]:
        statement = select(CandidateRecord)
        if status is not None:
            statement = statement.where(CandidateRecord.status == status.value)
        statement = statement.order_by(CandidateRecord.updated_at.desc())
        with self._session_factory() as session:
            rows = session.scalars(statement).all()
            return [deserialize_domain(Candidate, _payload(row)) for row in rows]

    def save_analysis_run(self, run: AnalysisRun) -> AnalysisRun:
        row = AnalysisRunRecord(
            id=str(run.id),
            candidate_id=str(run.candidate_id),
            status=run.status.value,
            as_of_date=run.as_of_date,
            payload=serialize_domain(run),
            requested_at=run.requested_at,
            updated_at=run.updated_at,
        )
        self._merge(row)
        return _clone(run)

    def get_analysis_run(self, run_id: UUID) -> AnalysisRun | None:
        with self._session_factory() as session:
            row = session.get(AnalysisRunRecord, str(run_id))
            return deserialize_domain(AnalysisRun, _payload(row)) if row is not None else None

    def list_analysis_runs(
        self,
        *,
        candidate_id: UUID | None = None,
        status: AnalysisRunStatus | None = None,
    ) -> list[AnalysisRun]:
        statement = select(AnalysisRunRecord)
        if candidate_id is not None:
            statement = statement.where(AnalysisRunRecord.candidate_id == str(candidate_id))
        if status is not None:
            statement = statement.where(AnalysisRunRecord.status == status.value)
        statement = statement.order_by(AnalysisRunRecord.requested_at.desc())
        with self._session_factory() as session:
            rows = session.scalars(statement).all()
            return [deserialize_domain(AnalysisRun, _payload(row)) for row in rows]

    def save_agent_output(self, output: AgentOutput) -> AgentOutput:
        row = AgentOutputRecord(
            id=str(output.id),
            analysis_run_id=str(output.analysis_run_id),
            role=output.role.value,
            status=output.status.value,
            payload=serialize_domain(output),
            created_at=output.created_at,
            updated_at=output.updated_at,
        )
        self._merge(row)
        return _clone(output)

    def list_agent_outputs(
        self,
        analysis_run_id: UUID,
        *,
        role: AgentRole | None = None,
        status: AgentOutputStatus | None = None,
    ) -> list[AgentOutput]:
        statement = select(AgentOutputRecord).where(
            AgentOutputRecord.analysis_run_id == str(analysis_run_id)
        )
        if role is not None:
            statement = statement.where(AgentOutputRecord.role == role.value)
        if status is not None:
            statement = statement.where(AgentOutputRecord.status == status.value)
        statement = statement.order_by(AgentOutputRecord.created_at.asc())
        with self._session_factory() as session:
            rows = session.scalars(statement).all()
            return [deserialize_domain(AgentOutput, _payload(row)) for row in rows]

    def append_event(self, event: Event) -> Event:
        row = EventRecord(
            id=str(event.id),
            candidate_id=str(event.candidate_id) if event.candidate_id is not None else None,
            analysis_run_id=(
                str(event.analysis_run_id) if event.analysis_run_id is not None else None
            ),
            event_type=event.event_type.value,
            payload=serialize_domain(event),
            created_at=event.created_at,
        )
        self._merge(row)
        return _clone(event)

    def list_events(
        self,
        *,
        candidate_id: UUID | None = None,
        analysis_run_id: UUID | None = None,
    ) -> list[Event]:
        statement = select(EventRecord)
        if candidate_id is not None:
            statement = statement.where(EventRecord.candidate_id == str(candidate_id))
        if analysis_run_id is not None:
            statement = statement.where(EventRecord.analysis_run_id == str(analysis_run_id))
        statement = statement.order_by(EventRecord.created_at.asc())
        with self._session_factory() as session:
            rows = session.scalars(statement).all()
            return [deserialize_domain(Event, _payload(row)) for row in rows]

    def save_human_review(self, review: HumanReview) -> HumanReview:
        row = ReviewRecord(
            id=str(review.id),
            candidate_id=str(review.candidate_id),
            analysis_run_id=str(review.analysis_run_id),
            decision=review.decision.value,
            payload=serialize_domain(review),
            created_at=review.created_at,
        )
        self._merge(row)
        return _clone(review)

    def list_human_reviews(self, analysis_run_id: UUID) -> list[HumanReview]:
        statement = (
            select(ReviewRecord)
            .where(ReviewRecord.analysis_run_id == str(analysis_run_id))
            .order_by(ReviewRecord.created_at.desc())
        )
        with self._session_factory() as session:
            rows = session.scalars(statement).all()
            return [deserialize_domain(HumanReview, _payload(row)) for row in rows]

    def save_snapshot(self, snapshot: Snapshot) -> Snapshot:
        row = SnapshotRecord(
            id=str(snapshot.id),
            candidate_id=str(snapshot.candidate_id),
            analysis_run_id=str(snapshot.analysis_run_id),
            kind=snapshot.kind.value,
            payload=serialize_domain(snapshot),
            captured_at=snapshot.captured_at,
        )
        self._merge(row)
        return _clone(snapshot)

    def list_snapshots(
        self,
        analysis_run_id: UUID,
        *,
        kind: SnapshotKind | None = None,
    ) -> list[Snapshot]:
        statement = select(SnapshotRecord).where(
            SnapshotRecord.analysis_run_id == str(analysis_run_id)
        )
        if kind is not None:
            statement = statement.where(SnapshotRecord.kind == kind.value)
        statement = statement.order_by(SnapshotRecord.captured_at.desc())
        with self._session_factory() as session:
            rows = session.scalars(statement).all()
            return [deserialize_domain(Snapshot, _payload(row)) for row in rows]

    def _merge(self, row: Base) -> None:
        with self._session_factory() as session, session.begin():
            session.merge(row)
