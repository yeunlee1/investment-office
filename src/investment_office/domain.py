# 투자 후보와 분석 실행, 에이전트 판단, 사람 검토를 정의하는 도메인 모델
from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import (
    AnyHttpUrl,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)


def utc_now() -> datetime:
    """도메인 객체의 기본 시각을 UTC로 생성한다."""

    return datetime.now(UTC)


class CandidateSource(StrEnum):
    USER = "user"
    SYSTEM = "system"


class CandidateStatus(StrEnum):
    QUEUED = "queued"
    ANALYZING = "analyzing"
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class AnalysisRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentRole(StrEnum):
    TECHNICAL = "technical"
    NEWS = "news"
    FUNDAMENTAL = "fundamental"
    SENTIMENT = "sentiment"
    BULL = "bull"
    BEAR = "bear"
    HEAD_TRADER = "head_trader"
    RISK_MANAGER = "risk_manager"


class AgentOutputStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EventType(StrEnum):
    CANDIDATE_CREATED = "candidate_created"
    ANALYSIS_QUEUED = "analysis_queued"
    ANALYSIS_STARTED = "analysis_started"
    AGENT_OUTPUT_RECORDED = "agent_output_recorded"
    ANALYSIS_COMPLETED = "analysis_completed"
    ANALYSIS_FAILED = "analysis_failed"
    HUMAN_REVIEW_RECORDED = "human_review_recorded"
    STATUS_CHANGED = "status_changed"


class ReviewDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    DEFERRED = "deferred"


class SnapshotKind(StrEnum):
    INPUT = "input"
    MARKET_DATA = "market_data"
    AGENT_STATE = "agent_state"
    DECISION = "decision"
    PORTFOLIO = "portfolio"


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Evidence(DomainModel):
    title: str = Field(min_length=1, max_length=300)
    url: AnyHttpUrl | None = None
    published_at: AwareDatetime | None = None
    excerpt: str | None = Field(default=None, max_length=2_000)


class Candidate(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    ticker: str = Field(min_length=1, max_length=15, pattern=r"^[A-Z][A-Z0-9.\-]{0,14}$")
    company_name: str | None = Field(default=None, max_length=200)
    source: CandidateSource = CandidateSource.USER
    thesis: str | None = Field(default=None, max_length=5_000)
    submitted_by: str = Field(default="human", min_length=1, max_length=120)
    status: CandidateStatus = CandidateStatus.QUEUED
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: AwareDatetime = Field(default_factory=utc_now)
    updated_at: AwareDatetime = Field(default_factory=utc_now)

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        return self


class AnalysisRun(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    candidate_id: UUID
    status: AnalysisRunStatus = AnalysisRunStatus.QUEUED
    as_of_date: date = Field(default_factory=lambda: utc_now().date())
    configuration: dict[str, JsonValue] = Field(default_factory=dict)
    error_message: str | None = Field(default=None, max_length=4_000)
    requested_at: AwareDatetime = Field(default_factory=utc_now)
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    updated_at: AwareDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        if self.started_at is not None and self.started_at < self.requested_at:
            raise ValueError("started_at must not precede requested_at")
        lower_bound = self.started_at or self.requested_at
        if self.completed_at is not None and self.completed_at < lower_bound:
            raise ValueError("completed_at must not precede the run start")
        if self.updated_at < self.requested_at:
            raise ValueError("updated_at must not precede requested_at")
        return self


class AgentOutput(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    analysis_run_id: UUID
    role: AgentRole
    status: AgentOutputStatus = AgentOutputStatus.QUEUED
    content: str = Field(default="", max_length=100_000)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)
    data: dict[str, JsonValue] = Field(default_factory=dict)
    error_message: str | None = Field(default=None, max_length=4_000)
    created_at: AwareDatetime = Field(default_factory=utc_now)
    updated_at: AwareDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        return self


class Event(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    event_type: EventType
    message: str = Field(min_length=1, max_length=2_000)
    candidate_id: UUID | None = None
    analysis_run_id: UUID | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: AwareDatetime = Field(default_factory=utc_now)


class HumanReview(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    candidate_id: UUID
    analysis_run_id: UUID
    decision: ReviewDecision
    reviewer: str = Field(default="human", min_length=1, max_length=120)
    rationale: str = Field(min_length=1, max_length=10_000)
    approved_position_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    approved_risk_units: float | None = Field(default=None, ge=0.0, le=100.0)
    conditions: list[str] = Field(default_factory=list, max_length=50)
    created_at: AwareDatetime = Field(default_factory=utc_now)


class Snapshot(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    candidate_id: UUID
    analysis_run_id: UUID
    kind: SnapshotKind
    data: dict[str, JsonValue] = Field(default_factory=dict)
    checksum: str | None = Field(default=None, max_length=128)
    captured_at: AwareDatetime = Field(default_factory=utc_now)
