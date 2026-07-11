# Graph Report - investment-office  (2026-07-12)

## Corpus Check
- 56 files · ~69,387 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1212 nodes · 4191 edges · 91 communities (46 shown, 45 thin omitted)
- Extraction: 70% EXTRACTED · 30% INFERRED · 0% AMBIGUOUS · INFERRED: 1254 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `af0c1d46`
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
- AnalysisRun
- YahooFinanceClient
- market_data.py
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
- MariaDBStorage
- AsyncClient
- BaseModel
- datetime
- RuntimeError
- ValueError
- FakeMarketData
- test_in_memory_storage_supports_full_review_flow_without_database
- Self
- Any
- BaseModel
- ValueError
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
1. `Snapshot` - 79 edges
2. `Storage` - 79 edges
3. `AnalysisProvider` - 74 edges
4. `AnalysisRunStatus` - 72 edges
5. `SnapshotKind` - 67 edges
6. `AgentRole` - 65 edges
7. `Event` - 63 edges
8. `CommitteeBroker` - 63 edges
9. `EventBroker` - 61 edges
10. `AnalysisRun` - 58 edges

## Surprising Connections (you probably didn't know these)
- `test_mariadb_storage_constructor_does_not_open_a_session()` --calls--> `MariaDBStorage`  [INFERRED]
  tests/test_storage.py → src/investment_office/storage.py
- `test_settings_reject_non_loopback_hosts()` --calls--> `Settings`  [INFERRED]
  tests/test_api.py → src/investment_office/config.py
- `FakeMarketData` --uses--> `CandidateStatus`  [INFERRED]
  tests/test_api.py → src/investment_office/domain.py
- `FakeProvider` --uses--> `CandidateStatus`  [INFERRED]
  tests/test_api.py → src/investment_office/domain.py
- `FakeRiskResult` --uses--> `CandidateStatus`  [INFERRED]
  tests/test_api.py → src/investment_office/domain.py

## Import Cycles
- None detected.

## Communities (91 total, 45 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.26
Nodes (33): AgentOutput, AgentOutputStatus, AgentRole, CandidateSource, EventType, Evidence, Snapshot, SnapshotKind (+25 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (61): build_analysis_prompt(), get_role_instruction(), Return the bounded analysis instruction for a supported role., Build a prompt that treats every supplied payload value as untrusted data., EventCallback, MonkeyPatch, PathLike, Process (+53 more)

### Community 2 - "Community 2"
Cohesion: 0.16
Nodes (13): InsufficientMarketDataError, MarketDataError, Fetch two years of daily bars and compute a completed-EOD snapshot., 시장 데이터 조회 또는 변환 실패의 기본 예외., Yahoo Finance 응답이 실패했거나 계약과 다를 때 발생한다., 조회된 자산이 지원 대상인 미국 주식 또는 ETF가 아닐 때 발생한다., 현재가와 직전 종가조차 산출할 수 없을 때 발생한다., _require_mapping() (+5 more)

### Community 3 - "Community 3"
Cohesion: 0.08
Nodes (24): AwareDatetime, _ActiveMeeting, CommitteeBroker, CommitteeMeetingState, CommitteeValidationError, 기존 에이전트 결과를 감사 가능한 투자위원회 회의로 구성한다., 완료된 분석 결과를 고정 순서의 회의 발언으로 불러온다., 사람이 지정한 한 역할만 추가로 호출하고 성공과 실패를 모두 저장한다. (+16 more)

### Community 4 - "Community 4"
Cohesion: 0.11
Nodes (85): addEvent(), agentStatusLabel(), announce(), asArray(), asObject(), bindEvents(), calculateProgress(), compactText() (+77 more)

### Community 5 - "Community 5"
Cohesion: 0.14
Nodes (31): assess_risk(), _blocked(), _chairman_mapping(), _confidence(), 의장 결론 또는 시장 스냅샷이 위험 산정 계약과 맞지 않을 때 발생한다., Dollar capital과 무관한 위험 단위 및 기술 지표 제한 정책., Human approval 전에 적용할 가격 계획과 최대 위험 노출., Return a deterministic, capital-independent risk assessment. (+23 more)

### Community 6 - "Community 6"
Cohesion: 0.18
Nodes (4): _clone(), InMemoryStorage, DB 스키마 적용 전에도 동일 인터페이스를 제공하는 프로세스 내 저장소., ModelT

### Community 7 - "Community 7"
Cohesion: 0.12
Nodes (20): Any, BaseModel, datetime, UUID, 기존 분석 서비스와 명시적으로 연결되는 호환 속성., 예약 시각이 된 분석을 한 번만 claim할 수 있게 조정한다., 대기 중인 분석 실행을 미래의 KST 시각에 한 번 예약한다., 최신 예약 상태를 예정 시각과 등록 순서 기준으로 반환한다. (+12 more)

### Community 8 - "Community 8"
Cohesion: 0.13
Nodes (44): DatabaseRuntime, 실행 중인 MariaDB 연결과 저장소를 함께 보관한다., AnalysisRunStatus, DiscoveryStrategy, DecisionArchiveNotFoundError, 요청한 분석 실행 또는 연결 후보가 없을 때 발생한다., EventBroker, 프로세스 내부의 가벼운 fan-out 이벤트 브로커. (+36 more)

### Community 10 - "Community 10"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 11 - "Community 11"
Cohesion: 0.20
Nodes (9): Pixel Investment Office, 검증, 게임형 업무와 회의, 데이터베이스 범위, 분석 흐름, 접속과 종료, 처음 한 번 실행, 투자 사용 범위 (+1 more)

### Community 12 - "Community 12"
Cohesion: 0.13
Nodes (14): AnalysisWorkflow, AnalysisWorkflowView, LookupError, InvestmentCommittee, Any, UUID, 후속 등록 실패로 실행할 수 없는 대기 분석을 취소 상태로 확정한다., 한 분석 실행을 완료하거나 실패 상태로 확정한다. (+6 more)

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
Cohesion: 0.16
Nodes (14): DecisionArchiveEntry, DecisionArchiveService, 실행 식별자로 카드 한 건을 조회한다., 예약 분석 스냅샷에서 의사결정 카드에 필요한 메타데이터., 한 분석 실행과 연결된 과거 의사결정 카드., 저장된 실행을 변경하지 않고 의사결정 카드 목록과 상세를 제공한다., 최신 실행부터 카드로 조합하고 선택적으로 종목과 개수를 제한한다., ScheduledAnalysisSummary (+6 more)

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
Cohesion: 0.13
Nodes (16): CandidateDiscoveryItem, CandidateDiscoveryResult, CandidateDiscoveryService, DiscoveryEODMetrics, DiscoveryVerdict, EODMarketDataClient, 순위가 있거나 제외 사유가 기록된 유니버스 종목., 후보와 제외 종목을 분리한 1차 스크리닝 결과. (+8 more)

### Community 45 - "BaseModel"
Cohesion: 0.14
Nodes (27): Event, ReviewDecision, AnalysisRunConflictError, RuntimeError, 대기 중이 아닌 분석 실행을 중복 시작하려 할 때 발생한다., blocked_risk(), EventFailingStorage, fake_risk() (+19 more)

### Community 46 - "FastAPI"
Cohesion: 0.35
Nodes (10): GateProvider, make_service(), Any, test_cancelled_queue_item_can_resume_as_new_attempt_only(), test_failure_report_and_resume_use_stored_previous_context_for_new_attempt(), test_report_reads_only_persisted_state_without_provider_call(), test_restart_recovery_fails_running_item_and_returns_valid_queue(), test_run_requires_stored_market_snapshot_without_calling_provider() (+2 more)

### Community 47 - "RiskFunction"
Cohesion: 0.07
Nodes (46): BaseSettings, LogCaptureFixture, get_settings(), 환경 변수와 로컬 .env 파일에서 읽는 실행 설정., 인증이 없는 로컬 API가 외부 인터페이스에 노출되지 않게 한다., 프로세스에서 동일한 검증 설정 객체를 재사용한다., Settings, create_app() (+38 more)

### Community 54 - "AnalysisRun"
Cohesion: 0.26
Nodes (16): AnalysisRun, Candidate, CandidateStatus, DomainModel, HumanReview, AgentOutputRecord, AnalysisRunRecord, Base (+8 more)

### Community 55 - "YahooFinanceClient"
Cohesion: 0.21
Nodes (18): InvalidTickerError, normalize_us_ticker(), Normalize a supported US ticker, including Yahoo's class-share separator., Fetch and validate recent completed Yahoo Finance daily bars., 지원하지 않는 미국 종목 티커 형식일 때 발생한다., YahooFinanceClient, _chart_payload(), _mock_client() (+10 more)

### Community 56 - "market_data.py"
Cohesion: 0.25
Nodes (15): _atr(), _average_volume(), _EODBar, _optional_float(), _optional_int(), _optional_mapping(), _optional_sequence(), _return_pct() (+7 more)

### Community 67 - "MariaDBStorage"
Cohesion: 0.22
Nodes (7): create_database_runtime(), 허용된 데이터베이스에만 연결하고 필요할 때 6개 테이블을 생성한다., MariaDBStorage, Pydantic 도메인 객체를 MariaDB JSON 컬럼에 안전한 값으로 바꾼다., 호출자가 제공한 SQLAlchemy Session 팩토리만 사용하는 MariaDB 저장소., serialize_domain(), SessionFactory

### Community 73 - "FakeMarketData"
Cohesion: 0.35
Nodes (8): 명시적 스타터 유니버스의 종목과 섹터., UniverseMember, FakeMarketData, snapshot(), test_data_shortage_and_lookup_failure_are_excluded_without_failing_screen(), test_screen_respects_concurrency_limit_and_returns_deterministic_ranking(), test_strategy_changes_weighting_without_changing_input_data(), test_validates_public_screen_arguments()

### Community 74 - "test_in_memory_storage_supports_full_review_flow_without_database"
Cohesion: 0.36
Nodes (5): _candidate(), test_domain_payload_round_trip_preserves_types(), test_in_memory_storage_filters_and_returns_defensive_copies(), test_in_memory_storage_supports_full_review_flow_without_database(), test_mariadb_storage_constructor_does_not_open_a_session()

## Knowledge Gaps
- **62 isolated node(s):** `investment-office`, `elements`, `state`, `elements`, `state` (+57 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **45 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CodexProvider` connect `Community 1` to `Community 8`?**
  _High betweenness centrality (0.069) - this node is a cross-community bridge._
- **Why does `YahooFinanceClient` connect `YahooFinanceClient` to `Community 0`, `Community 2`, `Community 8`, `Community 12`, `BaseModel`, `RiskFunction`, `Any`, `market_data.py`?**
  _High betweenness centrality (0.062) - this node is a cross-community bridge._
- **Why does `API` connect `AnalysisProvider` to `setText`, `setFeedback`, `Community 4`, `submitDiscoveryAnalysis`, `office.js`?**
  _High betweenness centrality (0.051) - this node is a cross-community bridge._
- **Are the 76 inferred relationships involving `Snapshot` (e.g. with `_ActiveMeeting` and `_ClaimAccumulator`) actually correct?**
  _`Snapshot` has 76 INFERRED edges - model-reasoned connections that need verification._
- **Are the 60 inferred relationships involving `Storage` (e.g. with `_ActiveMeeting` and `_ClaimAccumulator`) actually correct?**
  _`Storage` has 60 INFERRED edges - model-reasoned connections that need verification._
- **Are the 68 inferred relationships involving `AnalysisProvider` (e.g. with `_ActiveMeeting` and `_ClaimAccumulator`) actually correct?**
  _`AnalysisProvider` has 68 INFERRED edges - model-reasoned connections that need verification._
- **Are the 71 inferred relationships involving `AnalysisRunStatus` (e.g. with `_ActiveMeeting` and `_ClaimAccumulator`) actually correct?**
  _`AnalysisRunStatus` has 71 INFERRED edges - model-reasoned connections that need verification._