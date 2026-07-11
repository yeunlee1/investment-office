# Graph Report - investment-office  (2026-07-12)

## Corpus Check
- 56 files · ~68,983 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1207 nodes · 4121 edges · 90 communities (40 shown, 50 thin omitted)
- Extraction: 70% EXTRACTED · 30% INFERRED · 0% AMBIGUOUS · INFERRED: 1233 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c889097a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- office.js
- Pixel Investment Office
- graphify reference: query, path, explain
- graphify reference: add a URL and watch a folder
- graphify reference: incremental update and cluster-only
- test_office_game.py
- graphify reference: GitHub clone and cross-repo merge
- graphify reference: transcribe video and audio
- AGENTS.md
- extraction-spec.md
- AnalysisProvider
- WorkItemService
- .subscribe
- WorkItemService
- fillRect
- setText
- setFeedback
- interact
- submitDiscoveryAnalysis
- Settings
- test_scheduled_analysis.py
- GateProvider
- AnalysisRun
- test_dashboard_discovery.py
- BaseModel
- FastAPI
- RiskFunction
- BaseModel
- Exception
- Protocol
- StrEnum
- Any
- Any
- BaseModel
- JsonValue
- RuntimeError
- StrEnum
- UUID
- ValueError
- BaseModel
- UUID
- Any
- AsyncClient
- BaseModel
- datetime
- RuntimeError
- ValueError
- Any
- BaseModel
- ValueError
- Any
- BaseModel
- datetime
- RuntimeError
- StrEnum
- UUID
- Any
- JsonValue
- Protocol
- UUID
- Exception
- Any
- Exception
- datetime
- Any
- AsyncClient
- BaseModel

## God Nodes (most connected - your core abstractions)
1. `Storage` - 78 edges
2. `AnalysisProvider` - 74 edges
3. `Snapshot` - 73 edges
4. `AnalysisRunStatus` - 67 edges
5. `AgentRole` - 65 edges
6. `Event` - 63 edges
7. `CommitteeBroker` - 63 edges
8. `SnapshotKind` - 62 edges
9. `EventBroker` - 60 edges
10. `AnalysisRun` - 56 edges

## Surprising Connections (you probably didn't know these)
- `test_settings_reject_non_loopback_hosts()` --calls--> `Settings`  [INFERRED]
  tests/test_api.py → src/investment_office/config.py
- `EventFailingStorage` --uses--> `CandidateStatus`  [INFERRED]
  tests/test_orchestrator.py → src/investment_office/domain.py
- `FakeMarketData` --uses--> `CandidateStatus`  [INFERRED]
  tests/test_orchestrator.py → src/investment_office/domain.py
- `FakeProvider` --uses--> `CandidateStatus`  [INFERRED]
  tests/test_orchestrator.py → src/investment_office/domain.py
- `FakeRiskResult` --uses--> `CandidateStatus`  [INFERRED]
  tests/test_orchestrator.py → src/investment_office/domain.py

## Import Cycles
- None detected.

## Communities (90 total, 50 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.22
Nodes (35): AgentOutput, AgentOutputStatus, AgentRole, CandidateSource, Event, EventType, Evidence, SnapshotKind (+27 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (61): build_analysis_prompt(), get_role_instruction(), Return the bounded analysis instruction for a supported role., Build a prompt that treats every supplied payload value as untrusted data., EventCallback, MonkeyPatch, PathLike, Process (+53 more)

### Community 2 - "Community 2"
Cohesion: 0.08
Nodes (46): _atr(), _average_volume(), _EODBar, InsufficientMarketDataError, InvalidTickerError, MarketDataError, normalize_us_ticker(), _optional_float() (+38 more)

### Community 3 - "Community 3"
Cohesion: 0.10
Nodes (15): AwareDatetime, _ActiveMeeting, CommitteeBroker, CommitteeMeetingState, CommitteeMinutes, 기존 에이전트 결과를 감사 가능한 투자위원회 회의로 구성한다., 완료된 분석 결과를 고정 순서의 회의 발언으로 불러온다., 사람이 지정한 한 역할만 추가로 호출하고 성공과 실패를 모두 저장한다. (+7 more)

### Community 4 - "Community 4"
Cohesion: 0.11
Nodes (85): addEvent(), agentStatusLabel(), announce(), asArray(), asObject(), bindEvents(), calculateProgress(), compactText() (+77 more)

### Community 5 - "Community 5"
Cohesion: 0.06
Nodes (55): CandidateDiscoveryItem, CandidateDiscoveryResult, CandidateDiscoveryService, DiscoveryEODMetrics, DiscoveryVerdict, EODMarketDataClient, 순위가 있거나 제외 사유가 기록된 유니버스 종목., 후보와 제외 종목을 분리한 1차 스크리닝 결과. (+47 more)

### Community 6 - "Community 6"
Cohesion: 0.07
Nodes (18): create_database_runtime(), 허용된 데이터베이스에만 연결하고 필요할 때 6개 테이블을 생성한다., _clone(), deserialize_domain(), InMemoryStorage, MariaDBStorage, _payload(), Pydantic 도메인 객체를 MariaDB JSON 컬럼에 안전한 값으로 바꾼다. (+10 more)

### Community 7 - "Community 7"
Cohesion: 0.12
Nodes (16): 기존 분석 서비스와 명시적으로 연결되는 호환 속성., 예약 시각이 된 분석을 한 번만 claim할 수 있게 조정한다., 대기 중인 분석 실행을 미래의 KST 시각에 한 번 예약한다., 최신 예약 상태를 예정 시각과 등록 순서 기준으로 반환한다., 예약 ID에 해당하는 최신 영속 상태를 반환한다., 아직 claim되지 않은 예약을 취소한다., 예약 시각이 지난 항목을 FIFO 순서로 원자적으로 claim한다., claim된 예약이 실제 실행 콜백에 전달됐음을 기록한다. (+8 more)

### Community 8 - "Community 8"
Cohesion: 0.14
Nodes (43): DatabaseRuntime, 실행 중인 MariaDB 연결과 저장소를 함께 보관한다., AnalysisRunStatus, ReviewDecision, DiscoveryStrategy, DecisionArchiveNotFoundError, 요청한 분석 실행 또는 연결 후보가 없을 때 발생한다., EventBroker (+35 more)

### Community 10 - "Community 10"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 11 - "Community 11"
Cohesion: 0.20
Nodes (9): Pixel Investment Office, 검증, 게임형 업무와 회의, 데이터베이스 범위, 분석 흐름, 접속과 종료, 처음 한 번 실행, 투자 사용 범위 (+1 more)

### Community 12 - "Community 12"
Cohesion: 0.16
Nodes (11): AnalysisWorkflowView, LookupError, InvestmentCommittee, Any, UUID, 한 분석 실행을 완료하거나 실패 상태로 확정한다., 서버 재시작 전에 실행 중이던 분석을 명시적인 실패 상태로 복구한다., 완료된 초안에 대한 사람의 최종 게이트 결정을 기록한다. (+3 more)

### Community 13 - "Community 13"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 14 - "Community 14"
Cohesion: 0.56
Nodes (8): add_run(), make_service(), test_cancel_and_dispatch_terminal_records_enforce_transitions(), test_claim_due_uses_scheduled_time_then_global_sequence_fifo(), test_concurrent_schedule_requests_create_only_one_active_item(), test_due_schedule_reconciles_run_that_was_completed_before_dispatch(), test_new_service_recovers_persisted_claim_and_reconciles_dispatch(), test_schedule_requires_aware_future_time_and_persists_kst_event()

### Community 15 - "office.js"
Cohesion: 0.09
Nodes (43): addTaskButton(), ApiRequestError, appendDiscoveryList(), appendMinutesSection(), candidateScore(), candidateTicker(), committeeClaims(), committeeEntries() (+35 more)

### Community 18 - "Pixel Investment Office"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 19 - "graphify reference: query, path, explain"
Cohesion: 0.70
Nodes (4): _existing_app_password(), main(), _random_password(), _workspace()

### Community 20 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.10
Nodes (40): AnalysisWorkflow, AnalysisRun, Candidate, CandidateStatus, DomainModel, HumanReview, Snapshot, DecisionArchiveEntry (+32 more)

### Community 22 - "graphify reference: incremental update and cluster-only"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 23 - "test_office_game.py"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 24 - "graphify reference: GitHub clone and cross-repo merge"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

### Community 28 - "AnalysisProvider"
Cohesion: 0.08
Nodes (99): activateTab(), ACTIVE_COMMITTEE_STATUSES, ACTIVE_RUN_STATUSES, bindEvents(), elements, handleTabKeydown(), handleTaskAction(), loadMinutes() (+91 more)

### Community 32 - "fillRect"
Cohesion: 0.20
Nodes (22): collides(), draw(), drawBackground(), drawConferenceTable(), drawDesk(), drawIntake(), drawInteractionMarker(), drawLounge() (+14 more)

### Community 33 - "setText"
Cohesion: 0.20
Nodes (21): announce(), applyProvider(), applyRun(), connectEvents(), loadInitialState(), refreshRun(), renderDecisionDraft(), replaceList() (+13 more)

### Community 34 - "setFeedback"
Cohesion: 0.21
Nodes (25): applyCommittee(), committeeFromPayload(), committeeIdentifier(), committeeIsActive(), committeeStatusLabel(), configureScheduleTime(), handleScheduleAction(), handleTaskAction() (+17 more)

### Community 36 - "interact"
Cohesion: 0.19
Nodes (14): agentForRole(), agentStatus(), bindKeyboard(), bindMobileControls(), closeDialog(), debugState(), interact(), normalizeStatus() (+6 more)

### Community 37 - "submitDiscoveryAnalysis"
Cohesion: 0.12
Nodes (27): bindUi(), decisionsFromPayload(), discoveryRunFromPayload(), discoveryRunId(), discoveryRunIsTerminal(), discoveryRunsFromPayload(), discoveryRunStatus(), finishCommittee() (+19 more)

### Community 39 - "Settings"
Cohesion: 0.16
Nodes (18): 도메인 객체의 기본 시각을 UTC로 생성한다., utc_now(), Lock, Any, BaseModel, UUID, 수동 업무를 역할별로 한 번에 하나만 실행하고 상태를 스냅샷으로 남긴다., 한 분석 실행의 최신 업무 상태를 대기열 순서로 반환한다. (+10 more)

### Community 40 - "test_scheduled_analysis.py"
Cohesion: 0.29
Nodes (10): CommitteeValidationError, 회의 입력이나 제어 명령이 허용 범위를 벗어난 경우., FakeProvider, seed_completed_run(), test_directed_speak_calls_only_selected_role_and_respects_turn_cap(), test_directed_speak_failure_is_preserved_in_output_and_minutes(), test_existing_outputs_form_deterministic_ledger_and_minutes(), test_running_meeting_can_resume_from_snapshot_after_restart() (+2 more)

### Community 45 - "BaseModel"
Cohesion: 0.23
Nodes (14): blocked_risk(), fake_risk(), make_committee(), Any, RiskFunction, test_agent_failure_is_persisted_without_reviewable_decision(), test_analysis_cannot_start_twice(), test_analysis_workflow_metadata_is_stored_and_exposed() (+6 more)

### Community 46 - "FastAPI"
Cohesion: 0.35
Nodes (10): GateProvider, make_service(), Any, test_cancelled_queue_item_can_resume_as_new_attempt_only(), test_failure_report_and_resume_use_stored_previous_context_for_new_attempt(), test_report_reads_only_persisted_state_without_provider_call(), test_restart_recovery_fails_running_item_and_returns_valid_queue(), test_run_requires_stored_market_snapshot_without_calling_provider() (+2 more)

### Community 47 - "RiskFunction"
Cohesion: 0.07
Nodes (44): BaseSettings, LogCaptureFixture, get_settings(), 환경 변수와 로컬 .env 파일에서 읽는 실행 설정., 인증이 없는 로컬 API가 외부 인터페이스에 노출되지 않게 한다., 프로세스에서 동일한 검증 설정 객체를 재사용한다., Settings, create_app() (+36 more)

## Knowledge Gaps
- **62 isolated node(s):** `investment-office`, `elements`, `state`, `elements`, `state` (+57 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **50 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CodexProvider` connect `Community 1` to `Community 8`?**
  _High betweenness centrality (0.070) - this node is a cross-community bridge._
- **Why does `YahooFinanceClient` connect `Community 2` to `Community 0`, `Community 8`, `Community 12`, `BaseModel`, `RiskFunction`, `Any`?**
  _High betweenness centrality (0.067) - this node is a cross-community bridge._
- **Why does `API` connect `AnalysisProvider` to `setText`, `setFeedback`, `Community 4`, `submitDiscoveryAnalysis`, `office.js`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Are the 60 inferred relationships involving `Storage` (e.g. with `_ActiveMeeting` and `_ClaimAccumulator`) actually correct?**
  _`Storage` has 60 INFERRED edges - model-reasoned connections that need verification._
- **Are the 68 inferred relationships involving `AnalysisProvider` (e.g. with `_ActiveMeeting` and `_ClaimAccumulator`) actually correct?**
  _`AnalysisProvider` has 68 INFERRED edges - model-reasoned connections that need verification._
- **Are the 71 inferred relationships involving `Snapshot` (e.g. with `_ActiveMeeting` and `_ClaimAccumulator`) actually correct?**
  _`Snapshot` has 71 INFERRED edges - model-reasoned connections that need verification._
- **Are the 66 inferred relationships involving `AnalysisRunStatus` (e.g. with `_ActiveMeeting` and `_ClaimAccumulator`) actually correct?**
  _`AnalysisRunStatus` has 66 INFERRED edges - model-reasoned connections that need verification._