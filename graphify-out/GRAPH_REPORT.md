# Graph Report - investment-office  (2026-07-11)

## Corpus Check
- 56 files · ~67,328 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1177 nodes · 3855 edges · 114 communities (36 shown, 78 thin omitted)
- Extraction: 69% EXTRACTED · 31% INFERRED · 0% AMBIGUOUS · INFERRED: 1184 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

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
- BaseModel
- Path
- RuntimeError
- StreamReader
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
- Protocol
- RiskFunction
- RuntimeError
- UUID
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
- BaseModel
- RuntimeError
- StrEnum
- UUID
- Any
- JsonValue
- Protocol
- UUID
- Any
- AsyncClient
- BaseModel
- FastAPI
- UUID
- Exception
- Any
- StreamReader
- Any
- Exception
- datetime
- Any
- AsyncClient
- Any
- BaseModel
- Exception
- BaseModel
- Any

## God Nodes (most connected - your core abstractions)
1. `Storage` - 75 edges
2. `Snapshot` - 70 edges
3. `AnalysisProvider` - 68 edges
4. `CommitteeBroker` - 63 edges
5. `SnapshotKind` - 60 edges
6. `AnalysisRunStatus` - 56 edges
7. `EventBroker` - 55 edges
8. `AgentRole` - 54 edges
9. `Event` - 53 edges
10. `InvestmentCommittee` - 50 edges

## Surprising Connections (you probably didn't know these)
- `FakeMarketData` --uses--> `Settings`  [INFERRED]
  tests/test_api.py → src/investment_office/config.py
- `FakeProvider` --uses--> `Settings`  [INFERRED]
  tests/test_api.py → src/investment_office/config.py
- `FakeRiskResult` --uses--> `Settings`  [INFERRED]
  tests/test_api.py → src/investment_office/config.py
- `FakeSnapshot` --uses--> `Settings`  [INFERRED]
  tests/test_api.py → src/investment_office/config.py
- `FlakyScheduleStorage` --uses--> `Settings`  [INFERRED]
  tests/test_api.py → src/investment_office/config.py

## Import Cycles
- None detected.

## Communities (114 total, 78 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (128): AnalysisWorkflow, BaseSettings, 환경 변수와 로컬 .env 파일에서 읽는 실행 설정., Settings, DatabaseRuntime, 실행 중인 MariaDB 연결과 저장소를 함께 보관한다., AgentOutput, AgentOutputStatus (+120 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (51): AnalysisResult, CodexConfigurationError, CodexExecutableNotFoundError, CodexInputError, CodexLaunchError, CodexOutputLimitError, CodexProcessError, CodexProtocolError (+43 more)

### Community 2 - "Community 2"
Cohesion: 0.08
Nodes (46): _atr(), _average_volume(), _EODBar, InsufficientMarketDataError, InvalidTickerError, MarketDataError, normalize_us_ticker(), _optional_float() (+38 more)

### Community 3 - "Community 3"
Cohesion: 0.08
Nodes (21): AwareDatetime, _ActiveMeeting, CommitteeBroker, CommitteeMeetingState, 기존 에이전트 결과를 감사 가능한 투자위원회 회의로 구성한다., 완료된 분석 결과를 고정 순서의 회의 발언으로 불러온다., 사람이 지정한 한 역할만 추가로 호출하고 성공과 실패를 모두 저장한다., 추가 모델 호출 없이 claim ledger와 최종 회의록을 저장한다. (+13 more)

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
Cohesion: 0.13
Nodes (21): create_app(), 운영 의존성 또는 테스트 대역으로 애플리케이션을 구성한다., fake_risk(), FakeMarketData, FakeProvider, FakeRiskResult, FakeSnapshot, FlakyScheduleStorage (+13 more)

### Community 10 - "Community 10"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 11 - "Community 11"
Cohesion: 0.20
Nodes (9): Pixel Investment Office, 검증, 게임형 업무와 회의, 데이터베이스 범위, 분석 흐름, 접속과 종료, 처음 한 번 실행, 투자 사용 범위 (+1 more)

### Community 12 - "Community 12"
Cohesion: 0.44
Nodes (7): GateProvider, make_service(), test_cancelled_queue_item_can_resume_as_new_attempt_only(), test_failure_report_and_resume_use_stored_previous_context_for_new_attempt(), test_report_reads_only_persisted_state_without_provider_call(), test_run_requires_stored_market_snapshot_without_calling_provider(), test_same_run_and_role_executes_only_one_item_then_next_queue_item()

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
Cohesion: 0.40
Nodes (4): get_settings(), 프로세스에서 동일한 검증 설정 객체를 재사용한다., 설정된 로컬 주소에서 개발 서버를 실행한다., run()

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
Cohesion: 0.09
Nodes (19): AnalysisWorkflowView, 도메인 객체의 기본 시각을 UTC로 생성한다., utc_now(), 서버 재시작 전에 실행 중이던 분석을 명시적인 실패 상태로 복구한다., 완료된 초안에 대한 사람의 최종 게이트 결정을 기록한다., 프런트엔드가 바로 소비할 수 있는 실행 상태를 조립한다., 수동 업무를 역할별로 한 번에 하나만 실행하고 상태를 스냅샷으로 남긴다., 한 분석 실행의 최신 업무 상태를 대기열 순서로 반환한다. (+11 more)

## Knowledge Gaps
- **62 isolated node(s):** `investment-office`, `elements`, `state`, `elements`, `state` (+57 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **78 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CodexProvider` connect `Community 1` to `Community 0`?**
  _High betweenness centrality (0.058) - this node is a cross-community bridge._
- **Why does `API` connect `AnalysisProvider` to `setText`, `setFeedback`, `Community 4`, `submitDiscoveryAnalysis`, `office.js`?**
  _High betweenness centrality (0.057) - this node is a cross-community bridge._
- **Why does `YahooFinanceClient` connect `Community 2` to `Community 0`, `Community 8`?**
  _High betweenness centrality (0.051) - this node is a cross-community bridge._
- **Are the 60 inferred relationships involving `Storage` (e.g. with `AnalyzeRequest` and `CommitteeCommandRequest`) actually correct?**
  _`Storage` has 60 INFERRED edges - model-reasoned connections that need verification._
- **Are the 68 inferred relationships involving `Snapshot` (e.g. with `_ActiveMeeting` and `_ClaimAccumulator`) actually correct?**
  _`Snapshot` has 68 INFERRED edges - model-reasoned connections that need verification._
- **Are the 65 inferred relationships involving `AnalysisProvider` (e.g. with `AnalyzeRequest` and `CommitteeCommandRequest`) actually correct?**
  _`AnalysisProvider` has 65 INFERRED edges - model-reasoned connections that need verification._
- **Are the 27 inferred relationships involving `CommitteeBroker` (e.g. with `AnalyzeRequest` and `CommitteeCommandRequest`) actually correct?**
  _`CommitteeBroker` has 27 INFERRED edges - model-reasoned connections that need verification._