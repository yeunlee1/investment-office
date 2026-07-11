# 외부 서비스 없이 분석·조회·검토·SSE API의 핵심 계약을 검증한다.
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.types import Message, Scope

from investment_office.config import Settings
from investment_office.domain import (
    AnalysisRun,
    AnalysisRunStatus,
    CandidateStatus,
    Snapshot,
    SnapshotKind,
)
from investment_office.main import _log_background_task_failure, create_app
from investment_office.services.market_data import YahooFinanceClient
from investment_office.services.market_overview import MarketOverviewService
from investment_office.services.orchestrator import AnalysisProvider, RiskFunction
from investment_office.storage import InMemoryStorage


class FakeSnapshot(BaseModel):
    ticker: str = "AAPL"
    as_of: str = "2026-07-10"
    exchange: str = "NMS"
    timezone: str = "America/New_York"
    as_of_date: date = date(2026, 7, 10)
    fetched_at: datetime = datetime(2026, 7, 11, tzinfo=UTC)
    observations: int = 252
    close: float = 215.0
    current_close: float = 215.0
    previous_close: float = 212.0
    return_1d_pct: float = 1.42
    return_5d_pct: float = 3.2
    return_20d_pct: float = 7.5
    return_60d_pct: float = 14.0
    sma_20: float = 205.0
    sma_50: float = 198.0
    sma_200: float = 180.0
    rsi_14: float = 62.0
    atr_14: float = 4.2
    volatility_20d_pct: float = 28.0
    high_52_week: float = 230.0
    low_52_week: float = 150.0
    average_volume_20d: float = 25_000_000
    data_gaps: list[str] = []
    currency: str = "USD"
    source_url: str = "https://query1.finance.yahoo.com/v8/finance/chart/AAPL"


class FakeRiskResult(BaseModel):
    action: str = "size_position"
    eligible: bool = True
    position_cap_pct: float = 3.0
    warnings: list[str] = ["최종 주문은 사람이 별도로 판단한다."]


class FakeOverviewResult(BaseModel):
    generated_at: datetime = datetime(2026, 7, 12, tzinfo=UTC)
    common: dict[str, Any] = {
        "status": "ready",
        "facts": [],
        "sections": [],
        "warnings": [],
    }
    markets: dict[str, Any] = {
        market: {
            "market": market,
            "label": label,
            "regime": {
                "rates": "unknown",
                "currency": "unknown",
                "volatility": "unknown",
                "commodities": "unknown",
                "liquidity": "unknown",
            },
            "confidence": 0,
            "position_cap_multiplier": 0.25,
            "warnings": [],
            "data_quality": {
                "analysis_eligible": False,
                "blocking_reasons": ["고정 시험 자료입니다."],
                "warnings": [],
                "stale_fact_ids": [],
                "blocked_section_ids": [],
            },
        }
        for market, label in (("us", "미국 시장"), ("kr", "한국 시장"))
    }


class FakeMarketOverviewService:
    async def build(self) -> FakeOverviewResult:
        return FakeOverviewResult()


class FakeMarketData:
    def __init__(self) -> None:
        self.closed = False

    async def fetch_eod_snapshot(self, ticker: str) -> FakeSnapshot:
        return FakeSnapshot(ticker=ticker)

    async def aclose(self) -> None:
        self.closed = True


class FlakyScheduleStorage(InMemoryStorage):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_run_lookup = False
        self.fail_next_schedule_snapshot = False

    def get_analysis_run(self, run_id: UUID) -> AnalysisRun | None:
        if self.fail_next_run_lookup:
            self.fail_next_run_lookup = False
            raise RuntimeError("temporary storage outage")
        return super().get_analysis_run(run_id)

    def save_snapshot(self, snapshot: Snapshot) -> Snapshot:
        if (
            self.fail_next_schedule_snapshot
            and snapshot.kind is SnapshotKind.AGENT_STATE
            and snapshot.data.get("record_type") == "scheduled_analysis"
        ):
            self.fail_next_schedule_snapshot = False
            raise RuntimeError("temporary schedule storage outage")
        return super().save_snapshot(snapshot)


class FakeProvider:
    async def analyze(
        self,
        role: str,
        ticker: str,
        snapshot: dict[str, Any],
        context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        del context
        return {
            "role": role,
            "ticker": ticker,
            "stance": "bullish" if role == "head_trader" else "neutral",
            "confidence": 0.72,
            "summary": f"{role} 분석 요약",
            "key_points": ["주어진 스냅샷을 확인했다."],
            "evidence": [
                {
                    "claim": "시장 데이터 입력을 사용했다.",
                    "source_url": snapshot["source_url"],
                    "published_at": None,
                }
            ],
            "risks": ["데이터 범위가 제한적이다."],
            "recommendation": "사람 검토 전에는 주문하지 않는다.",
            "data_gaps": [],
            "invalidations": ["가격 조건이 바뀌면 재검토한다."],
        }


def fake_risk(snapshot: FakeSnapshot, chairman: dict[str, Any]) -> FakeRiskResult:
    assert snapshot.ticker == chairman["ticker"]
    return FakeRiskResult()


def make_app(*, storage: InMemoryStorage | None = None) -> tuple[FastAPI, FakeMarketData]:
    market = FakeMarketData()
    settings = Settings(database_url="mariadb+pymysql://unused:unused@127.0.0.1:3307/unused")
    app = create_app(
        settings=settings,
        storage=storage or InMemoryStorage(),
        provider=cast(AnalysisProvider, FakeProvider()),
        market_data=cast(YahooFinanceClient, market),
        market_overview_service=cast(
            MarketOverviewService,
            FakeMarketOverviewService(),
        ),
        risk_function=cast(RiskFunction, fake_risk),
    )
    return app, market


async def wait_for_status(
    client: httpx.AsyncClient,
    run_id: str,
    expected: str,
) -> dict[str, Any]:
    for _ in range(200):
        response = await client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200
        run = cast(dict[str, Any], response.json()["run"])
        if run["status"] == expected:
            return run
        await asyncio.sleep(0.01)
    raise AssertionError(f"run {run_id} did not reach {expected}")


@pytest.mark.asyncio
async def test_background_task_failure_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    async def fail() -> None:
        raise RuntimeError("백그라운드 검증 실패")

    task = asyncio.create_task(fail(), name="백그라운드-검증")
    await asyncio.sleep(0)

    with caplog.at_level(logging.ERROR, logger="investment_office.main"):
        _log_background_task_failure(task)

    assert "백그라운드-검증" in caplog.text
    assert "백그라운드 검증 실패" in caplog.text


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.0.10", "::1"])
def test_settings_reject_non_loopback_hosts(host: str) -> None:
    with pytest.raises(ValueError, match="127.0.0.1 또는 localhost"):
        Settings(
            host=host,
            database_url="mariadb+pymysql://unused:unused@127.0.0.1:3307/unused",
        )


@pytest.mark.asyncio
async def test_local_api_rejects_untrusted_hosts_and_cross_origin_mutations() -> None:
    app, _ = make_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1",
        ) as client:
            untrusted_host = await client.get(
                "/api/state",
                headers={"host": "attacker.invalid"},
            )
            assert untrusted_host.status_code == 400

            cross_origin = await client.post(
                "/api/analyze",
                headers={
                    "origin": "https://attacker.invalid",
                    "sec-fetch-site": "cross-site",
                },
                json={"ticker": "AAPL"},
            )
            assert cross_origin.status_code == 403
            assert "다른 출처" in cross_origin.json()["detail"]

            runs = await client.get("/api/runs")
            assert runs.json()["summary"]["total"] == 0

            same_origin = await client.post(
                "/api/analyze",
                headers={
                    "origin": "http://127.0.0.1",
                    "sec-fetch-site": "same-origin",
                },
                json={"ticker": "AAPL"},
            )
            assert same_origin.status_code == 202

        remote_transport = httpx.ASGITransport(
            app=app,
            client=("203.0.113.10", 51_234),
        )
        async with httpx.AsyncClient(
            transport=remote_transport,
            base_url="http://127.0.0.1",
        ) as remote_client:
            remote_response = await remote_client.get("/api/state")
            assert remote_response.status_code == 403
            assert "로컬 컴퓨터 밖" in remote_response.json()["detail"]


@pytest.mark.asyncio
async def test_analysis_api_returns_202_then_supports_query_and_single_review() -> None:
    app, market = make_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            response = await client.post(
                "/api/analyze",
                json={"ticker": " aapl ", "thesis": "서비스 매출을 검토한다."},
            )

            assert response.status_code == 202
            body = response.json()
            run_id = body["run_id"]
            UUID(run_id)
            assert body["run"]["ticker"] == "AAPL"
            assert body["run"]["status"] in {"queued", "running", "review"}

            completed = await wait_for_status(client, run_id, "review")
            assert completed["progress"] == 100
            assert len(completed["agents"]) == 6
            assert completed["decision"]["auto_trade"] is False

            review_payload = {
                "decision": "approved",
                "reason": "리스크 조건을 읽고 사람이 승인했다.",
            }
            reviewed = await client.post(f"/api/runs/{run_id}/review", json=review_payload)
            assert reviewed.status_code == 200
            assert reviewed.json()["run"]["status"] == "approved"
            assert reviewed.json()["review"]["decision"] == "approved"

            duplicate = await client.post(f"/api/runs/{run_id}/review", json=review_payload)
            assert duplicate.status_code == 409
            assert "이미 사람의 결정" in duplicate.json()["detail"]

            missing_id = uuid4()
            assert (await client.get(f"/api/runs/{missing_id}")).status_code == 404
            missing_review = await client.post(
                f"/api/runs/{missing_id}/review",
                json={"decision": "rejected", "reason": "존재하지 않는 실행이다."},
            )
            assert missing_review.status_code == 404

    assert market.closed is True


@pytest.mark.asyncio
async def test_manual_work_api_runs_real_provider_and_returns_stored_report() -> None:
    app, _ = make_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            analysis = await client.post("/api/analyze", json={"ticker": "MSFT"})
            run_id = analysis.json()["run_id"]
            await wait_for_status(client, run_id, "review")

            created = await client.post(
                f"/api/runs/{run_id}/tasks",
                json={
                    "role": "fundamental",
                    "title": "현금흐름 재검토",
                    "instructions": "저장된 시장 데이터 범위 안에서 데이터 공백을 정리한다.",
                },
            )
            assert created.status_code == 202
            task_id = created.json()["task"]["id"]

            task: dict[str, Any] | None = None
            for _ in range(100):
                listed = await client.get(f"/api/runs/{run_id}/tasks")
                assert listed.status_code == 200
                tasks = listed.json()["tasks"]
                task = next(item for item in tasks if item["id"] == task_id)
                if task["status"] == "completed":
                    break
                await asyncio.sleep(0.01)

            assert task is not None
            assert task["status"] == "completed"
            assert task["result"]["role"] == "fundamental"

            report = await client.post(f"/api/tasks/{task_id}/report-requests", json={})
            assert report.status_code == 200
            assert report.json()["report"]["source"] == "stored_state"
            assert report.json()["report"]["status"] == "completed"

            invalid_resume = await client.post(f"/api/tasks/{task_id}/resume", json={})
            assert invalid_resume.status_code == 409

            missing = await client.post(f"/api/tasks/{uuid4()}/report-requests", json={})
            assert missing.status_code == 404


@pytest.mark.asyncio
async def test_committee_api_builds_grounded_turns_and_human_gated_minutes() -> None:
    app, _ = make_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            analysis = await client.post("/api/analyze", json={"ticker": "NVDA"})
            run_id = analysis.json()["run_id"]
            await wait_for_status(client, run_id, "review")

            empty = await client.get(f"/api/runs/{run_id}/committee")
            assert empty.status_code == 200
            assert empty.json()["committee"] is None

            started = await client.post(
                f"/api/runs/{run_id}/committee/start",
                json={
                    "topic": "성장 가설과 핵심 하방 위험을 근거 중심으로 검토한다.",
                    "participants": ["fundamental", "head_trader"],
                    "max_turns": 4,
                },
            )
            assert started.status_code == 202
            state = started.json()["committee"]
            session_id = state["session_id"]
            assert state["status"] == "running"
            assert len(state["turns"]) == 2
            assert state["claim_ledger"]

            speech = await client.post(
                f"/api/committee/{session_id}/commands",
                json={
                    "command": "request_speech",
                    "role": "fundamental",
                    "prompt": "입력에 있는 근거와 데이터 공백을 구분해 다시 말한다.",
                },
            )
            assert speech.status_code == 202

            for _ in range(100):
                detail = await client.get(f"/api/committee/{session_id}")
                assert detail.status_code == 200
                if len(detail.json()["committee"]["turns"]) == 3:
                    break
                await asyncio.sleep(0.01)
            assert len(detail.json()["committee"]["turns"]) == 3

            stopped = await client.post(
                f"/api/committee/{session_id}/commands",
                json={"command": "stop"},
            )
            assert stopped.status_code == 202

            final_state: dict[str, Any] | None = None
            for _ in range(100):
                latest = await client.get(f"/api/runs/{run_id}/committee")
                final_state = latest.json()["committee"]
                if final_state and final_state["status"] == "stopped":
                    break
                await asyncio.sleep(0.01)
            assert final_state is not None
            assert final_state["status"] == "stopped"

            minutes = await client.get(f"/api/committee/{session_id}/minutes")
            assert minutes.status_code == 200
            minute_payload = minutes.json()["minutes"]
            assert minute_payload["human_approval_required"] is True
            assert minute_payload["auto_trade"] is False
            assert minute_payload["generation_method"] == "deterministic_claim_ledger_v1"

            after_end = await client.post(
                f"/api/committee/{session_id}/commands",
                json={"command": "finish"},
            )
            assert after_end.status_code == 409


@pytest.mark.asyncio
async def test_schedule_and_decision_archive_apis_preserve_future_and_past_runs() -> None:
    app, _ = make_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            scheduled_for = datetime.now(UTC) + timedelta(minutes=10)
            created = await client.post(
                "/api/schedules",
                json={
                    "ticker": "AAPL",
                    "thesis": "예약 분석 계약을 검증한다.",
                    "scheduled_for": scheduled_for.isoformat(),
                },
            )
            assert created.status_code == 202
            body = created.json()
            assert body["deduplicated"] is False
            schedule_id = body["schedule"]["id"]
            run_id = body["schedule"]["run_id"]
            assert body["schedule"]["status"] == "scheduled"
            assert body["schedule"]["timezone"] == "Asia/Seoul"
            assert body["schedule"]["thesis"] == "예약 분석 계약을 검증한다."
            assert body["run"]["status"] == "scheduled"

            schedules = await client.get("/api/schedules")
            assert schedules.status_code == 200
            assert schedules.json()["schedules"][0]["id"] == schedule_id
            assert schedules.json()["schedules"][0]["thesis"] == "예약 분석 계약을 검증한다."

            archive = await client.get("/api/decisions", params={"limit": 50})
            assert archive.status_code == 200
            entry = next(
                item for item in archive.json()["decisions"] if item["run_id"] == run_id
            )
            assert entry["effective_status"] == "scheduled"
            assert entry["decision"] is None
            assert entry["scheduled_analysis"]["run_id"] == run_id

            detail = await client.get(f"/api/decisions/{run_id}")
            assert detail.status_code == 200
            assert detail.json()["decision"]["ticker"] == "AAPL"

            cancelled = await client.post(f"/api/schedules/{schedule_id}/cancel", json={})
            assert cancelled.status_code == 200
            assert cancelled.json()["schedule"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_identical_concurrent_schedule_requests_are_deduplicated() -> None:
    storage = InMemoryStorage()
    app, _ = make_app(storage=storage)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            payload = {
                "ticker": "AAPL",
                "thesis": "동일 예약 요청을 한 건으로 처리한다.",
                "scheduled_for": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            }
            first, second = await asyncio.gather(
                client.post("/api/schedules", json=payload),
                client.post("/api/schedules", json=payload),
            )

            assert first.status_code == 202
            assert second.status_code == 202
            assert first.json()["schedule"]["id"] == second.json()["schedule"]["id"]
            assert first.json()["run"]["run_id"] == second.json()["run"]["run_id"]
            assert sorted([first.json()["deduplicated"], second.json()["deduplicated"]]) == [
                False,
                True,
            ]
            assert len(storage.list_analysis_runs()) == 1


@pytest.mark.asyncio
async def test_schedule_storage_failure_cancels_created_run() -> None:
    storage = FlakyScheduleStorage()
    app, _ = make_app(storage=storage)

    async with app.router.lifespan_context(app):
        storage.fail_next_schedule_snapshot = True
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            response = await client.post(
                "/api/schedules",
                json={
                    "ticker": "MSFT",
                    "scheduled_for": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
                },
            )

            assert response.status_code == 500
            runs = storage.list_analysis_runs()
            assert len(runs) == 1
            assert runs[0].status is AnalysisRunStatus.CANCELLED
            candidate = storage.get_candidate(runs[0].candidate_id)
            assert candidate is not None
            assert candidate.status is CandidateStatus.ARCHIVED


@pytest.mark.asyncio
async def test_due_schedule_is_dispatched_to_existing_analysis_pipeline() -> None:
    app, _ = make_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            created = await client.post(
                "/api/schedules",
                json={
                    "ticker": "MSFT",
                    "scheduled_for": (datetime.now(UTC) + timedelta(milliseconds=200)).isoformat(),
                },
            )
            assert created.status_code == 202
            schedule_id = created.json()["schedule"]["id"]
            run_id = created.json()["schedule"]["run_id"]

            final_schedule: dict[str, Any] | None = None
            for _ in range(500):
                response = await client.get(f"/api/schedules/{schedule_id}")
                assert response.status_code == 200
                final_schedule = response.json()["schedule"]
                if final_schedule["status"] in {"completed", "failed"}:
                    break
                await asyncio.sleep(0.01)

            assert final_schedule is not None
            assert final_schedule["status"] == "completed"
            completed_run = await client.get(f"/api/runs/{run_id}")
            assert completed_run.status_code == 200
            assert completed_run.json()["run"]["status"] == "review"
            assert completed_run.json()["run"]["progress"] == 100


@pytest.mark.asyncio
async def test_scheduler_poller_survives_temporary_storage_error() -> None:
    storage = FlakyScheduleStorage()
    app, _ = make_app(storage=storage)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            created = await client.post(
                "/api/schedules",
                json={
                    "ticker": "AAPL",
                    "scheduled_for": (
                        datetime.now(UTC) + timedelta(milliseconds=200)
                    ).isoformat(),
                },
            )
            assert created.status_code == 202
            storage.fail_next_run_lookup = True

            for _ in range(350):
                scheduler = cast(dict[str, Any], app.state.scheduler_status)
                if scheduler["status"] == "degraded":
                    break
                await asyncio.sleep(0.01)

            assert scheduler["status"] == "degraded"
            assert "temporary storage outage" in scheduler["error"]
            pollers = [
                task
                for task in app.state.tasks
                if task.get_name() == "scheduled-analysis-poller"
            ]
            assert len(pollers) == 1
            assert pollers[0].done() is False


@pytest.mark.asyncio
async def test_discovery_api_screens_then_runs_selected_candidates_with_human_gate() -> None:
    app, _ = make_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            screened = await client.post(
                "/api/discoveries/screen",
                json={"strategy": "balanced", "limit": 8},
            )
            assert screened.status_code == 200
            discovery = screened.json()["discovery"]
            assert discovery["strategy"] == "balanced"
            assert discovery["universe_size"] == 30
            assert discovery["evaluated_count"] == 30
            assert discovery["qualified_count"] == 30
            assert discovery["omitted_count"] == 22
            assert len(discovery["candidates"]) == 8
            assert discovery["candidates"][0]["rank"] == 1
            assert discovery["candidates"][0]["verdict"] in {"review_first", "watch"}
            assert "매수 추천이 아니라" in discovery["safety_notice"]

            empty_archive = await client.get("/api/decisions")
            assert empty_archive.json()["decisions"] == []

            selected = [item["ticker"] for item in discovery["candidates"][:2]]
            launched = await client.post(
                "/api/discoveries/analyze",
                json={"tickers": selected},
            )
            assert launched.status_code == 202
            payload = launched.json()
            assert payload["human_approval_required"] is True
            assert payload["auto_trade"] is False
            assert [item["ticker"] for item in payload["runs"]] == selected
            assert payload["discovery_batch_id"]
            assert {
                item["discovery_batch_id"] for item in payload["runs"]
            } == {payload["discovery_batch_id"]}
            assert {item["workflow"] for item in payload["runs"]} == {"discovery"}

            for item in payload["runs"]:
                completed = await wait_for_status(client, item["run_id"], "review")
                assert completed["decision"]["auto_trade"] is False
                assert completed["workflow"] == "discovery"
                assert completed["discovery_batch_id"] == payload["discovery_batch_id"]

            archive = await client.get("/api/decisions")
            assert {item["ticker"] for item in archive.json()["decisions"]} == set(selected)

            duplicate = await client.post(
                "/api/discoveries/analyze",
                json={"tickers": [selected[0], selected[0].lower()]},
            )
            assert duplicate.status_code == 422

            too_many = await client.post(
                "/api/discoveries/analyze",
                json={"tickers": ["AAPL", "MSFT", "NVDA", "META"]},
            )
            assert too_many.status_code == 422


@pytest.mark.asyncio
async def test_api_accepts_explicit_korean_market_and_keeps_markets_separate() -> None:
    app, _ = make_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            analysis = await client.post(
                "/api/analyze",
                json={"market": "kr", "ticker": "005930"},
            )
            assert analysis.status_code == 202
            run = analysis.json()["run"]
            assert run["market"] == "kr"
            assert run["ticker"] == "005930"
            assert run["canonical_id"] == "kr:005930"

            invalid = await client.post(
                "/api/analyze",
                json={"market": "kr", "ticker": "AAPL"},
            )
            assert invalid.status_code == 422

            screened = await client.post(
                "/api/discoveries/screen",
                json={"market": "kr", "strategy": "balanced", "limit": 3},
            )
            assert screened.status_code == 200
            discovery = screened.json()["discovery"]
            assert discovery["market"] == "kr"
            assert discovery["universe_size"] == 30
            assert all(item["market"] == "kr" for item in discovery["candidates"])

            sources_response = await client.get("/api/data-sources")
            assert sources_response.status_code == 200
            sources = sources_response.json()["sources"]
            by_id = {item["policy"]["id"]: item for item in sources}
            assert by_id["sec"]["status"]["analysis_ready"] is False
            assert by_id["fred"]["status"]["analysis_ready"] is True
            assert by_id["data_go_kr"]["status"]["analysis_ready"] is False
            assert by_id["reuters"]["status"]["analysis_ready"] is False

            overview_response = await client.get("/api/markets/overview")
            assert overview_response.status_code == 200
            overview = overview_response.json()
            assert set(overview["markets"]) == {"us", "kr"}
            assert overview["common"]["status"] == "ready"


@pytest.mark.asyncio
async def test_run_list_filters_ui_status_and_returns_unlimited_summary() -> None:
    app, _ = make_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            manual = await client.post("/api/analyze", json={"ticker": "AAPL"})
            assert manual.status_code == 202
            assert manual.json()["run"]["workflow"] == "manual"

            scheduled = await client.post(
                "/api/schedules",
                json={
                    "ticker": "MSFT",
                    "scheduled_for": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                },
            )
            assert scheduled.status_code == 202
            assert scheduled.json()["run"]["workflow"] == "scheduled"

            discovery = await client.post(
                "/api/discoveries/analyze",
                json={"tickers": ["NVDA", "META"]},
            )
            assert discovery.status_code == 202

            all_runs = await client.get("/api/runs", params={"limit": 1})
            assert all_runs.status_code == 200
            payload = all_runs.json()
            assert len(payload["runs"]) == 1
            assert payload["summary"]["total"] == 4
            assert payload["summary"]["filtered_total"] == 4
            assert payload["summary"]["returned"] == 1
            assert payload["summary"]["by_workflow"] == {
                "manual": 1,
                "discovery": 2,
                "scheduled": 1,
                "unknown": 0,
            }

            discovery_runs = await client.get(
                "/api/runs",
                params={"workflow": "discovery", "limit": 200},
            )
            assert discovery_runs.status_code == 200
            assert len(discovery_runs.json()["runs"]) == 2
            assert {item["workflow"] for item in discovery_runs.json()["runs"]} == {
                "discovery"
            }

            scheduled_runs = await client.get(
                "/api/runs",
                params={"workflow": "scheduled", "status": "scheduled"},
            )
            assert scheduled_runs.status_code == 200
            assert [item["ticker"] for item in scheduled_runs.json()["runs"]] == ["MSFT"]
            assert scheduled_runs.json()["summary"]["filtered_total"] == 1

            assert (await client.get("/api/runs", params={"limit": 0})).status_code == 422
            assert (await client.get("/api/runs", params={"limit": 201})).status_code == 422
            assert (
                await client.get("/api/runs", params={"workflow": "invalid"})
            ).status_code == 422


def test_analysis_site_routes_use_separate_templates() -> None:
    app, _ = make_app()
    routes = {
        route.path: route.endpoint.__name__
        for route in app.routes
        if isinstance(route, APIRoute)
    }

    assert routes["/analysis"] == "analysis_page"
    assert routes["/markets"] == "markets_page"
    assert routes["/discovery"] == "discovery_page"
    assert routes["/history"] == "history_page"


@pytest.mark.asyncio
async def test_site_navigation_replaces_game_entry_while_office_stays_available() -> None:
    app, _ = make_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            landing = await client.get("/")
            markets = await client.get("/markets")
            office = await client.get("/office")

    assert landing.status_code == 200
    assert 'href="/analysis"' in landing.text
    assert 'href="/markets"' in landing.text
    assert 'href="/discovery"' in landing.text
    assert 'href="/history"' in landing.text
    assert 'href="/office"' not in landing.text
    assert office.status_code == 200
    assert markets.status_code == 200
    assert 'id="markets-refresh"' in markets.text
    assert "<canvas" in office.text
    assert 'id="office-canvas"' in office.text
    assert 'src="/static/office.js?v=8"' in office.text


@pytest.mark.asyncio
async def test_sse_stream_starts_with_injected_provider_state() -> None:
    app, _ = make_app()

    async with app.router.lifespan_context(app):
        route = next(
            route
            for route in app.routes
            if isinstance(route, APIRoute) and route.path == "/api/events"
        )
        endpoint = cast(
            Callable[[Request], Awaitable[StreamingResponse]],
            route.endpoint,
        )

        async def disconnected() -> Message:
            return {"type": "http.disconnect"}

        scope = cast(
            Scope,
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/api/events",
                "raw_path": b"/api/events",
                "query_string": b"",
                "root_path": "",
                "headers": [],
                "client": ("127.0.0.1", 12345),
                "server": ("testserver", 80),
                "app": app,
                "state": {},
            },
        )
        response = await endpoint(Request(scope, disconnected))
        iterator = cast(AsyncIterator[str | bytes], response.body_iterator)
        first_chunk = await anext(iterator)
        text = first_chunk.decode() if isinstance(first_chunk, bytes) else first_chunk

        assert response.media_type == "text/event-stream"
        assert text.startswith("event: provider\n")
        payload = json.loads(text.split("data: ", maxsplit=1)[1])
        assert payload["type"] == "provider"
        assert payload["provider"]["status"] == "ready"
        assert payload["provider"]["mode"] == "injected"
