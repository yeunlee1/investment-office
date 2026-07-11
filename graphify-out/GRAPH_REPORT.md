# Graph Report - investment-office  (2026-07-12)

## Corpus Check
- 56 files · ~69,749 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1214 nodes · 4438 edges · 46 communities (41 shown, 5 thin omitted)
- Extraction: 72% EXTRACTED · 28% INFERRED · 0% AMBIGUOUS · INFERRED: 1246 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `fc82bdbc`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Snapshot
- AnalysisRun
- analysis.js
- EODSnapshot
- app.js
- YahooFinanceClient
- test_api.py
- WorkItemService
- CommitteeBroker
- office.js
- ._run_agent
- What You Must Do When Invoked
- API
- CodexProvider
- codex_provider.py
- setText
- bindUi
- test_codex_provider.py
- fillRect
- FakeStdin
- submitDiscoveryScreen
- renderAgentTasks
- Pixel Investment Office
- graphify reference: extra exports and benchmark
- CodexProcessError
- test_scheduled_analysis.py
- graphify reference: query, path, explain
- .subscribe
- bootstrap_database.py
- build_analysis_prompt
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: incremental update and cluster-only
- graphify reference: GitHub clone and cross-repo merge
- graphify reference: transcribe video and audio
- AGENTS.md
- extraction-spec.md
- investment-office

## God Nodes (most connected - your core abstractions)
1. `Snapshot` - 88 edges
2. `Storage` - 82 edges
3. `AnalysisRunStatus` - 77 edges
4. `AnalysisProvider` - 75 edges
5. `AgentRole` - 74 edges
6. `AnalysisRun` - 71 edges
7. `SnapshotKind` - 68 edges
8. `Event` - 68 edges
9. `Candidate` - 65 edges
10. `CommitteeBroker` - 63 edges

## Surprising Connections (you probably didn't know these)
- `test_settings_reject_non_loopback_hosts()` --calls--> `Settings`  [INFERRED]
  tests/test_api.py → src/investment_office/config.py
- `FakeMarketData` --uses--> `CandidateStatus`  [INFERRED]
  tests/test_api.py → src/investment_office/domain.py
- `FakeProvider` --uses--> `CandidateStatus`  [INFERRED]
  tests/test_api.py → src/investment_office/domain.py
- `FakeRiskResult` --uses--> `CandidateStatus`  [INFERRED]
  tests/test_api.py → src/investment_office/domain.py
- `FakeSnapshot` --uses--> `CandidateStatus`  [INFERRED]
  tests/test_api.py → src/investment_office/domain.py

## Import Cycles
- None detected.

## Communities (46 total, 5 thin omitted)

### Community 0 - "Snapshot"
Cohesion: 0.05
Nodes (140): create_database_runtime(), DatabaseRuntime, 실행 중인 MariaDB 연결과 저장소를 함께 보관한다., 허용된 데이터베이스에만 연결하고 필요할 때 6개 테이블을 생성한다., AgentOutput, AgentOutputStatus, AgentRole, AnalysisRunStatus (+132 more)

### Community 1 - "AnalysisRun"
Cohesion: 0.05
Nodes (61): AnalysisWorkflow, DeclarativeBase, ModelT, Self, SessionFactory, AnalysisRun, Candidate, CandidateStatus (+53 more)

### Community 2 - "analysis.js"
Cohesion: 0.08
Nodes (98): activateTab(), ACTIVE_COMMITTEE_STATUSES, ACTIVE_RUN_STATUSES, bindEvents(), elements, handleTabKeydown(), handleTaskAction(), loadMinutes() (+90 more)

### Community 3 - "EODSnapshot"
Cohesion: 0.06
Nodes (64): RiskAction, Semaphore, CandidateDiscoveryItem, CandidateDiscoveryResult, CandidateDiscoveryService, DiscoveryEODMetrics, DiscoveryVerdict, EODMarketDataClient (+56 more)

### Community 4 - "app.js"
Cohesion: 0.11
Nodes (85): addEvent(), agentStatusLabel(), announce(), asArray(), asObject(), bindEvents(), calculateProgress(), compactText() (+77 more)

### Community 5 - "YahooFinanceClient"
Cohesion: 0.08
Nodes (52): Response, _atr(), _average_volume(), _EODBar, InsufficientMarketDataError, InvalidTickerError, MarketDataError, normalize_us_ticker() (+44 more)

### Community 6 - "test_api.py"
Cohesion: 0.07
Nodes (46): BaseSettings, LogCaptureFixture, get_settings(), 환경 변수와 로컬 .env 파일에서 읽는 실행 설정., 인증이 없는 로컬 API가 외부 인터페이스에 노출되지 않게 한다., 프로세스에서 동일한 검증 설정 객체를 재사용한다., Settings, create_app() (+38 more)

### Community 7 - "WorkItemService"
Cohesion: 0.11
Nodes (29): Lock, datetime, 도메인 객체의 기본 시각을 UTC로 생성한다., utc_now(), Any, BaseModel, UUID, 수동 업무를 역할별로 한 번에 하나만 실행하고 상태를 스냅샷으로 남긴다. (+21 more)

### Community 8 - "CommitteeBroker"
Cohesion: 0.11
Nodes (17): AwareDatetime, JsonDict, _ActiveMeeting, CommitteeBroker, CommitteeMeetingState, Any, JsonValue, UUID (+9 more)

### Community 9 - "office.js"
Cohesion: 0.10
Nodes (38): agentForRole(), agentStatus(), ApiRequestError, bindKeyboard(), bindMobileControls(), collides(), confidenceLabel(), configureScheduleTime() (+30 more)

### Community 10 - "._run_agent"
Cohesion: 0.13
Nodes (10): AnalysisWorkflowView, LookupError, Any, UUID, 후속 등록 실패로 실행할 수 없는 대기 분석을 취소 상태로 확정한다., 한 분석 실행을 완료하거나 실패 상태로 확정한다., 서버 재시작 전에 실행 중이던 분석을 명시적인 실패 상태로 복구한다., 완료된 초안에 대한 사람의 최종 게이트 결정을 기록한다. (+2 more)

### Community 11 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 12 - "API"
Cohesion: 0.22
Nodes (25): applyCommittee(), committeeFromPayload(), committeeIdentifier(), committeeIsActive(), committeeStatusLabel(), handleScheduleAction(), handleTaskAction(), loadAgentTasks() (+17 more)

### Community 13 - "CodexProvider"
Cohesion: 0.17
Nodes (9): EventCallback, Process, CodexProvider, Any, Path, Task, Run one isolated, read-only ``codex exec`` analysis per request., Execute a role analysis and return a validated JSON-compatible dictionary. (+1 more)

### Community 14 - "codex_provider.py"
Cohesion: 0.11
Nodes (20): AnalysisResult, CodexExecutableNotFoundError, CodexInputError, CodexLaunchError, CodexOutputLimitError, CodexProtocolError, CodexProviderError, EvidenceItem (+12 more)

### Community 15 - "setText"
Cohesion: 0.17
Nodes (23): announce(), applyProvider(), applyRun(), closeDialog(), connectEvents(), loadInitialState(), refreshRun(), renderDecisionDraft() (+15 more)

### Community 16 - "bindUi"
Cohesion: 0.15
Nodes (22): bindUi(), decisionsFromPayload(), discoveryRunFromPayload(), discoveryRunId(), discoveryRunIsTerminal(), discoveryRunsFromPayload(), discoveryRunStatus(), finishCommittee() (+14 more)

### Community 17 - "test_codex_provider.py"
Cohesion: 0.32
Nodes (18): MonkeyPatch, CodexResponseValidationError, Raised when the final response is missing, malformed, or ungrounded., install_fake_spawn(), Any, snapshot(), test_analyze_kills_process_after_timeout(), test_analyze_kills_process_when_stdout_exceeds_limit() (+10 more)

### Community 18 - "fillRect"
Cohesion: 0.27
Nodes (18): draw(), drawBackground(), drawConferenceTable(), drawDesk(), drawIntake(), drawInteractionMarker(), drawLounge(), drawNpc() (+10 more)

### Community 19 - "FakeStdin"
Cohesion: 0.15
Nodes (6): CodexTimeoutError, Raised when a Codex invocation exceeds its deadline., FakeProcess, FakeStdin, make_stream(), StreamReader

### Community 20 - "submitDiscoveryScreen"
Cohesion: 0.18
Nodes (14): appendDiscoveryList(), candidateScore(), candidateTicker(), discoveryFromPayload(), discoveryStrategyLabel(), discoveryVerdictLabel(), handleDiscoverySelection(), renderDiscovery() (+6 more)

### Community 21 - "renderAgentTasks"
Cohesion: 0.17
Nodes (13): addTaskButton(), appendMinutesSection(), committeeClaims(), committeeEntries(), evidenceText(), readableTime(), renderAgentTasks(), renderCommitteeClaims() (+5 more)

### Community 22 - "Pixel Investment Office"
Cohesion: 0.20
Nodes (9): Pixel Investment Office, 검증, 게임형 업무와 회의, 데이터베이스 범위, 분석 흐름, 접속과 종료, 처음 한 번 실행, 투자 사용 범위 (+1 more)

### Community 23 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 24 - "CodexProcessError"
Cohesion: 0.28
Nodes (5): PathLike, CodexConfigurationError, CodexProcessError, Raised when Codex exits unsuccessfully., Raised when provider configuration is invalid.

### Community 25 - "test_scheduled_analysis.py"
Cohesion: 0.56
Nodes (8): add_run(), make_service(), test_cancel_and_dispatch_terminal_records_enforce_transitions(), test_claim_due_uses_scheduled_time_then_global_sequence_fifo(), test_concurrent_schedule_requests_create_only_one_active_item(), test_due_schedule_reconciles_run_that_was_completed_before_dispatch(), test_new_service_recovers_persisted_claim_and_reconciles_dispatch(), test_schedule_requires_aware_future_time_and_persists_kst_event()

### Community 28 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 29 - ".subscribe"
Cohesion: 0.33
Nodes (4): Queue, Any, 현재 연결된 모든 구독자에게 이벤트 복사본을 보낸다., 구독 생명주기 동안 전용 큐를 등록한다.

### Community 30 - "bootstrap_database.py"
Cohesion: 0.60
Nodes (5): _existing_app_password(), main(), Path, _random_password(), _workspace()

### Community 31 - "build_analysis_prompt"
Cohesion: 0.40
Nodes (5): build_analysis_prompt(), get_role_instruction(), Any, Return the bounded analysis instruction for a supported role., Build a prompt that treats every supplied payload value as untrusted data.

### Community 33 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 34 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 35 - "graphify reference: incremental update and cluster-only"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

## Knowledge Gaps
- **62 isolated node(s):** `investment-office`, `elements`, `state`, `elements`, `state` (+57 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CodexProvider` connect `CodexProvider` to `Snapshot`, `codex_provider.py`, `test_codex_provider.py`, `FakeStdin`, `CodexProcessError`?**
  _High betweenness centrality (0.086) - this node is a cross-community bridge._
- **Why does `YahooFinanceClient` connect `YahooFinanceClient` to `Snapshot`, `test_api.py`?**
  _High betweenness centrality (0.062) - this node is a cross-community bridge._
- **Why does `EODSnapshot` connect `EODSnapshot` to `Snapshot`, `YahooFinanceClient`?**
  _High betweenness centrality (0.061) - this node is a cross-community bridge._
- **Are the 75 inferred relationships involving `Snapshot` (e.g. with `_ActiveMeeting` and `_ClaimAccumulator`) actually correct?**
  _`Snapshot` has 75 INFERRED edges - model-reasoned connections that need verification._
- **Are the 60 inferred relationships involving `Storage` (e.g. with `AnalyzeRequest` and `CommitteeCommandRequest`) actually correct?**
  _`Storage` has 60 INFERRED edges - model-reasoned connections that need verification._
- **Are the 71 inferred relationships involving `AnalysisRunStatus` (e.g. with `AnalyzeRequest` and `CommitteeCommandRequest`) actually correct?**
  _`AnalysisRunStatus` has 71 INFERRED edges - model-reasoned connections that need verification._
- **Are the 68 inferred relationships involving `AnalysisProvider` (e.g. with `AnalyzeRequest` and `CommitteeCommandRequest`) actually correct?**
  _`AnalysisProvider` has 68 INFERRED edges - model-reasoned connections that need verification._