# 투자위원회의 단계별 에이전트 실행과 사람 검토 상태 전이를 검증한다.
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from pydantic import AnyHttpUrl, BaseModel

from investment_office.domain import (
    AgentOutput,
    AgentOutputStatus,
    AgentRole,
    AnalysisRunStatus,
    CandidateStatus,
    Event,
    EventType,
    ReviewDecision,
    Snapshot,
    SnapshotKind,
)
from investment_office.services.event_broker import EventBroker
from investment_office.services.market_data import YahooFinanceClient
from investment_office.services.market_regime import (
    MarketRegime,
    MarketRegimeAssessment,
    RegimeState,
)
from investment_office.services.orchestrator import (
    DISCOVERY_ANALYSIS_THESIS,
    AnalysisProvider,
    AnalysisRunConflictError,
    ConcurrencyLimitedAnalysisProvider,
    InvestmentCommittee,
    ResearchDataClient,
    RiskFunction,
)
from investment_office.services.research_contracts import (
    AnalysisInputBundle,
    DataQualityReport,
    Fact,
    InstrumentRef,
    ResearchSection,
    SectionStatus,
    SourceRef,
    SourceTier,
)
from investment_office.services.research_pipeline import ResearchPipelineResult
from investment_office.storage import InMemoryStorage


class FakeSnapshot(BaseModel):
    ticker: str = "AAPL"
    exchange: str = "NMS"
    as_of: str = "2026-07-10"
    close: float = 215.0
    previous_close: float = 212.0
    currency: str = "USD"
    source_url: str = "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"


class FakeRiskResult(BaseModel):
    action: str = "size_position"
    eligible: bool = True
    position_cap_pct: float = 4.0
    warnings: list[str] = ["실적 발표 전후 변동성을 다시 확인한다."]


class FakeMarketData:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.requested_tickers: list[str] = []

    async def fetch_eod_snapshot(self, ticker: str) -> FakeSnapshot:
        self.requested_tickers.append(ticker)
        if self.error is not None:
            raise self.error
        return FakeSnapshot(ticker=ticker)


class BlockingMarketData(FakeMarketData):
    def __init__(self, expected_parallel: int) -> None:
        super().__init__()
        self.expected_parallel = expected_parallel
        self.active = 0
        self.max_active = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def fetch_eod_snapshot(self, ticker: str) -> FakeSnapshot:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if self.active >= self.expected_parallel:
            self.started.set()
        try:
            await self.release.wait()
            return await super().fetch_eod_snapshot(ticker)
        finally:
            self.active -= 1


class FakeResearchData:
    def __init__(self) -> None:
        self.calls: list[InstrumentRef] = []

    async def collect(
        self,
        instrument: InstrumentRef,
        snapshot: Any,
    ) -> ResearchPipelineResult:
        self.calls.append(instrument)
        collected_at = datetime(2026, 7, 12, 9, 30, tzinfo=UTC)
        observed_at = datetime(2026, 7, 10, tzinfo=UTC)
        source = SourceRef(
            source_id="test:research:source",
            name="고정 연구 자료",
            tier=SourceTier.FALLBACK,
            url=AnyHttpUrl(snapshot.source_url),
            retrieved_at=collected_at,
        )
        facts = tuple(
            Fact(
                fact_id=fact_id,
                source_id=source.source_id,
                metric=metric,
                value=value,
                unit=unit,
                observed_at=observed_at,
                published_at=observed_at,
                collected_at=collected_at,
                instrument=instrument,
            )
            for fact_id, metric, value, unit in (
                ("test:fundamental:revenue", "매출", 100.0, "currency"),
                ("test:news:filing", "공시", "10-Q", "form"),
                ("test:macro:vix", "VIX 종가", 17.0, "index_point"),
            )
        )
        sections = tuple(
            ResearchSection(
                section_id=section_id,
                title=title,
                status=SectionStatus.COMPLETE,
                fact_ids=(fact.fact_id,),
            )
            for section_id, title, fact in (
                ("company.fundamental", "공식 재무", facts[0]),
                ("company.official_news", "공식 공시", facts[1]),
                ("macro.volatility", "시장 변동성", facts[2]),
            )
        )
        quality = DataQualityReport(
            generated_at=collected_at,
            analysis_eligible=True,
        )
        bundle = AnalysisInputBundle(
            cutoff=collected_at,
            market_session=date(2026, 7, 10),
            instrument=instrument,
            sources=(source,),
            facts=facts,
            sections=sections,
            quality=quality,
        )
        regime = MarketRegimeAssessment(
            market=instrument.market,
            regime=MarketRegime(
                rates=RegimeState.NEUTRAL,
                currency=RegimeState.NEUTRAL,
                volatility=RegimeState.NEUTRAL,
                commodities=RegimeState.NEUTRAL,
                liquidity=RegimeState.NEUTRAL,
            ),
            confidence=1,
            evidence_fact_ids=(facts[2].fact_id,),
            warnings=(),
            position_cap_multiplier=0.5,
        )

        def agent_fact(fact: Fact) -> dict[str, object]:
            payload = cast(dict[str, object], fact.model_dump(mode="json"))
            payload["source_url"] = str(source.url)
            return payload

        return ResearchPipelineResult(
            bundle=bundle,
            regime=regime,
            fundamentals=[agent_fact(facts[0])],
            news=[agent_fact(facts[1])],
            macro=[agent_fact(facts[2])],
            observation_cutoff=collected_at,
        )


class FakeProvider:
    def __init__(self, *, fail_role: str | None = None) -> None:
        self.fail_role = fail_role
        self.calls: list[tuple[str, str, int]] = []

    async def analyze(
        self,
        role: str,
        ticker: str,
        snapshot: dict[str, Any],
        context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self.calls.append((role, ticker, len(context)))
        if role == self.fail_role:
            raise RuntimeError(f"{role} 분석 실패")
        stance = "bullish" if role in {"bull", "head_trader"} else "neutral"
        bundle = snapshot.get("research_bundle")
        facts = bundle.get("facts", []) if isinstance(bundle, dict) else []
        evidence = (
            [
                {
                    "fact_id": facts[0]["fact_id"],
                    "claim": "모델이 임의로 만든 근거 문장",
                    "source_url": "https://attacker.invalid/forged",
                    "published_at": "2099-01-01T00:00:00Z",
                }
            ]
            if facts
            else []
        )
        return {
            "role": role,
            "ticker": ticker,
            "stance": stance,
            "confidence": 0.76,
            "summary": f"{role} 역할의 검증 가능한 요약",
            "key_points": ["입력 스냅샷만 사용했다."],
            "evidence": evidence,
            "risks": ["제공된 데이터 범위가 제한적이다."],
            "recommendation": "사람의 최종 확인 후 조건부로 판단한다.",
            "data_gaps": [],
            "invalidations": ["입력 가격 조건이 바뀌면 재검토한다."],
        }


class BlockingProvider(FakeProvider):
    def __init__(self, expected_parallel: int) -> None:
        super().__init__()
        self.expected_parallel = expected_parallel
        self.active = 0
        self.max_active = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def analyze(
        self,
        role: str,
        ticker: str,
        snapshot: dict[str, Any],
        context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if self.active >= self.expected_parallel:
            self.started.set()
        try:
            await self.release.wait()
            return await super().analyze(role, ticker, snapshot, context)
        finally:
            self.active -= 1


def fake_risk(snapshot: FakeSnapshot, chairman: dict[str, Any]) -> FakeRiskResult:
    assert snapshot.ticker == chairman["ticker"]
    return FakeRiskResult()


def blocked_risk(snapshot: FakeSnapshot, chairman: dict[str, Any]) -> FakeRiskResult:
    assert snapshot.ticker == chairman["ticker"]
    return FakeRiskResult(action="avoid", eligible=False, position_cap_pct=0.0)


class SiblingFailureProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.bear_started = asyncio.Event()
        self.bear_cancelled = False

    async def analyze(
        self,
        role: str,
        ticker: str,
        snapshot: dict[str, Any],
        context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if role == "bull":
            await self.bear_started.wait()
            raise RuntimeError("bull 분석 실패")
        if role == "bear":
            self.bear_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.bear_cancelled = True
                raise
        return await super().analyze(role, ticker, snapshot, context)


class EventFailingStorage(InMemoryStorage):
    def append_event(self, event: Event) -> Event:
        del event
        raise RuntimeError("이벤트 저장 실패")


def make_committee(
    *,
    provider: FakeProvider | None = None,
    market_data: FakeMarketData | None = None,
    storage: InMemoryStorage | None = None,
    risk_function: RiskFunction | None = None,
    research_data: FakeResearchData | None = None,
    max_parallel_agents: int = 3,
) -> tuple[InvestmentCommittee, InMemoryStorage, FakeProvider, FakeMarketData]:
    resolved_storage = storage or InMemoryStorage()
    resolved_provider = provider or FakeProvider()
    resolved_market = market_data or FakeMarketData()
    committee = InvestmentCommittee(
        storage=resolved_storage,
        provider=cast(AnalysisProvider, resolved_provider),
        market_data=cast(YahooFinanceClient, resolved_market),
        broker=EventBroker(),
        max_parallel_agents=max_parallel_agents,
        risk_function=risk_function or cast(RiskFunction, fake_risk),
        research_data=cast(ResearchDataClient, research_data) if research_data else None,
    )
    return committee, resolved_storage, resolved_provider, resolved_market


@pytest.mark.asyncio
async def test_model_provider_wrapper_enforces_shared_parallel_limit() -> None:
    provider = BlockingProvider(expected_parallel=2)
    limited = ConcurrencyLimitedAnalysisProvider(provider, asyncio.Semaphore(2))
    calls = [
        asyncio.create_task(
            limited.analyze(
                "technical",
                f"T{index}",
                {"source_url": "https://example.com/market"},
                [],
            )
        )
        for index in range(5)
    ]

    await asyncio.wait_for(provider.started.wait(), timeout=1)
    await asyncio.sleep(0.02)

    assert provider.max_active == 2
    provider.release.set()
    await asyncio.wait_for(asyncio.gather(*calls), timeout=2)


@pytest.mark.asyncio
async def test_analysis_run_limit_caps_parallel_price_and_research_entry() -> None:
    market = BlockingMarketData(expected_parallel=2)
    committee, _, _, _ = make_committee(
        market_data=market,
        max_parallel_agents=2,
    )
    runs = [await committee.create_analysis(f"T{index}") for index in range(5)]
    tasks = [asyncio.create_task(committee.run_analysis(run.id)) for run in runs]

    await asyncio.wait_for(market.started.wait(), timeout=1)
    await asyncio.sleep(0.02)

    assert market.max_active == 2
    market.release.set()
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=3)
    assert len(market.requested_tickers) == len(runs)


@pytest.mark.asyncio
async def test_analysis_workflow_metadata_is_stored_and_exposed() -> None:
    committee, _, _, _ = make_committee()

    manual = await committee.create_analysis("AAPL")
    batch_id = str(uuid4())
    discovery = await committee.create_analysis(
        "MSFT",
        DISCOVERY_ANALYSIS_THESIS,
        workflow="discovery",
        discovery_batch_id=batch_id,
    )

    assert manual.configuration["workflow"] == "manual"
    assert committee.build_run_payload(manual.id)["workflow"] == "manual"
    assert committee.build_run_payload(manual.id)["discovery_batch_id"] is None
    assert discovery.configuration["workflow"] == "discovery"
    assert discovery.configuration["discovery_batch_id"] == batch_id
    assert committee.build_run_payload(discovery.id)["workflow"] == "discovery"
    assert committee.build_run_payload(discovery.id)["discovery_batch_id"] == batch_id


@pytest.mark.asyncio
async def test_create_korean_analysis_persists_market_identity_without_schema_change() -> None:
    committee, storage, _, _ = make_committee()

    run = await committee.create_analysis("005930", market="kr")

    candidate = storage.get_candidate(run.candidate_id)
    assert candidate is not None
    assert candidate.ticker == "KR-005930"
    assert candidate.attributes == {
        "market": "kr",
        "local_symbol": "005930",
        "canonical_id": "kr:005930",
        "currency": "KRW",
        "data_contract_version": "1.0",
    }
    assert run.configuration["market"] == "kr"
    payload = committee.build_run_payload(run.id)
    assert payload["ticker"] == "005930"
    assert payload["market"] == "kr"
    assert payload["canonical_id"] == "kr:005930"


@pytest.mark.asyncio
async def test_legacy_workflow_inference_is_conservative() -> None:
    committee, storage, _, _ = make_committee()

    discovery = await committee.create_analysis("AAPL", DISCOVERY_ANALYSIS_THESIS)
    discovery.configuration.pop("workflow")
    storage.save_analysis_run(discovery)

    scheduled = await committee.create_analysis("MSFT", "예약 분석 가설")
    scheduled.configuration.pop("workflow")
    storage.save_analysis_run(scheduled)
    storage.save_snapshot(
        Snapshot(
            candidate_id=scheduled.candidate_id,
            analysis_run_id=scheduled.id,
            kind=SnapshotKind.AGENT_STATE,
            data={"record_type": "scheduled_analysis"},
        )
    )

    unknown = await committee.create_analysis("NVDA", "일반 분석 가설")
    unknown.configuration.pop("workflow")
    storage.save_analysis_run(unknown)

    assert committee.build_run_payload(discovery.id)["workflow"] == "discovery"
    assert committee.build_run_payload(scheduled.id)["workflow"] == "scheduled"
    assert committee.build_run_payload(unknown.id)["workflow"] == "unknown"


@pytest.mark.parametrize(
    ("decision", "payload_status", "candidate_status"),
    [
        (ReviewDecision.APPROVED, "approved", CandidateStatus.APPROVED),
        (ReviewDecision.DEFERRED, "hold", CandidateStatus.READY_FOR_REVIEW),
        (ReviewDecision.REJECTED, "rejected", CandidateStatus.REJECTED),
    ],
)
@pytest.mark.asyncio
async def test_six_agent_analysis_then_human_review_state(
    decision: ReviewDecision,
    payload_status: str,
    candidate_status: CandidateStatus,
) -> None:
    committee, storage, provider, market = make_committee()

    run = await committee.create_analysis(" aapl ", "서비스 매출의 지속성을 검토한다.")
    await committee.run_analysis(run.id)

    completed = storage.get_analysis_run(run.id)
    assert completed is not None
    assert completed.status is AnalysisRunStatus.COMPLETED
    assert market.requested_tickers == ["AAPL"]
    assert {role for role, _, _ in provider.calls} == {
        "technical",
        "bull",
        "bear",
        "head_trader",
    }
    assert {role: context_size for role, _, context_size in provider.calls} == {
        "technical": 0,
        "bull": 3,
        "bear": 3,
        "head_trader": 5,
    }
    outputs = storage.list_agent_outputs(run.id)
    assert len(outputs) == 7
    assert {output.role for output in outputs} == {
        AgentRole.FUNDAMENTAL,
        AgentRole.TECHNICAL,
        AgentRole.NEWS,
        AgentRole.BULL,
        AgentRole.BEAR,
        AgentRole.HEAD_TRADER,
        AgentRole.RISK_MANAGER,
    }
    outputs_by_role = {output.role: output for output in outputs}
    assert outputs_by_role[AgentRole.TECHNICAL].evidence == []
    for role in (AgentRole.FUNDAMENTAL, AgentRole.NEWS):
        output = outputs_by_role[role]
        assert output.confidence == 0.0
        assert output.evidence == []
        assert output.data["stance"] == "neutral"
        assert output.data["data_gaps"]
    draft = committee.build_run_payload(run.id)
    assert draft["status"] == "review"
    assert draft["progress"] == 100
    assert len(draft["agents"]) == 6
    assert draft["decision"]["human_approval_required"] is True
    assert draft["decision"]["auto_trade"] is False
    assert draft["decision"]["risk_eligible"] is False
    assert draft["decision"]["position_cap_pct"] == 0.0

    review = await committee.record_review(run.id, decision, "리스크 조건을 확인해 기록한다.")

    assert review.decision is decision
    assert storage.list_human_reviews(run.id) == [review]
    candidate = storage.get_candidate(completed.candidate_id)
    assert candidate is not None
    assert candidate.status is candidate_status
    reviewed = committee.build_run_payload(run.id)
    assert reviewed["status"] == payload_status
    assert reviewed["human_review"]["decision"] == decision.value
    last_event = storage.list_events(analysis_run_id=run.id)[-1]
    assert last_event.event_type is EventType.HUMAN_REVIEW_RECORDED


@pytest.mark.asyncio
async def test_research_bundle_runs_all_roles_and_applies_regime_cap() -> None:
    research = FakeResearchData()
    committee, storage, provider, _ = make_committee(research_data=research)
    run = await committee.create_analysis("AAPL")

    await committee.run_analysis(run.id)

    assert [item.symbol for item in research.calls] == ["AAPL"]
    assert {role for role, _, _ in provider.calls} == {
        "fundamental",
        "technical",
        "news",
        "bull",
        "bear",
        "head_trader",
    }
    market_snapshot = storage.list_snapshots(run.id, kind=SnapshotKind.MARKET_DATA)[0]
    assert market_snapshot.data["research_quality"]["analysis_eligible"] is True
    outputs = storage.list_agent_outputs(run.id)
    model_outputs = [output for output in outputs if output.role is not AgentRole.RISK_MANAGER]
    assert model_outputs
    for output in model_outputs:
        assert output.evidence[0].fact_id == "test:fundamental:revenue"
        assert output.evidence[0].title == "매출=100.0 currency"
        assert str(output.evidence[0].url) == (
            "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"
        )
        assert "임의로 만든" not in output.data["evidence"][0]["claim"]
        assert "attacker.invalid" not in output.data["evidence"][0]["source_url"]
    decision = committee.build_run_payload(run.id)["decision"]
    assert decision["risk_eligible"] is True
    assert decision["position_cap_pct"] == 2.0
    assert decision["market_regime"]["position_cap_multiplier"] == 0.5
    assert decision["research_quality"]["analysis_eligible"] is True


def test_research_quality_gate_blocks_positive_risk_result() -> None:
    risk = {
        "action": "size_position",
        "eligible": True,
        "position_cap_pct": 4.0,
        "warnings": [],
        "data_gaps": [],
    }
    snapshot = {
        "research_quality": {
            "analysis_eligible": False,
            "blocking_reasons": ["공식 재무제표가 없습니다."],
            "warnings": ["독립 뉴스 공급원이 없습니다."],
        },
        "market_regime": {
            "position_cap_multiplier": 0.5,
            "warnings": ["변동성 축을 확인할 수 없습니다."],
        },
    }

    gated = InvestmentCommittee._apply_research_risk_gates(risk, snapshot)

    assert gated["action"] == "watch"
    assert gated["eligible"] is False
    assert gated["position_cap_pct"] == 0.0
    assert gated["data_gaps"] == ["공식 재무제표가 없습니다."]
    assert "연구 자료 품질 게이트가 신규 포지션을 차단했습니다." in gated["warnings"]


@pytest.mark.asyncio
async def test_missing_required_research_blocks_when_chairman_clears_gaps() -> None:
    committee, storage, _, _ = make_committee()
    run = await committee.create_analysis("AAPL")

    await committee.run_analysis(run.id)

    outputs = {output.role: output for output in storage.list_agent_outputs(run.id)}
    assert outputs[AgentRole.HEAD_TRADER].data["data_gaps"] == []
    expected_gaps = [
        "검증 가능한 재무·공시 원문과 출처가 입력되지 않았습니다.",
        "검증 가능한 뉴스 원문과 출처가 입력되지 않았습니다.",
    ]
    risk = outputs[AgentRole.RISK_MANAGER].data
    assert risk["data_gaps"] == expected_gaps
    assert risk["eligible"] is False
    assert risk["position_cap_pct"] == 0.0
    assert "필수 분석 자료(재무·공시, 뉴스)가 없어 신규 포지션을 차단합니다." in risk[
        "warnings"
    ]

    decision = committee.build_run_payload(run.id)["decision"]
    assert decision["data_gaps"] == expected_gaps
    assert decision["recommendation"] == "hold and watch"
    assert decision["risk_eligible"] is False
    assert decision["position_cap_pct"] == 0.0


@pytest.mark.asyncio
async def test_agent_failure_is_persisted_without_reviewable_decision() -> None:
    committee, storage, _, _ = make_committee(provider=FakeProvider(fail_role="technical"))
    run = await committee.create_analysis("MSFT")

    await committee.run_analysis(run.id)

    failed = storage.get_analysis_run(run.id)
    assert failed is not None
    assert failed.status is AnalysisRunStatus.FAILED
    assert failed.error_message == "technical 분석 실패"
    candidate = storage.get_candidate(failed.candidate_id)
    assert candidate is not None
    assert candidate.status is CandidateStatus.QUEUED
    payload = committee.build_run_payload(run.id)
    assert payload["status"] == "failed"
    assert payload["decision"] is None
    assert any(
        event.event_type is EventType.ANALYSIS_FAILED
        for event in storage.list_events(analysis_run_id=run.id)
    )

    with pytest.raises(ValueError, match="완료된 분석만"):
        await committee.record_review(
            run.id,
            ReviewDecision.APPROVED,
            "실패한 분석은 승인하지 않는다.",
        )


@pytest.mark.asyncio
async def test_risk_block_overrides_bullish_chairman_recommendation() -> None:
    committee, storage, _, _ = make_committee(
        risk_function=cast(RiskFunction, blocked_risk),
    )
    run = await committee.create_analysis("NVDA")

    await committee.run_analysis(run.id)

    decision = committee.build_run_payload(run.id)["decision"]
    assert decision["recommendation"] == "avoid"
    assert decision["risk_eligible"] is False
    assert decision["position_cap_pct"] == 0.0
    assert "위험 정책이 신규 포지션을 허용하지 않습니다." in decision["risks"]


@pytest.mark.asyncio
async def test_stage_failure_cancels_and_persists_sibling_agent() -> None:
    provider = SiblingFailureProvider()
    committee, storage, _, _ = make_committee(provider=provider)
    run = await committee.create_analysis("AMD")

    await committee.run_analysis(run.id)

    assert provider.bear_cancelled is True
    outputs = {output.role: output for output in storage.list_agent_outputs(run.id)}
    assert outputs[AgentRole.BULL].status is AgentOutputStatus.FAILED
    assert outputs[AgentRole.BEAR].status is AgentOutputStatus.FAILED
    assert outputs[AgentRole.BEAR].error_message == "에이전트 실행 태스크가 취소되었습니다."
    await asyncio.sleep(0)
    refreshed = {output.role: output for output in storage.list_agent_outputs(run.id)}
    assert refreshed[AgentRole.BEAR].status is AgentOutputStatus.FAILED
    assert AgentRole.HEAD_TRADER not in refreshed


@pytest.mark.asyncio
async def test_event_failure_does_not_leave_analysis_in_inconsistent_state() -> None:
    storage = EventFailingStorage()
    committee, _, _, _ = make_committee(storage=storage)
    run = await committee.create_analysis("GOOG")

    await committee.run_analysis(run.id)

    completed = storage.get_analysis_run(run.id)
    assert completed is not None
    assert completed.status is AnalysisRunStatus.COMPLETED
    assert committee.build_run_payload(run.id)["decision"] is not None
    assert storage.list_events(analysis_run_id=run.id) == []


@pytest.mark.asyncio
async def test_restart_recovery_marks_running_run_and_agent_output_failed() -> None:
    committee, storage, _, _ = make_committee()
    run = await committee.create_analysis("META")
    stored_run = storage.get_analysis_run(run.id)
    candidate = storage.get_candidate(run.candidate_id)
    assert stored_run is not None
    assert candidate is not None
    stored_run.status = AnalysisRunStatus.RUNNING
    stored_run.started_at = stored_run.requested_at
    candidate.status = CandidateStatus.ANALYZING
    storage.save_analysis_run(stored_run)
    storage.save_candidate(candidate)
    output = AgentOutput(
        analysis_run_id=run.id,
        role=AgentRole.NEWS,
        status=AgentOutputStatus.RUNNING,
    )
    storage.save_agent_output(output)

    recovered = await committee.recover_interrupted_runs()

    assert [item.id for item in recovered] == [run.id]
    failed = storage.get_analysis_run(run.id)
    assert failed is not None
    assert failed.status is AnalysisRunStatus.FAILED
    assert "서버 재시작" in (failed.error_message or "")
    failed_candidate = storage.get_candidate(run.candidate_id)
    assert failed_candidate is not None
    assert failed_candidate.status is CandidateStatus.QUEUED
    failed_output = storage.list_agent_outputs(run.id)[0]
    assert failed_output.status is AgentOutputStatus.FAILED
    assert "서버 재시작" in (failed_output.error_message or "")


@pytest.mark.asyncio
async def test_analysis_cannot_start_twice() -> None:
    committee, storage, _, _ = make_committee()
    run = await committee.create_analysis("AAPL")
    stored_run = storage.get_analysis_run(run.id)
    assert stored_run is not None
    stored_run.status = AnalysisRunStatus.RUNNING
    stored_run.started_at = stored_run.requested_at
    storage.save_analysis_run(stored_run)

    with pytest.raises(AnalysisRunConflictError, match="대기 중인 분석만"):
        await committee.run_analysis(run.id)
