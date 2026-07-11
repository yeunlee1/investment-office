# 기존 분석 결과를 근거 중심 발언과 회의록으로 구성하는 투자위원회 브로커
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from investment_office.domain import (
    AgentOutput,
    AgentOutputStatus,
    AgentRole,
    AnalysisRunStatus,
    Event,
    EventType,
    Evidence,
    Snapshot,
    SnapshotKind,
    utc_now,
)
from investment_office.services.event_broker import EventBroker
from investment_office.services.orchestrator import AnalysisProvider
from investment_office.storage import Storage

JsonDict = dict[str, JsonValue]
JSON_DICT_ADAPTER = TypeAdapter(JsonDict)
logger = logging.getLogger(__name__)

COMMITTEE_ROLES = (
    AgentRole.FUNDAMENTAL,
    AgentRole.TECHNICAL,
    AgentRole.NEWS,
    AgentRole.BULL,
    AgentRole.BEAR,
    AgentRole.HEAD_TRADER,
)
ROLE_RANK = {role: index for index, role in enumerate(COMMITTEE_ROLES)}
CLAIM_FIELDS = (
    ("key_points", "claim"),
    ("risks", "risk"),
    ("invalidations", "invalidation"),
    ("data_gaps", "data_gap"),
)


class CommitteeError(RuntimeError):
    """투자위원회 실행의 공통 오류."""


class CommitteeNotFoundError(CommitteeError):
    """분석 실행이나 활성 회의를 찾지 못한 경우."""


class CommitteeConflictError(CommitteeError):
    """동일 분석 실행에 이미 활성 회의가 있는 경우."""


class CommitteeValidationError(CommitteeError, ValueError):
    """회의 입력이나 제어 명령이 허용 범위를 벗어난 경우."""


class CommitteeAgentError(CommitteeError):
    """지정 발언 호출이 실패했지만 결과를 보존한 경우."""


class CommitteeStatus(StrEnum):
    RUNNING = "running"
    STOP_REQUESTED = "stop_requested"
    COMPLETED = "completed"
    STOPPED = "stopped"


class CommitteeTurnStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    MISSING = "missing"


class CommitteeTurnSource(StrEnum):
    EXISTING = "existing_output"
    DIRECTED = "directed_speak"


class CommitteeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CommitteeTurn(CommitteeModel):
    sequence: int = Field(ge=1)
    role: AgentRole
    source: CommitteeTurnSource
    status: CommitteeTurnStatus
    source_output_id: UUID | None = None
    content: str = ""
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    stance: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    data: JsonDict = Field(default_factory=dict)
    error: str | None = None
    created_at: AwareDatetime = Field(default_factory=utc_now)


class ClaimLedgerEntry(CommitteeModel):
    claim_id: str
    kind: str
    text: str
    roles: list[AgentRole]
    turn_sequences: list[int]
    source_output_ids: list[UUID]
    evidence: list[Evidence]
    evidence_status: str


class CommitteeMeetingState(CommitteeModel):
    session_id: UUID
    analysis_run_id: UUID
    candidate_id: UUID
    ticker: str
    topic: str = Field(min_length=1, max_length=500)
    status: CommitteeStatus
    selected_roles: list[AgentRole]
    max_turns: int = Field(ge=1)
    turns: list[CommitteeTurn]
    claim_ledger: list[ClaimLedgerEntry]
    stop_requested: bool = False
    stop_reason: str | None = None
    started_at: AwareDatetime
    updated_at: AwareDatetime


class CommitteeMinutes(CommitteeModel):
    session_id: UUID
    analysis_run_id: UUID
    candidate_id: UUID
    ticker: str
    topic: str = Field(min_length=1, max_length=500)
    status: CommitteeStatus
    selected_roles: list[AgentRole]
    max_turns: int
    total_turns: int
    turns: list[CommitteeTurn]
    claim_ledger: list[ClaimLedgerEntry]
    stance_by_role: dict[str, str]
    chairman_summary: str | None
    chairman_recommendation: str | None
    bull_case: str | None
    bear_case: str | None
    data_gaps: list[str]
    failures: list[str]
    stop_reason: str | None = None
    generation_method: str = "deterministic_claim_ledger_v1"
    human_approval_required: bool = True
    auto_trade: bool = False
    started_at: AwareDatetime
    ended_at: AwareDatetime


@dataclass
class _ClaimAccumulator:
    kind: str
    text: str
    roles: list[AgentRole] = field(default_factory=list)
    sequences: list[int] = field(default_factory=list)
    output_ids: list[UUID] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class _ActiveMeeting:
    session_id: UUID
    analysis_run_id: UUID
    candidate_id: UUID
    ticker: str
    topic: str
    selected_roles: tuple[AgentRole, ...]
    max_turns: int
    started_at: AwareDatetime
    turns: list[CommitteeTurn]
    stop_requested: bool = False
    stop_reason: str | None = None
    operation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class CommitteeBroker:
    """기존 에이전트 결과를 감사 가능한 투자위원회 회의로 구성한다."""

    def __init__(
        self,
        *,
        storage: Storage,
        provider: AnalysisProvider | None = None,
        event_broker: EventBroker | None = None,
        max_allowed_turns: int = 24,
    ) -> None:
        if max_allowed_turns < len(COMMITTEE_ROLES):
            raise ValueError("max_allowed_turns must fit the default committee")
        self.storage = storage
        self.provider = provider
        self.event_broker = event_broker
        self.max_allowed_turns = max_allowed_turns
        self._active_by_run: dict[UUID, _ActiveMeeting] = {}
        self._states_by_session: dict[UUID, CommitteeMeetingState] = {}
        self._minutes_by_session: dict[UUID, CommitteeMinutes] = {}
        self._registry_lock = asyncio.Lock()

    async def start_meeting(
        self,
        run_id: UUID,
        *,
        topic: str,
        roles: Sequence[AgentRole | str] | None = None,
        max_turns: int = 12,
    ) -> CommitteeMeetingState:
        """완료된 분석 결과를 고정 순서의 회의 발언으로 불러온다."""

        normalized_topic = topic.strip()
        if not 1 <= len(normalized_topic) <= 500:
            raise CommitteeValidationError("topic은 1~500자여야 합니다.")
        selected_roles = self._normalize_roles(roles)
        if not len(selected_roles) <= max_turns <= self.max_allowed_turns:
            raise CommitteeValidationError(
                f"max_turns는 참가 역할 수 이상 {self.max_allowed_turns} 이하여야 합니다."
            )

        run = self.storage.get_analysis_run(run_id)
        if run is None:
            raise CommitteeNotFoundError("분석 실행을 찾을 수 없습니다.")
        if run.status is not AnalysisRunStatus.COMPLETED:
            raise CommitteeValidationError("완료된 분석 실행만 회의를 시작할 수 있습니다.")
        candidate = self.storage.get_candidate(run.candidate_id)
        if candidate is None:
            raise CommitteeNotFoundError("투자 후보를 찾을 수 없습니다.")

        outputs = self.storage.list_agent_outputs(run_id)
        turns = self._initial_turns(selected_roles, outputs)
        meeting = _ActiveMeeting(
            session_id=uuid4(),
            analysis_run_id=run.id,
            candidate_id=candidate.id,
            ticker=candidate.ticker,
            topic=normalized_topic,
            selected_roles=selected_roles,
            max_turns=max_turns,
            started_at=utc_now(),
            turns=turns,
        )

        async with self._registry_lock:
            if run_id in self._active_by_run:
                raise CommitteeConflictError("이 분석 실행에는 이미 활성 회의가 있습니다.")
            self._active_by_run[run_id] = meeting

        try:
            state = self._build_state(meeting, CommitteeStatus.RUNNING)
            self._save_state_snapshot(meeting, state)
            await self._record_event(
                meeting,
                "투자위원회 회의가 시작되었습니다.",
                "committee_started",
                {"selected_roles": [role.value for role in selected_roles]},
            )
            return state
        except BaseException:
            async with self._registry_lock:
                self._active_by_run.pop(run_id, None)
            raise

    async def directed_speak(
        self,
        run_id: UUID,
        role: AgentRole | str,
        instruction: str,
    ) -> CommitteeTurn:
        """사람이 지정한 한 역할만 추가로 호출하고 성공과 실패를 모두 저장한다."""

        meeting = self._require_active(run_id)
        normalized_role = self._normalize_role(role)
        normalized_instruction = instruction.strip()
        if not 1 <= len(normalized_instruction) <= 2_000:
            raise CommitteeValidationError("instruction은 1~2000자여야 합니다.")
        if normalized_role not in meeting.selected_roles:
            raise CommitteeValidationError("선택된 참가 역할만 추가 발언할 수 있습니다.")
        if self.provider is None:
            raise CommitteeValidationError("추가 발언에 사용할 AnalysisProvider가 없습니다.")

        async with meeting.operation_lock:
            if meeting.stop_requested:
                raise CommitteeValidationError("중단 요청된 회의에는 발언을 추가할 수 없습니다.")
            if len(meeting.turns) >= meeting.max_turns:
                raise CommitteeValidationError("회의의 최대 발언 수에 도달했습니다.")

            sequence = len(meeting.turns) + 1
            output = AgentOutput(
                analysis_run_id=run_id,
                role=normalized_role,
                status=AgentOutputStatus.RUNNING,
                data=JSON_DICT_ADAPTER.validate_python(
                    {
                        "committee": {
                            "session_id": str(meeting.session_id),
                            "sequence": sequence,
                            "source": CommitteeTurnSource.DIRECTED.value,
                            "instruction": normalized_instruction,
                        }
                    }
                ),
            )
            self.storage.save_agent_output(output)
            await self._record_event(
                meeting,
                f"{normalized_role.value} 역할의 지정 발언을 시작했습니다.",
                "directed_speak_started",
                {"role": normalized_role.value, "sequence": sequence},
            )

            try:
                result = await self.provider.analyze(
                    normalized_role.value,
                    meeting.ticker,
                    self._market_snapshot(run_id),
                    self._provider_context(meeting, normalized_instruction),
                )
                validated = JSON_DICT_ADAPTER.validate_python(result)
                confidence = self._confidence(validated.get("confidence"))
                evidence = self._evidence_from_result(validated)
                committee_meta = output.data["committee"]
                output.status = AgentOutputStatus.COMPLETED
                output.content = str(validated.get("summary", ""))
                output.confidence = confidence
                output.evidence = evidence
                output.data = dict(validated)
                output.data["committee"] = committee_meta
                output.updated_at = utc_now()
                self.storage.save_agent_output(output)
                turn = self._turn_from_output(
                    sequence,
                    output,
                    CommitteeTurnSource.DIRECTED,
                )
                meeting.turns.append(turn)
                state = self._build_state(
                    meeting,
                    CommitteeStatus.STOP_REQUESTED
                    if meeting.stop_requested
                    else CommitteeStatus.RUNNING,
                )
                self._save_state_snapshot(meeting, state)
                await self._record_event(
                    meeting,
                    f"{normalized_role.value} 역할의 지정 발언이 완료되었습니다.",
                    "directed_speak_completed",
                    {"role": normalized_role.value, "sequence": sequence},
                )
                return turn
            except Exception as exc:
                output.status = AgentOutputStatus.FAILED
                output.error_message = str(exc)[:4_000]
                output.updated_at = utc_now()
                self.storage.save_agent_output(output)
                turn = self._turn_from_output(
                    sequence,
                    output,
                    CommitteeTurnSource.DIRECTED,
                )
                meeting.turns.append(turn)
                self._save_state_snapshot(
                    meeting,
                    self._build_state(
                        meeting,
                        CommitteeStatus.STOP_REQUESTED
                        if meeting.stop_requested
                        else CommitteeStatus.RUNNING,
                    ),
                )
                await self._record_event(
                    meeting,
                    f"{normalized_role.value} 역할의 지정 발언이 실패했습니다.",
                    "directed_speak_failed",
                    {
                        "role": normalized_role.value,
                        "sequence": sequence,
                        "error": str(exc)[:500],
                    },
                )
                raise CommitteeAgentError(str(exc)) from exc

    async def finalize_meeting(self, run_id: UUID) -> CommitteeMinutes:
        """추가 모델 호출 없이 claim ledger와 최종 회의록을 저장한다."""

        meeting = self._require_active(run_id)
        async with meeting.operation_lock:
            status = (
                CommitteeStatus.STOPPED
                if meeting.stop_requested
                else CommitteeStatus.COMPLETED
            )
            return await self._finish_meeting(meeting, status)

    async def stop_meeting(self, run_id: UUID, reason: str) -> CommitteeMinutes:
        """중단 요청을 기록하고 진행 중 발언이 끝난 뒤 부분 회의록을 보존한다."""

        normalized_reason = reason.strip()
        if not 1 <= len(normalized_reason) <= 2_000:
            raise CommitteeValidationError("중단 사유는 1~2000자여야 합니다.")
        meeting = self._require_active(run_id)
        meeting.stop_requested = True
        meeting.stop_reason = normalized_reason
        self._cache_state(self._build_state(meeting, CommitteeStatus.STOP_REQUESTED))
        await self._record_event(
            meeting,
            "투자위원회 회의 중단이 요청되었습니다.",
            "committee_stop_requested",
            {"reason": normalized_reason},
        )
        async with meeting.operation_lock:
            return await self._finish_meeting(meeting, CommitteeStatus.STOPPED)

    def get_state(self, session_id: UUID) -> CommitteeMeetingState | None:
        """세션 식별자로 현재 또는 종료된 회의 상태를 조회한다."""

        state = self._states_by_session.get(session_id)
        if state is None:
            self._recover_snapshot(session_id)
            state = self._states_by_session.get(session_id)
        return state.model_copy(deep=True) if state is not None else None

    def get_minutes(self, session_id: UUID) -> CommitteeMinutes | None:
        """세션 식별자로 저장된 회의록을 조회하거나 스냅샷에서 복원한다."""

        minutes = self._minutes_by_session.get(session_id)
        if minutes is None:
            self._recover_snapshot(session_id)
            minutes = self._minutes_by_session.get(session_id)
        return minutes.model_copy(deep=True) if minutes is not None else None

    def get_active_state(self, run_id: UUID) -> CommitteeMeetingState | None:
        """분석 실행 식별자로 활성 회의 상태를 조회한다."""

        meeting = self._active_by_run.get(run_id)
        if meeting is None:
            return None
        status = (
            CommitteeStatus.STOP_REQUESTED
            if meeting.stop_requested
            else CommitteeStatus.RUNNING
        )
        return self._build_state(meeting, status)

    def get_latest_state(self, run_id: UUID) -> CommitteeMeetingState | None:
        """활성 회의를 우선하고 없으면 최신 스냅샷의 회의 상태를 반환한다."""

        active = self.get_active_state(run_id)
        if active is not None:
            return active
        for snapshot in self.storage.list_snapshots(run_id, kind=SnapshotKind.AGENT_STATE):
            state = self._restore_snapshot(snapshot)
            if state is not None:
                return state.model_copy(deep=True)
        return None

    def is_active(self, run_id: UUID) -> bool:
        return run_id in self._active_by_run

    async def _finish_meeting(
        self,
        meeting: _ActiveMeeting,
        status: CommitteeStatus,
    ) -> CommitteeMinutes:
        existing = self._minutes_by_session.get(meeting.session_id)
        if existing is not None:
            return existing.model_copy(deep=True)
        ended_at = utc_now()
        minutes = self._build_minutes(meeting, status, ended_at)
        state = self._build_state(meeting, status, updated_at=ended_at)
        payload = JSON_DICT_ADAPTER.validate_python(
            {
                "committee": state.model_dump(mode="json"),
                "minutes": minutes.model_dump(mode="json"),
            }
        )
        self.storage.save_snapshot(
            Snapshot(
                candidate_id=meeting.candidate_id,
                analysis_run_id=meeting.analysis_run_id,
                kind=SnapshotKind.AGENT_STATE,
                data=payload,
                checksum=self._checksum(payload),
            )
        )
        self._cache_state(state)
        self._minutes_by_session[minutes.session_id] = minutes.model_copy(deep=True)
        await self._record_event(
            meeting,
            "투자위원회 회의록이 저장되었습니다.",
            "committee_finished",
            {"status": status.value, "total_turns": len(meeting.turns)},
        )
        async with self._registry_lock:
            current = self._active_by_run.get(meeting.analysis_run_id)
            if current is meeting:
                self._active_by_run.pop(meeting.analysis_run_id, None)
        return minutes

    def _build_state(
        self,
        meeting: _ActiveMeeting,
        status: CommitteeStatus,
        *,
        updated_at: AwareDatetime | None = None,
    ) -> CommitteeMeetingState:
        return CommitteeMeetingState(
            session_id=meeting.session_id,
            analysis_run_id=meeting.analysis_run_id,
            candidate_id=meeting.candidate_id,
            ticker=meeting.ticker,
            topic=meeting.topic,
            status=status,
            selected_roles=list(meeting.selected_roles),
            max_turns=meeting.max_turns,
            turns=[turn.model_copy(deep=True) for turn in meeting.turns],
            claim_ledger=self._claim_ledger(meeting.turns),
            stop_requested=meeting.stop_requested,
            stop_reason=meeting.stop_reason,
            started_at=meeting.started_at,
            updated_at=updated_at or utc_now(),
        )

    def _build_minutes(
        self,
        meeting: _ActiveMeeting,
        status: CommitteeStatus,
        ended_at: AwareDatetime,
    ) -> CommitteeMinutes:
        completed = [
            turn for turn in meeting.turns if turn.status is CommitteeTurnStatus.COMPLETED
        ]
        by_role: dict[AgentRole, CommitteeTurn] = {}
        for turn in completed:
            by_role[turn.role] = turn
        ledger = self._claim_ledger(meeting.turns)
        bull = by_role.get(AgentRole.BULL)
        bear = by_role.get(AgentRole.BEAR)
        stance_by_role = {
            role.value: turn.stance
            for role, turn in by_role.items()
            if turn.stance is not None
        }
        chairman = by_role.get(AgentRole.HEAD_TRADER)
        return CommitteeMinutes(
            session_id=meeting.session_id,
            analysis_run_id=meeting.analysis_run_id,
            candidate_id=meeting.candidate_id,
            ticker=meeting.ticker,
            topic=meeting.topic,
            status=status,
            selected_roles=list(meeting.selected_roles),
            max_turns=meeting.max_turns,
            total_turns=len(meeting.turns),
            turns=[turn.model_copy(deep=True) for turn in meeting.turns],
            claim_ledger=ledger,
            stance_by_role=stance_by_role,
            chairman_summary=chairman.content if chairman else None,
            chairman_recommendation=(
                str(chairman.data["recommendation"])
                if chairman and "recommendation" in chairman.data
                else None
            ),
            bull_case=bull.content if bull is not None else None,
            bear_case=bear.content if bear is not None else None,
            data_gaps=[entry.text for entry in ledger if entry.kind == "data_gap"],
            failures=[
                f"{turn.role.value}: {turn.error or turn.status.value}"
                for turn in meeting.turns
                if turn.status is not CommitteeTurnStatus.COMPLETED
            ],
            stop_reason=meeting.stop_reason,
            started_at=meeting.started_at,
            ended_at=ended_at,
        )

    def _initial_turns(
        self,
        roles: tuple[AgentRole, ...],
        outputs: list[AgentOutput],
    ) -> list[CommitteeTurn]:
        turns: list[CommitteeTurn] = []
        for sequence, role in enumerate(roles, start=1):
            candidates = [
                output
                for output in outputs
                if output.role is role and not self._is_directed_output(output)
            ]
            completed = [
                output
                for output in candidates
                if output.status is AgentOutputStatus.COMPLETED
            ]
            selected = (completed or candidates)[-1] if candidates else None
            if selected is None:
                turns.append(
                    CommitteeTurn(
                        sequence=sequence,
                        role=role,
                        source=CommitteeTurnSource.EXISTING,
                        status=CommitteeTurnStatus.MISSING,
                        error="완료된 분석 결과가 없습니다.",
                    )
                )
            else:
                turns.append(
                    self._turn_from_output(
                        sequence,
                        selected,
                        CommitteeTurnSource.EXISTING,
                    )
                )
        return turns

    @staticmethod
    def _turn_from_output(
        sequence: int,
        output: AgentOutput,
        source: CommitteeTurnSource,
    ) -> CommitteeTurn:
        status = (
            CommitteeTurnStatus.COMPLETED
            if output.status is AgentOutputStatus.COMPLETED
            else CommitteeTurnStatus.FAILED
        )
        stance_value = output.data.get("stance")
        return CommitteeTurn(
            sequence=sequence,
            role=output.role,
            source=source,
            status=status,
            source_output_id=output.id,
            content=output.content,
            confidence=output.confidence,
            stance=str(stance_value) if isinstance(stance_value, str) else None,
            evidence=[item.model_copy(deep=True) for item in output.evidence],
            data=dict(output.data),
            error=output.error_message,
            created_at=output.updated_at,
        )

    def _claim_ledger(self, turns: list[CommitteeTurn]) -> list[ClaimLedgerEntry]:
        claims: dict[tuple[str, str], _ClaimAccumulator] = {}
        for turn in turns:
            if turn.status is not CommitteeTurnStatus.COMPLETED:
                continue
            found_claim = False
            for field_name, kind in CLAIM_FIELDS:
                for text in self._string_list(turn.data.get(field_name)):
                    found_claim = found_claim or kind == "claim"
                    self._accumulate_claim(claims, kind, text, turn)
            if not found_claim and turn.content.strip():
                self._accumulate_claim(claims, "summary", turn.content.strip(), turn)

        entries: list[ClaimLedgerEntry] = []
        for accumulator in claims.values():
            evidence = self._deduplicate_evidence(accumulator.evidence)
            normalized = self._normalize_claim(accumulator.text)
            claim_id = hashlib.sha256(
                f"{accumulator.kind}|{normalized}".encode()
            ).hexdigest()[:16]
            entries.append(
                ClaimLedgerEntry(
                    claim_id=claim_id,
                    kind=accumulator.kind,
                    text=accumulator.text,
                    roles=sorted(accumulator.roles, key=ROLE_RANK.__getitem__),
                    turn_sequences=sorted(accumulator.sequences),
                    source_output_ids=accumulator.output_ids,
                    evidence=evidence,
                    evidence_status=(
                        "cited"
                        if any(item.url is not None for item in evidence)
                        else "described"
                        if evidence
                        else "uncited"
                    ),
                )
            )
        return sorted(entries, key=lambda item: (item.turn_sequences[0], item.claim_id))

    def _accumulate_claim(
        self,
        claims: dict[tuple[str, str], _ClaimAccumulator],
        kind: str,
        text: str,
        turn: CommitteeTurn,
    ) -> None:
        normalized = self._normalize_claim(text)
        if not normalized:
            return
        key = (kind, normalized)
        accumulator = claims.setdefault(key, _ClaimAccumulator(kind=kind, text=text.strip()))
        if turn.role not in accumulator.roles:
            accumulator.roles.append(turn.role)
        if turn.sequence not in accumulator.sequences:
            accumulator.sequences.append(turn.sequence)
        if turn.source_output_id and turn.source_output_id not in accumulator.output_ids:
            accumulator.output_ids.append(turn.source_output_id)
        accumulator.evidence.extend(item.model_copy(deep=True) for item in turn.evidence)

    def _save_state_snapshot(
        self,
        meeting: _ActiveMeeting,
        state: CommitteeMeetingState,
    ) -> None:
        payload = JSON_DICT_ADAPTER.validate_python(
            {"committee": state.model_dump(mode="json")}
        )
        self.storage.save_snapshot(
            Snapshot(
                candidate_id=meeting.candidate_id,
                analysis_run_id=meeting.analysis_run_id,
                kind=SnapshotKind.AGENT_STATE,
                data=payload,
                checksum=self._checksum(payload),
            )
        )
        self._cache_state(state)

    def _cache_state(self, state: CommitteeMeetingState) -> None:
        self._states_by_session[state.session_id] = state.model_copy(deep=True)

    def _recover_snapshot(self, session_id: UUID) -> None:
        for run in self.storage.list_analysis_runs():
            snapshots = self.storage.list_snapshots(run.id, kind=SnapshotKind.AGENT_STATE)
            for snapshot in snapshots:
                if self._restore_snapshot(snapshot, expected_session_id=session_id) is not None:
                    return

    def _restore_snapshot(
        self,
        snapshot: Snapshot,
        *,
        expected_session_id: UUID | None = None,
    ) -> CommitteeMeetingState | None:
        committee_payload = snapshot.data.get("committee")
        if not isinstance(committee_payload, dict):
            return None
        if (
            expected_session_id is not None
            and committee_payload.get("session_id") != str(expected_session_id)
        ):
            return None
        state = CommitteeMeetingState.model_validate(committee_payload)
        self._cache_state(state)
        if state.status in {CommitteeStatus.RUNNING, CommitteeStatus.STOP_REQUESTED}:
            existing = self._active_by_run.get(state.analysis_run_id)
            if existing is None:
                self._active_by_run[state.analysis_run_id] = _ActiveMeeting(
                    session_id=state.session_id,
                    analysis_run_id=state.analysis_run_id,
                    candidate_id=state.candidate_id,
                    ticker=state.ticker,
                    topic=state.topic,
                    selected_roles=tuple(state.selected_roles),
                    max_turns=state.max_turns,
                    started_at=state.started_at,
                    turns=[turn.model_copy(deep=True) for turn in state.turns],
                    stop_requested=state.stop_requested,
                    stop_reason=state.stop_reason,
                )
        minutes_payload = snapshot.data.get("minutes")
        if isinstance(minutes_payload, dict):
            minutes = CommitteeMinutes.model_validate(minutes_payload)
            self._minutes_by_session[state.session_id] = minutes
        return state

    async def _record_event(
        self,
        meeting: _ActiveMeeting,
        message: str,
        action: str,
        payload: dict[str, Any],
    ) -> None:
        event_payload = JSON_DICT_ADAPTER.validate_python(
            {
                "committee_action": action,
                "session_id": str(meeting.session_id),
                **payload,
            }
        )
        event = Event(
            event_type=EventType.STATUS_CHANGED,
            message=message,
            candidate_id=meeting.candidate_id,
            analysis_run_id=meeting.analysis_run_id,
            payload=event_payload,
        )
        try:
            self.storage.append_event(event)
        except Exception:
            logger.exception(
                "회의 이벤트 저장에 실패했습니다.",
                extra={"analysis_run_id": str(meeting.analysis_run_id)},
            )
        if self.event_broker is not None:
            try:
                await self.event_broker.publish(
                    {
                        "event_id": str(event.id),
                        "type": "committee",
                        "event_type": event.event_type.value,
                        "message": event.message,
                        "candidate_id": str(meeting.candidate_id),
                        "run_id": str(meeting.analysis_run_id),
                        "session_id": str(meeting.session_id),
                        "created_at": event.created_at.isoformat(),
                        **payload,
                    }
                )
            except Exception:
                logger.exception(
                    "회의 실시간 이벤트 발행에 실패했습니다.",
                    extra={"analysis_run_id": str(meeting.analysis_run_id)},
                )

    def _require_active(self, run_id: UUID) -> _ActiveMeeting:
        meeting = self._active_by_run.get(run_id)
        if meeting is None:
            raise CommitteeNotFoundError("활성 투자위원회 회의를 찾을 수 없습니다.")
        return meeting

    def _normalize_roles(
        self,
        roles: Sequence[AgentRole | str] | None,
    ) -> tuple[AgentRole, ...]:
        requested = (
            COMMITTEE_ROLES
            if roles is None
            else tuple(self._normalize_role(role) for role in roles)
        )
        if not requested:
            raise CommitteeValidationError("한 개 이상의 참가 역할이 필요합니다.")
        if len(set(requested)) != len(requested):
            raise CommitteeValidationError("참가 역할을 중복 선택할 수 없습니다.")
        requested_set = set(requested)
        return tuple(role for role in COMMITTEE_ROLES if role in requested_set)

    @staticmethod
    def _normalize_role(role: AgentRole | str) -> AgentRole:
        try:
            normalized = role if isinstance(role, AgentRole) else AgentRole(role)
        except ValueError as exc:
            raise CommitteeValidationError("지원하지 않는 투자위원회 역할입니다.") from exc
        if normalized not in COMMITTEE_ROLES:
            raise CommitteeValidationError("지원하지 않는 투자위원회 역할입니다.")
        return normalized

    def _market_snapshot(self, run_id: UUID) -> dict[str, Any]:
        snapshots = self.storage.list_snapshots(run_id, kind=SnapshotKind.MARKET_DATA)
        return dict(snapshots[0].data) if snapshots else {}

    @staticmethod
    def _provider_context(
        meeting: _ActiveMeeting,
        instruction: str,
    ) -> list[dict[str, Any]]:
        context = [
            {
                "type": "committee_turn",
                "sequence": turn.sequence,
                "role": turn.role.value,
                "status": turn.status.value,
                "summary": turn.content,
                "result": turn.data,
            }
            for turn in meeting.turns
        ]
        context.append(
            {
                "committee_directed_request": {
                    "prompt": instruction,
                    "scope": "analysis_focus_only",
                }
            }
        )
        return context

    @staticmethod
    def _confidence(value: JsonValue | None) -> float | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return None

    @staticmethod
    def _evidence_from_result(result: JsonDict) -> list[Evidence]:
        evidence: list[Evidence] = []
        raw_items = result.get("evidence")
        if not isinstance(raw_items, list):
            return evidence
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            title = str(raw_item.get("claim", "근거")).strip() or "근거"
            evidence.append(
                Evidence.model_validate(
                    {
                        "title": title,
                        "fact_id": raw_item.get("fact_id"),
                        "url": raw_item.get("source_url"),
                        "published_at": raw_item.get("published_at"),
                    }
                )
            )
        return evidence

    @staticmethod
    def _string_list(value: JsonValue | None) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    @staticmethod
    def _normalize_claim(text: str) -> str:
        return re.sub(r"\s+", " ", text.strip()).casefold()

    @staticmethod
    def _deduplicate_evidence(evidence: list[Evidence]) -> list[Evidence]:
        result: list[Evidence] = []
        seen: set[tuple[str, str | None, str | None]] = set()
        for item in evidence:
            key = (item.title, item.fact_id, str(item.url) if item.url else None)
            if key in seen:
                continue
            seen.add(key)
            result.append(item.model_copy(deep=True))
        return result

    @staticmethod
    def _is_directed_output(output: AgentOutput) -> bool:
        committee = output.data.get("committee")
        return isinstance(committee, dict) and committee.get("source") == "directed_speak"

    @staticmethod
    def _checksum(payload: JsonDict) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()
