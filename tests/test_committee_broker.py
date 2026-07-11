# 투자위원회 브로커의 근거 집계와 회의 제어 안전장치를 검증한다.
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from investment_office.domain import (
    AgentOutput,
    AgentOutputStatus,
    AgentRole,
    AnalysisRun,
    AnalysisRunStatus,
    Candidate,
    Evidence,
    Snapshot,
    SnapshotKind,
)
from investment_office.services.committee_broker import (
    COMMITTEE_ROLES,
    CommitteeAgentError,
    CommitteeBroker,
    CommitteeConflictError,
    CommitteeNotFoundError,
    CommitteeStatus,
    CommitteeTurnStatus,
    CommitteeValidationError,
)
from investment_office.storage import InMemoryStorage

NOW = datetime(2026, 7, 11, 3, 0, tzinfo=UTC)
SOURCE_URL = "https://example.com/market-snapshot"


class FakeProvider:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def analyze(
        self,
        role: str,
        ticker: str,
        snapshot: dict[str, Any],
        context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "role": role,
                "ticker": ticker,
                "snapshot": snapshot,
                "context": context,
            }
        )
        if self.error is not None:
            raise self.error
        return {
            "role": role,
            "ticker": ticker,
            "stance": "neutral",
            "confidence": 0.68,
            "summary": "추가 확인 결과 기존 결론을 유지한다.",
            "key_points": ["추가 데이터도 현금흐름 안정성을 지지한다."],
            "evidence": [
                {
                    "claim": "시장 스냅샷을 다시 확인했다.",
                    "fact_id": "price:test:close",
                    "source_url": SOURCE_URL,
                    "published_at": None,
                }
            ],
            "risks": ["예상보다 높은 변동성이 남아 있다."],
            "recommendation": "사람 검토 전까지 대기한다.",
            "data_gaps": [],
            "invalidations": ["현금흐름이 둔화되면 재검토한다."],
        }


def seed_completed_run(
    storage: InMemoryStorage,
    *,
    include_roles: tuple[AgentRole, ...] = COMMITTEE_ROLES,
) -> AnalysisRun:
    candidate = storage.save_candidate(
        Candidate(ticker="AAPL", thesis="서비스 매출의 질을 검토한다.")
    )
    run = storage.save_analysis_run(
        AnalysisRun(
            candidate_id=candidate.id,
            status=AnalysisRunStatus.COMPLETED,
            requested_at=NOW,
            started_at=NOW,
            completed_at=NOW,
            updated_at=NOW,
        )
    )
    storage.save_snapshot(
        Snapshot(
            candidate_id=candidate.id,
            analysis_run_id=run.id,
            kind=SnapshotKind.MARKET_DATA,
            data={"ticker": "AAPL", "close": 215.0, "source_url": SOURCE_URL},
            captured_at=NOW,
        )
    )
    for index, role in enumerate(include_roles):
        shared_claim = (
            "서비스 매출이 현금흐름 안정성을 높인다."
            if role in {AgentRole.FUNDAMENTAL, AgentRole.TECHNICAL}
            else f"{role.value} 역할의 핵심 주장"
        )
        storage.save_agent_output(
            AgentOutput(
                analysis_run_id=run.id,
                role=role,
                status=AgentOutputStatus.COMPLETED,
                content=f"{role.value} 기존 분석 발언",
                confidence=0.6 + index * 0.03,
                evidence=[
                    Evidence.model_validate(
                        {"title": "입력 시장 데이터", "url": SOURCE_URL}
                    )
                ],
                data={
                    "stance": (
                        "bullish"
                        if role is AgentRole.BULL
                        else "bearish"
                        if role is AgentRole.BEAR
                        else "neutral"
                    ),
                    "key_points": [shared_claim],
                    "risks": [f"{role.value} 관점의 리스크"],
                    "data_gaps": [f"{role.value} 추가 확인 자료"],
                    "invalidations": [f"{role.value} 무효화 조건"],
                    "recommendation": "조건부 관찰",
                },
                created_at=NOW,
                updated_at=NOW,
            )
        )
    return run


@pytest.mark.asyncio
async def test_existing_outputs_form_deterministic_ledger_and_minutes() -> None:
    storage = InMemoryStorage()
    run = seed_completed_run(storage)
    broker = CommitteeBroker(storage=storage)

    state = await broker.start_meeting(
        run.id,
        topic="  AAPL 투자위원회  ",
        max_turns=8,
    )

    assert state.topic == "AAPL 투자위원회"
    assert state.status is CommitteeStatus.RUNNING
    assert [turn.role for turn in state.turns] == list(COMMITTEE_ROLES)
    assert all(turn.status is CommitteeTurnStatus.COMPLETED for turn in state.turns)
    shared = next(
        entry
        for entry in state.claim_ledger
        if entry.text == "서비스 매출이 현금흐름 안정성을 높인다."
    )
    assert shared.roles == [AgentRole.FUNDAMENTAL, AgentRole.TECHNICAL]
    assert shared.evidence_status == "cited"
    assert broker.get_state(state.session_id) == state
    assert broker.get_active_state(run.id) is not None
    assert broker.get_latest_state(run.id) is not None

    with pytest.raises(CommitteeConflictError, match="이미 활성 회의"):
        await broker.start_meeting(run.id, topic="중복 회의")

    minutes = await broker.finalize_meeting(run.id)

    assert minutes.status is CommitteeStatus.COMPLETED
    assert minutes.total_turns == 6
    assert minutes.chairman_summary == "head_trader 기존 분석 발언"
    assert minutes.bull_case == "bull 기존 분석 발언"
    assert minutes.bear_case == "bear 기존 분석 발언"
    assert minutes.human_approval_required is True
    assert minutes.auto_trade is False
    assert broker.is_active(run.id) is False
    final_state = broker.get_state(state.session_id)
    assert final_state is not None
    assert final_state.status is CommitteeStatus.COMPLETED
    assert broker.get_minutes(state.session_id) == minutes
    snapshots = storage.list_snapshots(run.id, kind=SnapshotKind.AGENT_STATE)
    assert snapshots[0].checksum is not None
    minutes_payload = snapshots[0].data["minutes"]
    assert isinstance(minutes_payload, dict)
    assert minutes_payload["generation_method"] == "deterministic_claim_ledger_v1"
    actions = [
        event.payload["committee_action"]
        for event in storage.list_events(analysis_run_id=run.id)
    ]
    assert actions == ["committee_started", "committee_finished"]
    assert storage.list_human_reviews(run.id) == []

    restarted = CommitteeBroker(storage=storage)
    recovered_state = restarted.get_state(state.session_id)
    recovered_minutes = restarted.get_minutes(state.session_id)
    assert recovered_state is not None
    assert recovered_state.status is CommitteeStatus.COMPLETED
    assert recovered_minutes == minutes
    latest_reader = CommitteeBroker(storage=storage)
    latest_state = latest_reader.get_latest_state(run.id)
    assert latest_state is not None
    assert latest_state.session_id == state.session_id
    assert latest_state.status is CommitteeStatus.COMPLETED


@pytest.mark.asyncio
async def test_running_meeting_can_resume_from_snapshot_after_restart() -> None:
    storage = InMemoryStorage()
    run = seed_completed_run(storage, include_roles=(AgentRole.BULL, AgentRole.BEAR))
    original = CommitteeBroker(storage=storage)
    state = await original.start_meeting(
        run.id,
        topic="재시작 복구 회의",
        roles=[AgentRole.BULL, AgentRole.BEAR],
        max_turns=4,
    )

    restarted = CommitteeBroker(storage=storage)
    recovered = restarted.get_latest_state(run.id)

    assert recovered is not None
    assert recovered.session_id == state.session_id
    assert restarted.is_active(run.id) is True
    minutes = await restarted.finalize_meeting(run.id)
    assert minutes.status is CommitteeStatus.COMPLETED
    assert minutes.total_turns == 2


@pytest.mark.asyncio
async def test_directed_speak_calls_only_selected_role_and_respects_turn_cap() -> None:
    storage = InMemoryStorage()
    run = seed_completed_run(storage, include_roles=(AgentRole.FUNDAMENTAL,))
    provider = FakeProvider()
    broker = CommitteeBroker(storage=storage, provider=provider)
    await broker.start_meeting(
        run.id,
        topic="추가 근거 확인",
        roles=[AgentRole.FUNDAMENTAL],
        max_turns=2,
    )

    turn = await broker.directed_speak(
        run.id,
        AgentRole.FUNDAMENTAL,
        "현금흐름 근거를 다시 확인해줘.",
    )

    assert turn.sequence == 2
    assert turn.status is CommitteeTurnStatus.COMPLETED
    assert len(provider.calls) == 1
    assert provider.calls[0]["role"] == "fundamental"
    assert provider.calls[0]["snapshot"]["close"] == 215.0
    assert provider.calls[0]["context"][-1] == {
        "committee_directed_request": {
            "prompt": "현금흐름 근거를 다시 확인해줘.",
            "scope": "analysis_focus_only",
        }
    }
    saved = storage.list_agent_outputs(run.id, role=AgentRole.FUNDAMENTAL)
    assert len(saved) == 2
    committee_payload = saved[-1].data["committee"]
    assert isinstance(committee_payload, dict)
    assert committee_payload["source"] == "directed_speak"

    with pytest.raises(CommitteeValidationError, match="최대 발언"):
        await broker.directed_speak(run.id, AgentRole.FUNDAMENTAL, "한 번 더 말해줘.")


@pytest.mark.asyncio
async def test_directed_speak_failure_is_preserved_in_output_and_minutes() -> None:
    storage = InMemoryStorage()
    run = seed_completed_run(storage, include_roles=(AgentRole.NEWS,))
    provider = FakeProvider(error=RuntimeError("provider unavailable"))
    broker = CommitteeBroker(storage=storage, provider=provider)
    state = await broker.start_meeting(
        run.id,
        topic="뉴스 리스크 확인",
        roles=[AgentRole.NEWS],
        max_turns=2,
    )

    with pytest.raises(CommitteeAgentError, match="provider unavailable"):
        await broker.directed_speak(run.id, AgentRole.NEWS, "최신 근거를 재검토해줘.")

    active = broker.get_state(state.session_id)
    assert active is not None
    assert active.turns[-1].status is CommitteeTurnStatus.FAILED
    failed = storage.list_agent_outputs(
        run.id,
        role=AgentRole.NEWS,
        status=AgentOutputStatus.FAILED,
    )
    assert len(failed) == 1
    assert failed[0].error_message == "provider unavailable"

    minutes = await broker.finalize_meeting(run.id)
    assert minutes.failures == ["news: provider unavailable"]
    assert minutes.total_turns == 2


@pytest.mark.asyncio
async def test_stop_preserves_partial_minutes_and_final_session_lookup() -> None:
    storage = InMemoryStorage()
    run = seed_completed_run(storage, include_roles=(AgentRole.BULL, AgentRole.BEAR))
    broker = CommitteeBroker(storage=storage)
    state = await broker.start_meeting(
        run.id,
        topic="강세와 약세 비교",
        roles=[AgentRole.BULL, AgentRole.BEAR],
        max_turns=4,
    )

    minutes = await broker.stop_meeting(run.id, "사람이 추가 자료를 요청했다.")

    assert minutes.status is CommitteeStatus.STOPPED
    assert minutes.stop_reason == "사람이 추가 자료를 요청했다."
    assert minutes.total_turns == 2
    assert broker.is_active(run.id) is False
    final_state = broker.get_state(state.session_id)
    assert final_state is not None
    assert final_state.status is CommitteeStatus.STOPPED
    assert final_state.stop_requested is True
    with pytest.raises(CommitteeNotFoundError):
        await broker.stop_meeting(run.id, "이미 끝난 회의")


@pytest.mark.asyncio
async def test_topic_role_instruction_and_run_state_are_validated() -> None:
    storage = InMemoryStorage()
    run = seed_completed_run(storage, include_roles=(AgentRole.FUNDAMENTAL,))
    broker = CommitteeBroker(storage=storage, provider=FakeProvider())

    with pytest.raises(CommitteeValidationError, match="topic"):
        await broker.start_meeting(run.id, topic=" ")
    with pytest.raises(CommitteeValidationError, match="topic"):
        await broker.start_meeting(run.id, topic="x" * 501)
    with pytest.raises(CommitteeValidationError, match="지원하지 않는"):
        await broker.start_meeting(
            run.id,
            topic="잘못된 역할",
            roles=[AgentRole.RISK_MANAGER],
        )
    with pytest.raises(CommitteeValidationError, match="중복"):
        await broker.start_meeting(
            run.id,
            topic="중복 역할",
            roles=[AgentRole.FUNDAMENTAL, AgentRole.FUNDAMENTAL],
        )
    with pytest.raises(CommitteeValidationError, match="max_turns"):
        await broker.start_meeting(
            run.id,
            topic="턴 부족",
            roles=[AgentRole.FUNDAMENTAL, AgentRole.TECHNICAL],
            max_turns=1,
        )

    await broker.start_meeting(
        run.id,
        topic="입력 검증",
        roles=[AgentRole.FUNDAMENTAL],
        max_turns=2,
    )
    with pytest.raises(CommitteeValidationError, match="instruction"):
        await broker.directed_speak(run.id, AgentRole.FUNDAMENTAL, " ")
    with pytest.raises(CommitteeValidationError, match="instruction"):
        await broker.directed_speak(run.id, AgentRole.FUNDAMENTAL, "x" * 2_001)

    candidate = storage.save_candidate(Candidate(ticker="MSFT"))
    queued = storage.save_analysis_run(AnalysisRun(candidate_id=candidate.id))
    with pytest.raises(CommitteeValidationError, match="완료된 분석"):
        await CommitteeBroker(storage=storage).start_meeting(queued.id, topic="대기 실행")
