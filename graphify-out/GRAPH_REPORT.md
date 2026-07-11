# Graph Report - investment-office  (2026-07-12)

## Corpus Check
- 56 files · ~68,390 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1197 nodes · 4049 edges · 96 communities (40 shown, 56 thin omitted)
- Extraction: 70% EXTRACTED · 30% INFERRED · 0% AMBIGUOUS · INFERRED: 1221 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `4678da90`
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
- BaseModel
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
- Any

## God Nodes (most connected - your core abstractions)
1. `Storage` - 77 edges
2. `Snapshot` - 72 edges
3. `AnalysisProvider` - 72 edges
4. `Event` - 63 edges
5. `CommitteeBroker` - 63 edges
6. `SnapshotKind` - 62 edges
7. `AgentRole` - 59 edges
8. `AnalysisRunStatus` - 58 edges
9. `EventBroker` - 58 edges
10. `InvestmentCommittee` - 55 edges

## Surprising Connections (you probably didn't know these)
- `test_settings_reject_non_loopback_hosts()` --calls--> `Settings`  [INFERRED]
  tests/test_api.py → src/investment_office/config.py
- `EventFailingStorage` --uses--> `AnalysisRunStatus`  [INFERRED]
  tests/test_orchestrator.py → src/investment_office/domain.py
- `FakeMarketData` --uses--> `AnalysisRunStatus`  [INFERRED]
  tests/test_orchestrator.py → src/investment_office/domain.py
- `FakeProvider` --uses--> `AnalysisRunStatus`  [INFERRED]
  tests/test_orchestrator.py → src/investment_office/domain.py
- `FakeRiskResult` --uses--> `AnalysisRunStatus`  [INFERRED]
  tests/test_orchestrator.py → src/investment_office/domain.py

## Import Cycles
- None detected.

## Communities (96 total, 56 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.31
Nodes (29): AgentOutput, AgentOutputStatus, AgentRole, AnalysisRunStatus, EventType, Evidence, SnapshotKind, _ActiveMeeting (+21 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (61): build_analysis_prompt(), get_role_instruction(), Return the bounded analysis instruction for a supported role., Build a prompt that treats every supplied payload value as untrusted data., EventCallback, MonkeyPatch, PathLike, Process (+53 more)

### Community 2 - "Community 2"
Cohesion: 0.08
Nodes (46): _atr(), _average_volume(), _EODBar, InsufficientMarketDataError, InvalidTickerError, MarketDataError, normalize_us_ticker(), _optional_float() (+38 more)

### Community 3 - "Community 3"
Cohesion: 0.08
Nodes (19): AwareDatetime, CommitteeBroker, 기존 에이전트 결과를 감사 가능한 투자위원회 회의로 구성한다., 완료된 분석 결과를 고정 순서의 회의 발언으로 불러온다., 사람이 지정한 한 역할만 추가로 호출하고 성공과 실패를 모두 저장한다., 추가 모델 호출 없이 claim ledger와 최종 회의록을 저장한다., 중단 요청을 기록하고 진행 중 발언이 끝난 뒤 부분 회의록을 보존한다., 세션 식별자로 현재 또는 종료된 회의 상태를 조회한다. (+11 more)

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
Nodes (39): DatabaseRuntime, 실행 중인 MariaDB 연결과 저장소를 함께 보관한다., DiscoveryStrategy, EventBroker, 프로세스 내부의 가벼운 fan-out 이벤트 브로커., 현재 연결된 모든 구독자에게 이벤트 복사본을 보낸다., 예약, 분석 실행 또는 후보를 찾지 못했을 때 발생한다., 예약 입력값이 유효하지 않을 때 발생한다. (+31 more)

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
Cohesion: 0.08
Nodes (42): verdictLabel(), addTaskButton(), agentForRole(), agentStatus(), ApiRequestError, appendDiscoveryList(), appendMinutesSection(), candidateScore() (+34 more)

### Community 18 - "Pixel Investment Office"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 19 - "graphify reference: query, path, explain"
Cohesion: 0.70
Nodes (4): _existing_app_password(), main(), _random_password(), _workspace()

### Community 20 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.19
Nodes (25): AnalysisWorkflow, AnalysisRun, Candidate, CandidateSource, DomainModel, Event, HumanReview, Snapshot (+17 more)

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
Nodes (98): activateTab(), ACTIVE_COMMITTEE_STATUSES, ACTIVE_RUN_STATUSES, bindEvents(), elements, handleTabKeydown(), handleTaskAction(), loadMinutes() (+90 more)

### Community 32 - "fillRect"
Cohesion: 0.27
Nodes (18): draw(), drawBackground(), drawConferenceTable(), drawDesk(), drawIntake(), drawInteractionMarker(), drawLounge(), drawNpc() (+10 more)

### Community 33 - "setText"
Cohesion: 0.15
Nodes (27): announce(), applyProvider(), applyRun(), connectEvents(), interact(), loadInitialState(), openAgent(), openCommittee() (+19 more)

### Community 34 - "setFeedback"
Cohesion: 0.22
Nodes (27): applyCommittee(), bindUi(), committeeFromPayload(), committeeIdentifier(), committeeIsActive(), committeeStatusLabel(), finishCommittee(), handleScheduleAction() (+19 more)

### Community 36 - "interact"
Cohesion: 0.25
Nodes (8): bindKeyboard(), bindMobileControls(), closeDialog(), collides(), frame(), movementVector(), nudgePlayer(), updatePlayer()

### Community 37 - "submitDiscoveryAnalysis"
Cohesion: 0.18
Nodes (18): discoveryRunFromPayload(), discoveryRunId(), discoveryRunIsTerminal(), discoveryRunsFromPayload(), discoveryRunStatus(), handleDiscoverySelection(), loadStoredDiscoveryRuns(), mergeDiscoveryRuns() (+10 more)

### Community 39 - "Settings"
Cohesion: 0.12
Nodes (21): 도메인 객체의 기본 시각을 UTC로 생성한다., utc_now(), 수동 업무를 역할별로 한 번에 하나만 실행하고 상태를 스냅샷으로 남긴다., 한 분석 실행의 최신 업무 상태를 대기열 순서로 반환한다., 업무 항목의 최신 저장 상태를 반환한다., 모든 분석 실행에서 업무 ID에 해당하는 최신 저장 상태를 찾는다., 역할의 다음 대기 업무 하나를 실행한다.          같은 분석 실행과 역할에 이미 실행 중인 업무가 있으면 아무것도 시작하지 않고, 실행기에서 실제로 관찰한 진행 데이터만 저장한다. (+13 more)

### Community 45 - "BaseModel"
Cohesion: 0.13
Nodes (27): CandidateStatus, ReviewDecision, AnalysisRunConflictError, RuntimeError, 대기 중이 아닌 분석 실행을 중복 시작하려 할 때 발생한다., blocked_risk(), EventFailingStorage, fake_risk() (+19 more)

### Community 46 - "FastAPI"
Cohesion: 0.15
Nodes (16): DecisionArchiveEntry, DecisionArchiveNotFoundError, DecisionArchiveService, 실행 식별자로 카드 한 건을 조회한다., 예약 분석 스냅샷에서 의사결정 카드에 필요한 메타데이터., 한 분석 실행과 연결된 과거 의사결정 카드., 요청한 분석 실행 또는 연결 후보가 없을 때 발생한다., 저장된 실행을 변경하지 않고 의사결정 카드 목록과 상세를 제공한다. (+8 more)

### Community 47 - "RiskFunction"
Cohesion: 0.09
Nodes (38): BaseSettings, get_settings(), 환경 변수와 로컬 .env 파일에서 읽는 실행 설정., 인증이 없는 로컬 API가 외부 인터페이스에 노출되지 않게 한다., 프로세스에서 동일한 검증 설정 객체를 재사용한다., Settings, create_app(), FastAPI (+30 more)

### Community 53 - "BaseModel"
Cohesion: 0.19
Nodes (13): confidenceLabel(), createDecisionArchiveCard(), decisionFromPayload(), decisionIdentifier(), decisionStatusLabel(), decisionView(), loadDecisionDetail(), readableKstTime() (+5 more)

## Knowledge Gaps
- **62 isolated node(s):** `investment-office`, `elements`, `state`, `elements`, `state` (+57 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **56 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CodexProvider` connect `Community 1` to `Community 8`?**
  _High betweenness centrality (0.070) - this node is a cross-community bridge._
- **Why does `AnalysisProvider` connect `Community 0` to `Community 2`, `Community 3`, `Community 5`, `Settings`, `Community 8`, `Community 12`, `BaseModel`, `RiskFunction`, `graphify reference: add a URL and watch a folder`, `Any`?**
  _High betweenness centrality (0.058) - this node is a cross-community bridge._
- **Why does `YahooFinanceClient` connect `Community 2` to `Community 0`, `Community 8`, `Community 12`, `BaseModel`, `RiskFunction`, `Any`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Are the 60 inferred relationships involving `Storage` (e.g. with `_ActiveMeeting` and `_ClaimAccumulator`) actually correct?**
  _`Storage` has 60 INFERRED edges - model-reasoned connections that need verification._
- **Are the 70 inferred relationships involving `Snapshot` (e.g. with `_ActiveMeeting` and `_ClaimAccumulator`) actually correct?**
  _`Snapshot` has 70 INFERRED edges - model-reasoned connections that need verification._
- **Are the 67 inferred relationships involving `AnalysisProvider` (e.g. with `_ActiveMeeting` and `_ClaimAccumulator`) actually correct?**
  _`AnalysisProvider` has 67 INFERRED edges - model-reasoned connections that need verification._
- **Are the 57 inferred relationships involving `Event` (e.g. with `_ActiveMeeting` and `_ClaimAccumulator`) actually correct?**
  _`Event` has 57 INFERRED edges - model-reasoned connections that need verification._