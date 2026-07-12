# Graph Report - investment-office  (2026-07-12)

## Corpus Check
- 80 files · ~110,144 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1989 nodes · 7817 edges · 74 communities (69 shown, 5 thin omitted)
- Extraction: 67% EXTRACTED · 33% INFERRED · 0% AMBIGUOUS · INFERRED: 2553 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `01a0ce95`
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
- ScheduledAnalysisService
- research_contracts.py
- CommitteeValidationError
- test_orchestrator.py
- interact
- create_app
- test_price_gateway.py
- price_gateway.py
- InstrumentRef
- SourceId
- MarketId
- ResearchPipeline
- MarketRegimeEvaluator
- assess_risk
- YahooFinanceClient
- InsufficientMarketDataError
- MacroContextResult
- ecos_context.py
- InstrumentIdentity
- Storage
- test_macro_context.py
- test_ecos_context.py
- datetime
- submitDiscoveryScreen
- Self
- build_codex_child_environment
- renderAgentTasks

## God Nodes (most connected - your core abstractions)
1. `MarketId` - 127 edges
2. `InstrumentRef` - 102 edges
3. `Snapshot` - 99 edges
4. `AnalysisRunStatus` - 89 edges
5. `EODSnapshot` - 89 edges
6. `Storage` - 89 edges
7. `Fact` - 88 edges
8. `AnalysisProvider` - 87 edges
9. `AgentRole` - 84 edges
10. `ResearchSection` - 81 edges

## Surprising Connections (you probably didn't know these)
- `test_bls_monthly_baselines_cross_calendar_year_safely()` --calls--> `OfficialMacroContextClient`  [INFERRED]
  tests/test_macro_context.py → src/investment_office/services/macro_context.py
- `test_duplicate_treasury_failures_preserve_bls_axis()` --calls--> `OfficialMacroContextClient`  [INFERRED]
  tests/test_macro_context.py → src/investment_office/services/macro_context.py
- `test_official_client_uses_origin_sources_and_blocks_unlicensed_axes()` --calls--> `OfficialMacroContextClient`  [INFERRED]
  tests/test_macro_context.py → src/investment_office/services/macro_context.py
- `test_provider_failure_preserves_other_official_axis()` --calls--> `OfficialMacroContextClient`  [INFERRED]
  tests/test_macro_context.py → src/investment_office/services/macro_context.py
- `FakeMarketOverviewService` --uses--> `Settings`  [INFERRED]
  tests/test_api.py → src/investment_office/config.py

## Import Cycles
- None detected.

## Communities (74 total, 5 thin omitted)

### Community 0 - "Snapshot"
Cohesion: 0.13
Nodes (53): create_database_runtime(), DatabaseRuntime, 실행 중인 MariaDB 연결과 저장소를 함께 보관한다., 허용된 데이터베이스에만 연결하고 필요할 때 6개 테이블을 생성한다., AnalysisRunStatus, AnalyzeRequest, CommitteeCommandRequest, CreateWorkItemRequest (+45 more)

### Community 1 - "AnalysisRun"
Cohesion: 0.06
Nodes (43): DeclarativeBase, SessionFactory, AnalysisRun, Candidate, DomainModel, HumanReview, BaseModel, Self (+35 more)

### Community 2 - "analysis.js"
Cohesion: 0.15
Nodes (48): activateTab(), ACTIVE_COMMITTEE_STATUSES, ACTIVE_RUN_STATUSES, bindEvents(), elements, handleTabKeydown(), handleTaskAction(), loadMinutes() (+40 more)

### Community 3 - "EODSnapshot"
Cohesion: 0.09
Nodes (28): CandidateDiscoveryItem, CandidateDiscoveryResult, CandidateDiscoveryService, DiscoveryEODMetrics, DiscoveryVerdict, EODMarketDataClient, BaseModel, Exception (+20 more)

### Community 4 - "app.js"
Cohesion: 0.11
Nodes (85): addEvent(), agentStatusLabel(), announce(), asArray(), asObject(), bindEvents(), calculateProgress(), compactText() (+77 more)

### Community 5 - "YahooFinanceClient"
Cohesion: 0.24
Nodes (16): _atr(), _average_volume(), _EODBar, _optional_float(), _optional_int(), _optional_mapping(), _optional_sequence(), _require_sequence() (+8 more)

### Community 6 - "test_api.py"
Cohesion: 0.05
Nodes (75): BaseSettings, EODMarketDataClient, LogCaptureFixture, get_settings(), 환경 변수와 로컬 .env 파일에서 읽는 실행 설정., 인증이 없는 로컬 API가 외부 인터페이스에 노출되지 않게 한다., 프로세스에서 동일한 검증 설정 객체를 재사용한다., Settings (+67 more)

### Community 7 - "WorkItemService"
Cohesion: 0.11
Nodes (30): Lock, datetime, 도메인 객체의 기본 시각을 UTC로 생성한다., utc_now(), Any, BaseModel, UUID, 수동 업무를 역할별로 한 번에 하나만 실행하고 상태를 스냅샷으로 남긴다. (+22 more)

### Community 8 - "CommitteeBroker"
Cohesion: 0.10
Nodes (20): AwareDatetime, JsonDict, _ActiveMeeting, CommitteeBroker, CommitteeMeetingState, CommitteeMinutes, CommitteeStatus, Any (+12 more)

### Community 9 - "office.js"
Cohesion: 0.10
Nodes (38): agentForRole(), agentStatus(), ApiRequestError, bindKeyboard(), bindMobileControls(), collides(), confidenceLabel(), configureScheduleTime() (+30 more)

### Community 10 - "._run_agent"
Cohesion: 0.06
Nodes (26): AnalysisWorkflow, AnalysisWorkflowView, LookupError, Self, InstrumentIdentityError, normalize_instrument(), ValueError, 시장과 종목 식별자가 지원 계약과 맞지 않을 때 발생한다. (+18 more)

### Community 11 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 12 - "API"
Cohesion: 0.22
Nodes (25): applyCommittee(), committeeFromPayload(), committeeIdentifier(), committeeIsActive(), committeeStatusLabel(), handleScheduleAction(), handleTaskAction(), loadAgentTasks() (+17 more)

### Community 13 - "CodexProvider"
Cohesion: 0.15
Nodes (10): Process, AnalysisResult, EvidenceItem, Any, BaseModel, Path, Task, 모델이 선택한 사실 원장 식별자 하나만 받는다. (+2 more)

### Community 14 - "codex_provider.py"
Cohesion: 0.25
Nodes (4): EventCallback, CodexProtocolError, StreamReader, Raised when JSONL progress output violates the documented protocol.

### Community 15 - "setText"
Cohesion: 0.17
Nodes (23): announce(), applyProvider(), applyRun(), closeDialog(), connectEvents(), loadInitialState(), refreshRun(), renderDecisionDraft() (+15 more)

### Community 16 - "bindUi"
Cohesion: 0.15
Nodes (22): bindUi(), decisionsFromPayload(), discoveryRunFromPayload(), discoveryRunId(), discoveryRunIsTerminal(), discoveryRunsFromPayload(), discoveryRunStatus(), finishCommittee() (+14 more)

### Community 17 - "test_codex_provider.py"
Cohesion: 0.30
Nodes (23): CodexProvider, Run one isolated, read-only ``codex exec`` analysis per request., grounded_bundle(), install_fake_spawn(), Any, MonkeyPatch, snapshot(), test_analyze_accepts_evidence_referencing_input_fact() (+15 more)

### Community 18 - "fillRect"
Cohesion: 0.27
Nodes (18): draw(), drawBackground(), drawConferenceTable(), drawDesk(), drawIntake(), drawInteractionMarker(), drawLounge(), drawNpc() (+10 more)

### Community 19 - "FakeStdin"
Cohesion: 0.10
Nodes (24): CodexExecutableNotFoundError, CodexInputError, CodexLaunchError, CodexOutputLimitError, CodexProcessError, CodexProviderError, CodexResponseValidationError, CodexTimeoutError (+16 more)

### Community 20 - "submitDiscoveryScreen"
Cohesion: 0.23
Nodes (13): CommitteeAgentError, 지정 발언 호출이 실패했지만 결과를 보존한 경우., FakeProvider, Any, Exception, seed_completed_run(), test_directed_speak_calls_only_selected_role_and_respects_turn_cap(), test_directed_speak_failure_is_preserved_in_output_and_minutes() (+5 more)

### Community 21 - "renderAgentTasks"
Cohesion: 0.16
Nodes (17): DecisionArchiveEntry, DecisionArchiveService, BaseModel, UUID, 실행 식별자로 카드 한 건을 조회한다., 예약 분석 스냅샷에서 의사결정 카드에 필요한 메타데이터., 한 분석 실행과 연결된 과거 의사결정 카드., 저장된 실행을 변경하지 않고 의사결정 카드 목록과 상세를 제공한다. (+9 more)

### Community 22 - "Pixel Investment Office"
Cohesion: 0.09
Nodes (21): 뉴스 적용, 목표, 미국·한국 시장 연구 설계, 사실 원장과 기준시점, 시장 분리, 운영과 보안, 자료 품질 게이트, 재무와 비율 (+13 more)

### Community 23 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 24 - "CodexProcessError"
Cohesion: 0.47
Nodes (3): PathLike, CodexConfigurationError, Raised when provider configuration is invalid.

### Community 25 - "test_scheduled_analysis.py"
Cohesion: 0.09
Nodes (42): calculate_valuation_metrics(), CompanyResearchError, _dart_filing_dates(), _dart_observed_date(), _dart_payload_items(), _dart_receipt_date(), _date_time(), _evidence_section() (+34 more)

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
Cohesion: 0.43
Nodes (6): build_analysis_prompt(), get_role_instruction(), _market_label(), Any, Return the bounded analysis instruction for a supported role., Build a prompt that treats every supplied payload value as untrusted data.

### Community 33 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 34 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 35 - "graphify reference: incremental update and cluster-only"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

### Community 46 - "ScheduledAnalysisService"
Cohesion: 0.11
Nodes (24): Any, BaseModel, datetime, UUID, 기존 분석 서비스와 명시적으로 연결되는 호환 속성., 예약 시각이 된 분석을 한 번만 claim할 수 있게 조정한다., 대기 중인 분석 실행을 미래의 KST 시각에 한 번 예약한다., 최신 예약 상태를 예정 시각과 등록 순서 기준으로 반환한다. (+16 more)

### Community 47 - "research_contracts.py"
Cohesion: 0.21
Nodes (40): OfficialCompanyResearchClient, SEC와 DART의 공식 API만 사용해 회사 연구 자료를 수집한다., 충분한 입력으로만 계산한 재무 비율과 입력 공백., _SecMetricSpec, ValuationMetrics, EcosContextResult, EcosMacroContextClient, _empty_result() (+32 more)

### Community 48 - "CommitteeValidationError"
Cohesion: 0.13
Nodes (34): ApiError, apiFieldLabel(), apiValidationMessage(), buildOperationHandle(), clockFormatter, dateTimeFormatter, finishStoredOperation(), formatApiErrorMessage() (+26 more)

### Community 49 - "test_orchestrator.py"
Cohesion: 0.09
Nodes (76): AgentOutput, AgentOutputStatus, AgentRole, CandidateSource, CandidateStatus, Event, EventType, Evidence (+68 more)

### Community 50 - "interact"
Cohesion: 0.21
Nodes (29): renderRunList(), renderSchedules(), renderRuns(), appendTwoLists(), applyFilters(), currentFilters(), elements, loadDetail() (+21 more)

### Community 51 - "create_app"
Cohesion: 0.08
Nodes (45): BaseException, MacroSectionId, _at_utc_midnight(), build_ecos_unavailable_section(), _build_fact(), _build_official_fact(), _build_official_series(), _build_section() (+37 more)

### Community 52 - "test_price_gateway.py"
Cohesion: 0.11
Nodes (44): build_default_price_gateway(), KoreaYahooPriceProvider, MissingPriceApiKeyError, Tiingo 공식 조정 일봉을 검증해 미국 시장 스냅샷으로 변환한다., 한국 거래소 메타데이터를 검증한 Yahoo 일봉을 장애 대체로 제공한다., 권리가 확인된 미국 Tiingo와 한국 공공데이터 게이트웨이를 만든다., 필수 가격 API 인증키가 설정되지 않았을 때 발생한다., TiingoPriceProvider (+36 more)

### Community 53 - "price_gateway.py"
Cohesion: 0.14
Nodes (34): _decode_json(), _decode_korea_yahoo_result(), _decode_tiingo_mapping(), _decode_tiingo_payload(), _decode_tiingo_sequence(), _extract_korea_items(), _korea_yahoo_candidates(), KoreaDailyBar (+26 more)

### Community 54 - "InstrumentRef"
Cohesion: 0.14
Nodes (29): FactValue, _agent_facts(), _build_price_part(), _build_quality(), _build_valuation_part(), _coerce_observed_at(), _collection_cutoff(), _company_part() (+21 more)

### Community 55 - "SourceId"
Cohesion: 0.10
Nodes (39): IntEnum, KeyError, DataDomain, get_source_policy(), LicenseScope, list_source_policies(), Officiality, BaseModel (+31 more)

### Community 56 - "MarketId"
Cohesion: 0.14
Nodes (34): _aware_utc(), _build_common(), _build_quality(), CommonMacroOverview, _evaluate_regime(), _expected_section_ids(), _failed_quality(), MacroContextProvider (+26 more)

### Community 57 - "ResearchPipeline"
Cohesion: 0.27
Nodes (35): CompanyResearchResult, 한 회사의 공식 재무 사실과 공시 메타데이터 수집 결과., 서로 독립적인 자료 공급원을 병렬 수집하고 품질 차단을 한곳에서 적용한다., ResearchPipeline, _company_result(), _CompanyClient, _ecos_result(), _fact() (+27 more)

### Community 58 - "MarketRegimeEvaluator"
Cohesion: 0.14
Nodes (23): _AxisEvaluation, _FactIndex, _finite_number(), MarketRegimeEvaluator, MarketRegimePolicy, _NumericFact, Self, 검증된 거시 사실만으로 축별 국면과 보수적 노출 상한을 산출한다. (+15 more)

### Community 59 - "assess_risk"
Cohesion: 0.14
Nodes (32): RiskAction, assess_risk(), _blocked(), _chairman_mapping(), _confidence(), BaseModel, ValueError, 의장 결론 또는 시장 스냅샷이 위험 산정 계약과 맞지 않을 때 발생한다. (+24 more)

### Community 60 - "YahooFinanceClient"
Cohesion: 0.10
Nodes (34): InvalidTickerError, MarketDataError, normalize_us_ticker(), AsyncClient, datetime, Response, RuntimeError, ValueError (+26 more)

### Community 61 - "InsufficientMarketDataError"
Cohesion: 0.09
Nodes (31): EODSnapshot, InsufficientMarketDataError, BaseModel, 현재가와 직전 종가조차 산출할 수 없을 때 발생한다., Yahoo Finance의 완료된 일봉으로 만든 재현 가능한 시장 스냅샷., build_default_committee_price_gateway(), build_kr_eod_snapshot(), CommitteePriceGateway (+23 more)

### Community 62 - "MacroContextResult"
Cohesion: 0.06
Nodes (16): button, buttonLabel, failedOutcome, FakeButton, FakeClassList, FakeElement, history, list (+8 more)

### Community 63 - "ecos_context.py"
Cohesion: 0.21
Nodes (17): Cycle, _assemble_result(), _at_utc_midnight(), EcosSeriesSpec, _failed_series(), _latest_observation(), _logical_error_code(), _parse_number() (+9 more)

### Community 64 - "InstrumentIdentity"
Cohesion: 0.14
Nodes (27): appendTags(), arrayOfText(), DOMAIN_LABELS, elements, firstDefined(), formatReading(), FRESHNESS_LABELS, loadMarkets() (+19 more)

### Community 65 - "Storage"
Cohesion: 0.20
Nodes (22): ACTIVE, DECIDED, elements, latestBatchRuns(), loadRuns(), marketLabel(), renderCandidates(), renderDiscovery() (+14 more)

### Community 66 - "test_macro_context.py"
Cohesion: 0.13
Nodes (12): MacroContextResult, 시장 개요 조회도 같은 자료 수집 한도 안에서 실행한다., 4시간 캐시와 단일화를 적용해 공통 거시 자료를 시장별 보완 구역과 반환한다., _fred_result(), _korean_result(), _Pipeline, Exception, test_both_market_failures_return_degraded_overview_instead_of_raising() (+4 more)

### Community 67 - "test_ecos_context.py"
Cohesion: 0.20
Nodes (11): Request, _mock_client(), _payload(), Any, AsyncClient, Response, test_fetch_uses_verified_codes_and_builds_complete_official_section(), test_http_and_logical_errors_block_without_exposing_key_or_remote_message() (+3 more)

### Community 68 - "datetime"
Cohesion: 0.29
Nodes (4): KoreaPublicDataPriceProvider, AsyncClient, datetime, 금융위원회 공공데이터 API에서 한국 주식 일봉을 조회한다.

### Community 69 - "submitDiscoveryScreen"
Cohesion: 0.18
Nodes (14): appendDiscoveryList(), candidateScore(), candidateTicker(), discoveryFromPayload(), discoveryStrategyLabel(), discoveryVerdictLabel(), handleDiscoverySelection(), renderDiscovery() (+6 more)

### Community 70 - "Self"
Cohesion: 0.24
Nodes (5): ModelT, Self, _require_known_refs(), _require_unique(), _unique_by_id()

### Community 71 - "build_codex_child_environment"
Cohesion: 0.50
Nodes (3): build_codex_child_environment(), 코덱스 인증과 실행에 필요한 비민감 환경 변수만 전달한다., 코덱스 인증과 실행에 필요한 비민감 환경 변수만 반환한다.

### Community 73 - "renderAgentTasks"
Cohesion: 0.17
Nodes (13): addTaskButton(), appendMinutesSection(), committeeClaims(), committeeEntries(), evidenceText(), readableTime(), renderAgentTasks(), renderCommitteeClaims() (+5 more)

## Knowledge Gaps
- **95 isolated node(s):** `investment-office`, `elements`, `state`, `elements`, `state` (+90 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MarketId` connect `MarketId` to `Snapshot`, `test_macro_context.py`, `EODSnapshot`, `datetime`, `test_api.py`, `._run_agent`, `research_contracts.py`, `test_orchestrator.py`, `test_price_gateway.py`, `price_gateway.py`, `InstrumentRef`, `SourceId`, `test_scheduled_analysis.py`, `MarketRegimeEvaluator`, `InsufficientMarketDataError`, `ResearchPipeline`?**
  _High betweenness centrality (0.088) - this node is a cross-community bridge._
- **Why does `YahooFinanceClient` connect `YahooFinanceClient` to `Snapshot`, `AnalysisRun`, `datetime`, `YahooFinanceClient`, `test_api.py`, `test_orchestrator.py`, `test_price_gateway.py`, `price_gateway.py`, `InsufficientMarketDataError`?**
  _High betweenness centrality (0.071) - this node is a cross-community bridge._
- **Why does `CodexProvider` connect `test_codex_provider.py` to `Snapshot`, `build_codex_child_environment`, `CodexProvider`, `codex_provider.py`, `FakeStdin`, `CodexProcessError`?**
  _High betweenness centrality (0.070) - this node is a cross-community bridge._
- **Are the 94 inferred relationships involving `MarketId` (e.g. with `AnalyzeRequest` and `CommitteeCommandRequest`) actually correct?**
  _`MarketId` has 94 INFERRED edges - model-reasoned connections that need verification._
- **Are the 54 inferred relationships involving `InstrumentRef` (e.g. with `CompanyResearchError` and `CompanyResearchResult`) actually correct?**
  _`InstrumentRef` has 54 INFERRED edges - model-reasoned connections that need verification._
- **Are the 86 inferred relationships involving `Snapshot` (e.g. with `_ActiveMeeting` and `_ClaimAccumulator`) actually correct?**
  _`Snapshot` has 86 INFERRED edges - model-reasoned connections that need verification._
- **Are the 83 inferred relationships involving `AnalysisRunStatus` (e.g. with `AnalyzeRequest` and `CommitteeCommandRequest`) actually correct?**
  _`AnalysisRunStatus` has 83 INFERRED edges - model-reasoned connections that need verification._