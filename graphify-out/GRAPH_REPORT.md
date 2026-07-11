# Graph Report - investment-office  (2026-07-12)

## Corpus Check
- 78 files · ~105,686 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1922 nodes · 7638 edges · 72 communities (67 shown, 5 thin omitted)
- Extraction: 67% EXTRACTED · 33% INFERRED · 0% AMBIGUOUS · INFERRED: 2554 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `7fe578e6`
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
- `test_settings_reject_non_loopback_hosts()` --calls--> `Settings`  [INFERRED]
  tests/test_api.py → src/investment_office/config.py
- `test_bls_monthly_baselines_cross_calendar_year_safely()` --calls--> `OfficialMacroContextClient`  [INFERRED]
  tests/test_macro_context.py → src/investment_office/services/macro_context.py
- `test_duplicate_treasury_failures_preserve_bls_axis()` --calls--> `OfficialMacroContextClient`  [INFERRED]
  tests/test_macro_context.py → src/investment_office/services/macro_context.py
- `test_official_client_uses_origin_sources_and_blocks_unlicensed_axes()` --calls--> `OfficialMacroContextClient`  [INFERRED]
  tests/test_macro_context.py → src/investment_office/services/macro_context.py
- `test_provider_failure_preserves_other_official_axis()` --calls--> `OfficialMacroContextClient`  [INFERRED]
  tests/test_macro_context.py → src/investment_office/services/macro_context.py

## Import Cycles
- None detected.

## Communities (72 total, 5 thin omitted)

### Community 0 - "Snapshot"
Cohesion: 0.09
Nodes (68): BaseSettings, EODMarketDataClient, get_settings(), 환경 변수와 로컬 .env 파일에서 읽는 실행 설정., 인증이 없는 로컬 API가 외부 인터페이스에 노출되지 않게 한다., 프로세스에서 동일한 검증 설정 객체를 재사용한다., Settings, create_database_runtime() (+60 more)

### Community 1 - "AnalysisRun"
Cohesion: 0.08
Nodes (39): DeclarativeBase, SessionFactory, Candidate, CandidateStatus, DomainModel, HumanReview, BaseModel, Snapshot (+31 more)

### Community 2 - "analysis.js"
Cohesion: 0.06
Nodes (127): activateTab(), ACTIVE_COMMITTEE_STATUSES, ACTIVE_RUN_STATUSES, bindEvents(), elements, handleTabKeydown(), handleTaskAction(), loadMinutes() (+119 more)

### Community 3 - "EODSnapshot"
Cohesion: 0.09
Nodes (28): CandidateDiscoveryItem, CandidateDiscoveryResult, CandidateDiscoveryService, DiscoveryEODMetrics, DiscoveryVerdict, EODMarketDataClient, BaseModel, Exception (+20 more)

### Community 4 - "app.js"
Cohesion: 0.11
Nodes (85): addEvent(), agentStatusLabel(), announce(), asArray(), asObject(), bindEvents(), calculateProgress(), compactText() (+77 more)

### Community 5 - "YahooFinanceClient"
Cohesion: 0.14
Nodes (24): _atr(), _average_volume(), _EODBar, InvalidTickerError, normalize_us_ticker(), _optional_float(), _optional_int(), _optional_mapping() (+16 more)

### Community 6 - "test_api.py"
Cohesion: 0.07
Nodes (60): LogCaptureFixture, _log_background_task_failure(), _probe_codex(), Any, Task, 회수된 백그라운드 태스크의 예상 밖 예외를 서버 로그에 남긴다., fake_risk(), FakeMarketData (+52 more)

### Community 7 - "WorkItemService"
Cohesion: 0.11
Nodes (30): Lock, datetime, 도메인 객체의 기본 시각을 UTC로 생성한다., utc_now(), Any, BaseModel, UUID, 수동 업무를 역할별로 한 번에 하나만 실행하고 상태를 스냅샷으로 남긴다. (+22 more)

### Community 8 - "CommitteeBroker"
Cohesion: 0.10
Nodes (18): AwareDatetime, JsonDict, _ActiveMeeting, CommitteeBroker, CommitteeMeetingState, CommitteeMinutes, Any, JsonValue (+10 more)

### Community 9 - "office.js"
Cohesion: 0.08
Nodes (39): addTaskButton(), agentForRole(), agentStatus(), ApiRequestError, appendMinutesSection(), committeeClaims(), committeeEntries(), confidenceLabel() (+31 more)

### Community 10 - "._run_agent"
Cohesion: 0.10
Nodes (18): AnalysisWorkflow, AnalysisWorkflowView, LookupError, AnalysisRun, Self, InvestmentCommittee, Any, UUID (+10 more)

### Community 11 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 12 - "API"
Cohesion: 0.23
Nodes (26): applyCommittee(), committeeFromPayload(), committeeIdentifier(), committeeIsActive(), committeeStatusLabel(), handleScheduleAction(), handleTaskAction(), loadAgentTasks() (+18 more)

### Community 13 - "CodexProvider"
Cohesion: 0.15
Nodes (10): Process, AnalysisResult, EvidenceItem, Any, BaseModel, Path, Task, 모델이 선택한 사실 원장 식별자 하나만 받는다. (+2 more)

### Community 14 - "codex_provider.py"
Cohesion: 0.25
Nodes (4): EventCallback, CodexProtocolError, StreamReader, Raised when JSONL progress output violates the documented protocol.

### Community 15 - "setText"
Cohesion: 0.16
Nodes (26): announce(), applyProvider(), applyRun(), connectEvents(), interact(), loadInitialState(), openAgent(), openCommittee() (+18 more)

### Community 16 - "bindUi"
Cohesion: 0.13
Nodes (25): bindUi(), discoveryRunFromPayload(), discoveryRunId(), discoveryRunIsTerminal(), discoveryRunsFromPayload(), discoveryRunStatus(), finishCommittee(), handleDiscoverySelection() (+17 more)

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
Cohesion: 0.14
Nodes (52): AgentOutput, AgentOutputStatus, AgentRole, CandidateSource, Event, EventType, Evidence, StrEnum (+44 more)

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
Cohesion: 0.10
Nodes (41): calculate_valuation_metrics(), CompanyResearchError, _dart_filing_dates(), _dart_observed_date(), _dart_payload_items(), _dart_receipt_date(), _date_time(), _evidence_section() (+33 more)

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
Cohesion: 0.12
Nodes (20): Any, BaseModel, datetime, UUID, 기존 분석 서비스와 명시적으로 연결되는 호환 속성., 예약 시각이 된 분석을 한 번만 claim할 수 있게 조정한다., 대기 중인 분석 실행을 미래의 KST 시각에 한 번 예약한다., 최신 예약 상태를 예정 시각과 등록 순서 기준으로 반환한다. (+12 more)

### Community 47 - "research_contracts.py"
Cohesion: 0.16
Nodes (44): OfficialCompanyResearchClient, SEC와 DART의 공식 API만 사용해 회사 연구 자료를 수집한다., 충분한 입력으로만 계산한 재무 비율과 입력 공백., _SecMetricSpec, ValuationMetrics, EcosContextResult, EcosMacroContextClient, _Observation (+36 more)

### Community 48 - "CommitteeValidationError"
Cohesion: 0.26
Nodes (11): FakeProvider, Any, Exception, seed_completed_run(), test_directed_speak_calls_only_selected_role_and_respects_turn_cap(), test_directed_speak_failure_is_preserved_in_output_and_minutes(), test_existing_outputs_form_deterministic_ledger_and_minutes(), test_korean_meeting_uses_local_symbol_for_state_and_directed_speech() (+3 more)

### Community 49 - "test_orchestrator.py"
Cohesion: 0.16
Nodes (18): blocked_risk(), fake_risk(), make_committee(), Any, RiskFunction, test_agent_failure_is_persisted_without_reviewable_decision(), test_analysis_cannot_start_twice(), test_analysis_run_limit_caps_parallel_price_and_research_entry() (+10 more)

### Community 50 - "interact"
Cohesion: 0.25
Nodes (8): bindKeyboard(), bindMobileControls(), closeDialog(), collides(), frame(), movementVector(), nudgePlayer(), updatePlayer()

### Community 51 - "create_app"
Cohesion: 0.12
Nodes (36): BaseException, MacroSectionId, _at_utc_midnight(), _build_fact(), _build_official_fact(), _build_official_series(), _build_section(), _calculate_change() (+28 more)

### Community 52 - "test_price_gateway.py"
Cohesion: 0.12
Nodes (44): build_default_price_gateway(), KoreaPublicDataPriceProvider, KoreaYahooPriceProvider, Tiingo 공식 조정 일봉을 검증해 미국 시장 스냅샷으로 변환한다., 금융위원회 공공데이터 API에서 한국 주식 일봉을 조회한다., 한국 거래소 메타데이터를 검증한 Yahoo 일봉을 장애 대체로 제공한다., 권리가 확인된 미국 Tiingo와 한국 공공데이터 게이트웨이를 만든다., TiingoPriceProvider (+36 more)

### Community 53 - "price_gateway.py"
Cohesion: 0.13
Nodes (39): build_kr_eod_snapshot(), _decode_json(), _decode_korea_yahoo_result(), _decode_tiingo_mapping(), _decode_tiingo_payload(), _decode_tiingo_sequence(), _extract_korea_items(), InsufficientPriceDataError (+31 more)

### Community 54 - "InstrumentRef"
Cohesion: 0.13
Nodes (35): FactValue, EODSnapshot, BaseModel, Yahoo Finance의 완료된 일봉으로 만든 재현 가능한 시장 스냅샷., InstrumentRef, _agent_facts(), _build_price_part(), _build_quality() (+27 more)

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
Cohesion: 0.13
Nodes (28): MarketDataError, AsyncClient, Response, RuntimeError, Fetch and validate recent completed Yahoo Finance daily bars., 시장 데이터 조회 또는 변환 실패의 기본 예외., Yahoo Finance 응답이 실패했거나 계약과 다를 때 발생한다., 조회된 자산이 지원 대상인 미국 주식 또는 ETF가 아닐 때 발생한다. (+20 more)

### Community 61 - "InsufficientMarketDataError"
Cohesion: 0.09
Nodes (20): InsufficientMarketDataError, 현재가와 직전 종가조차 산출할 수 없을 때 발생한다., CommitteePriceGateway, FallbackPriceProvider, MarketPriceGateway, MissingPriceApiKeyError, PriceGatewayError, PriceProvider (+12 more)

### Community 62 - "MacroContextResult"
Cohesion: 0.12
Nodes (13): MacroContextResult, 시장 개요 조회도 같은 자료 수집 한도 안에서 실행한다., 4시간 캐시와 단일화를 적용해 공통 거시 자료를 시장별 보완 구역과 반환한다., _fred_result(), _korean_result(), _Pipeline, Exception, test_both_market_failures_return_degraded_overview_instead_of_raising() (+5 more)

### Community 63 - "ecos_context.py"
Cohesion: 0.20
Nodes (18): Cycle, _assemble_result(), _at_utc_midnight(), EcosSeriesSpec, _empty_result(), _failed_series(), _latest_observation(), _logical_error_code() (+10 more)

### Community 64 - "InstrumentIdentity"
Cohesion: 0.14
Nodes (15): Self, InstrumentIdentity, InstrumentIdentityError, normalize_instrument(), BaseModel, ValueError, 시장과 종목 식별자가 지원 계약과 맞지 않을 때 발생한다., 외부 표시 심볼과 기존 DB에 저장할 호환 티커를 함께 제공한다. (+7 more)

### Community 65 - "Storage"
Cohesion: 0.15
Nodes (4): ValueError, Protocol, UUID, Storage

### Community 66 - "test_macro_context.py"
Cohesion: 0.13
Nodes (9): build_ecos_unavailable_section(), ECOS 키가 없을 때 한국 고유 거시 구역을 명시적으로 사용 불가 처리한다., test_bls_monthly_baselines_cross_calendar_year_safely(), test_duplicate_treasury_failures_preserve_bls_axis(), test_fred_client_is_disabled_before_network_access(), test_missing_ecos_key_builds_required_unavailable_section(), test_official_client_rejects_naive_collection_time(), test_official_client_uses_origin_sources_and_blocks_unlicensed_axes() (+1 more)

### Community 67 - "test_ecos_context.py"
Cohesion: 0.20
Nodes (11): Request, _mock_client(), _payload(), Any, AsyncClient, Response, test_fetch_uses_verified_codes_and_builds_complete_official_section(), test_http_and_logical_errors_block_without_exposing_key_or_remote_message() (+3 more)

### Community 68 - "datetime"
Cohesion: 0.20
Nodes (4): build_default_committee_price_gateway(), AsyncClient, datetime, 앱 기본 설정을 기존 투자위원회가 바로 사용할 가격 클라이언트로 만든다.

### Community 69 - "submitDiscoveryScreen"
Cohesion: 0.20
Nodes (12): verdictLabel(), appendDiscoveryList(), candidateScore(), candidateTicker(), discoveryFromPayload(), discoveryStrategyLabel(), discoveryVerdictLabel(), renderDiscovery() (+4 more)

### Community 70 - "Self"
Cohesion: 0.24
Nodes (5): ModelT, Self, _require_known_refs(), _require_unique(), _unique_by_id()

### Community 71 - "build_codex_child_environment"
Cohesion: 0.50
Nodes (3): build_codex_child_environment(), 코덱스 인증과 실행에 필요한 비민감 환경 변수만 전달한다., 코덱스 인증과 실행에 필요한 비민감 환경 변수만 반환한다.

## Knowledge Gaps
- **80 isolated node(s):** `investment-office`, `elements`, `state`, `elements`, `state` (+75 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MarketId` connect `MarketId` to `Snapshot`, `InstrumentIdentity`, `EODSnapshot`, `test_api.py`, `._run_agent`, `research_contracts.py`, `submitDiscoveryScreen`, `price_gateway.py`, `test_price_gateway.py`, `InstrumentRef`, `SourceId`, `test_scheduled_analysis.py`, `MarketRegimeEvaluator`, `YahooFinanceClient`, `InsufficientMarketDataError`, `MacroContextResult`, `ResearchPipeline`?**
  _High betweenness centrality (0.096) - this node is a cross-community bridge._
- **Why does `CodexProvider` connect `test_codex_provider.py` to `Snapshot`, `build_codex_child_environment`, `CodexProvider`, `codex_provider.py`, `FakeStdin`, `CodexProcessError`?**
  _High betweenness centrality (0.073) - this node is a cross-community bridge._
- **Why does `YahooFinanceClient` connect `YahooFinanceClient` to `Snapshot`, `AnalysisRun`, `datetime`, `YahooFinanceClient`, `test_api.py`, `research_contracts.py`, `test_orchestrator.py`, `test_price_gateway.py`, `price_gateway.py`, `submitDiscoveryScreen`, `InsufficientMarketDataError`?**
  _High betweenness centrality (0.067) - this node is a cross-community bridge._
- **Are the 94 inferred relationships involving `MarketId` (e.g. with `AnalyzeRequest` and `CommitteeCommandRequest`) actually correct?**
  _`MarketId` has 94 INFERRED edges - model-reasoned connections that need verification._
- **Are the 54 inferred relationships involving `InstrumentRef` (e.g. with `CompanyResearchError` and `CompanyResearchResult`) actually correct?**
  _`InstrumentRef` has 54 INFERRED edges - model-reasoned connections that need verification._
- **Are the 86 inferred relationships involving `Snapshot` (e.g. with `_ActiveMeeting` and `_ClaimAccumulator`) actually correct?**
  _`Snapshot` has 86 INFERRED edges - model-reasoned connections that need verification._
- **Are the 83 inferred relationships involving `AnalysisRunStatus` (e.g. with `AnalyzeRequest` and `CommitteeCommandRequest`) actually correct?**
  _`AnalysisRunStatus` has 83 INFERRED edges - model-reasoned connections that need verification._