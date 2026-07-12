// 전체시장 종목추천 작업의 단계별 진행과 복수 심층분석, 서버 완료 이력을 관리한다.
import {
  API,
  appendMarketBadge,
  appendStatusBadge,
  asArray,
  asObject,
  clearElement,
  compactText,
  createElement,
  formatDateTime,
  initSiteShell,
  requestJson,
  runProgress,
  safeSourceUrl,
  setButtonBusy,
  setFeedback,
  setText,
  startSiteOperation,
  statusInfo,
} from "./site-common.js?v=7";

const DISCOVERY_SCAN_ENDPOINT = "/api/discoveries/scans";
const SCAN_POLL_INTERVAL = 900;
const BACKEND_STAGES = ["universe", "fundamentals", "liquidity", "sector", "ranking"];
const SCAN_TERMINAL = new Set(["complete", "partial", "failed"]);

const elements = {
  screenForm: document.querySelector("#discovery-screen-form"),
  screenButton: document.querySelector('#discovery-screen-form button[type="submit"]'),
  market: document.querySelector("#discovery-market"),
  strategy: document.querySelector("#discovery-strategy"),
  riskProfile: document.querySelector("#discovery-risk-profile"),
  feedback: document.querySelector("#discovery-feedback"),
  universe: document.querySelector("#discovery-universe"),
  fundamentals: document.querySelector("#discovery-fundamentals"),
  liquidity: document.querySelector("#discovery-liquidity"),
  shortlist: document.querySelector("#discovery-shortlist"),
  candidateList: document.querySelector("#discovery-candidate-list"),
  selection: document.querySelector("#discovery-selection"),
  analyzeForm: document.querySelector("#discovery-analyze-form"),
  analyzeButton: document.querySelector("#discovery-analyze"),
  runList: document.querySelector("#discovery-run-list"),
  runFeedback: document.querySelector("#discovery-run-feedback"),
  live: document.querySelector("#site-live-region"),
};

const state = {
  discovery: null,
  runs: [],
  latestBatchId: null,
  pollTimer: null,
  scanPollTimer: null,
  scanJobId: null,
  scanJob: null,
  scanPollFailures: 0,
  scanOperation: null,
  eventRefreshTimer: null,
  loading: false,
};

const ACTIVE = new Set(["queued", "running"]);
const DECIDED = new Set(["approved", "rejected", "hold", "complete"]);

function marketLabel(market) {
  return market === "kr" ? "한국" : "미국";
}

function setStage(stage, status, label) {
  const element = document.querySelector(`[data-discovery-stage="${stage}"]`);
  if (!element) return;
  element.dataset.status = status;
  element.setAttribute("aria-busy", String(["active", "running"].includes(status)));
  if (["done", "completed"].includes(status)) element.style.setProperty("--stage-progress", "1");
  else if (["idle", "error", "failed", "blocked"].includes(status)) element.style.setProperty("--stage-progress", "0");
  setText(element.querySelector("output"), label, "대기");
}

function numericCount(value) {
  const count = Number(value);
  return Number.isFinite(count) && count >= 0 ? count : 0;
}

function backendStage(job, stageName) {
  return asArray(job?.stages).find((stage) => stage?.stage === stageName) || null;
}

function setStageField(element, field, value) {
  setText(element?.querySelector(`[data-stage-field="${field}"]`), value, "0");
}

function renderBackendStage(job, stageName) {
  const element = document.querySelector(`[data-discovery-stage="${stageName}"]`);
  if (!element) return;
  const stage = backendStage(job, stageName);
  const total = numericCount(stage?.total);
  const processed = numericCount(stage?.processed);
  const passed = numericCount(stage?.passed);
  const failed = numericCount(stage?.failed);
  const cached = numericCount(stage?.cached);
  const jobStatus = String(job?.status || "queued").toLowerCase();
  const currentStage = String(job?.current_stage || "");
  const completed = Boolean(stage?.completed_at);
  const started = Boolean(stage?.started_at) || currentStage === stageName;
  const firstIncompleteStage = BACKEND_STAGES.find(
    (name) => !backendStage(job, name)?.completed_at,
  ) || currentStage || "ranking";
  const failedStage = currentStage || firstIncompleteStage;
  const failedHere = jobStatus === "failed" && failedStage === stageName;
  const partialHere = jobStatus === "partial" && stageName === "ranking";
  const progress = total > 0 ? Math.min(1, processed / total) : Number(completed);

  let status = "idle";
  let label = "대기";
  if (failedHere) {
    status = "error";
    label = "자료 오류";
  } else if (partialHere) {
    status = "partial";
    label = `${processed} / ${total || "—"}`;
  } else if (completed) {
    status = "done";
    label = `${processed} / ${total || processed}`;
  } else if (started && !SCAN_TERMINAL.has(jobStatus)) {
    status = "active";
    label = `${processed} / ${total || "—"}`;
  } else if (jobStatus === "failed" || jobStatus === "partial") {
    status = "blocked";
    label = "중단";
  }

  setStage(stageName, status, label);
  element.style.setProperty("--stage-progress", String(progress));
  setStageField(element, "processed", `${processed} / ${total || "—"}`);
  setStageField(element, "passed", String(passed));
  setStageField(element, "failed", String(failed));
  setStageField(element, "cached", String(cached));
  setText(
    element.querySelector("[data-stage-message]"),
    failedHere
      ? job?.error || job?.message || stage?.message
      : stage?.message || "작업 대기 중",
    "작업 대기 중",
  );
}

function renderBackendStages(job) {
  BACKEND_STAGES.forEach((stageName) => renderBackendStage(job, stageName));
}

function resetBackendStages() {
  BACKEND_STAGES.forEach((stageName) => {
    const element = document.querySelector(`[data-discovery-stage="${stageName}"]`);
    setStage(stageName, "idle", "대기");
    setStageField(element, "processed", "0 / —");
    setStageField(element, "passed", "0");
    setStageField(element, "failed", "0");
    setStageField(element, "cached", "0");
    setText(element?.querySelector("[data-stage-message]"), "작업 대기 중");
  });
}

function updateScanMetrics(job, discovery = null) {
  const universe = backendStage(job, "universe");
  const fundamentals = backendStage(job, "fundamentals");
  const liquidity = backendStage(job, "liquidity");
  const ranking = backendStage(job, "ranking");
  const candidates = asArray(discovery?.candidates);
  const universeTotal = universe
    ? numericCount(universe.completed_at ? universe.passed : universe.total)
    : numericCount(discovery?.universe_size);
  const fundamentalsPassed = fundamentals
    ? numericCount(fundamentals.passed)
    : numericCount(discovery?.fundamentals_passed_count || discovery?.financial_passed_count);
  const liquidityPassed = liquidity
    ? numericCount(liquidity.passed)
    : numericCount(discovery?.liquidity_passed_count || discovery?.evaluated_count);
  const hasFinalCandidates = discovery !== null && Object.hasOwn(discovery, "candidates");
  const shortlistCount = hasFinalCandidates ? candidates.length : numericCount(ranking?.passed);
  setText(elements.universe, universeTotal || "—");
  setText(elements.fundamentals, fundamentalsPassed || (universeTotal ? "0" : "—"));
  setText(elements.liquidity, liquidityPassed || (universeTotal ? "0" : "—"));
  setText(elements.shortlist, shortlistCount || (SCAN_TERMINAL.has(String(job?.status || "")) ? "0" : "—"));
}

function selectedTickers() {
  return Array.from(elements.candidateList?.querySelectorAll('input[name="discovery-ticker"]:checked') || [])
    .map((input) => input.value)
    .filter(Boolean);
}

function selectedCompanyNames() {
  return Array.from(elements.candidateList?.querySelectorAll('input[name="discovery-ticker"]:checked') || [])
    .map((input) => input.dataset.companyName || input.value)
    .filter(Boolean);
}

function updateSelection(changedInput = null) {
  let selected = selectedTickers();
  if (changedInput?.checked && selected.length > 3) {
    changedInput.checked = false;
    selected = selectedTickers();
    setFeedback(elements.feedback, "심층분석 후보는 최대 3개까지 선택할 수 있습니다.", "error");
  }
  setText(elements.selection, `${selected.length} / 3 선택`);
  if (elements.analyzeButton) elements.analyzeButton.disabled = selected.length === 0 || state.loading;
}

function verdictLabel(verdict) {
  return {
    review_first: "우선 검토",
    watch: "관찰 후보",
    exclude: "기준 미충족",
  }[String(verdict || "watch")] || "관찰 후보";
}

function formattedScore(value) {
  const rawValue = value && typeof value === "object" ? value.score ?? value.value : value;
  const score = Number(rawValue);
  return Number.isFinite(score) ? score.toFixed(1) : null;
}

function firstScore(...values) {
  return values.map(formattedScore).find((value) => value !== null) || null;
}

function scoreBreakdown(candidate) {
  const breakdown = asObject(candidate.breakdown || candidate.score_breakdown || candidate.scores);
  return [
    ["재무", firstScore(breakdown.financial, breakdown.fundamentals, breakdown.financial_strength)],
    ["성장", firstScore(breakdown.growth, breakdown.execution)],
    ["업종", firstScore(breakdown.sector, breakdown.industry, breakdown.industry_momentum)],
    ["업종전망", firstScore(breakdown.outlook, breakdown.industry_outlook)],
    ["차트", firstScore(breakdown.chart, breakdown.technical, breakdown.momentum)],
  ].filter(([, value]) => value !== null);
}

function renderCandidateEmpty(message, detail = "스캔을 시작하면 비교 카드가 표시됩니다.", tone = "idle") {
  clearElement(elements.candidateList);
  const empty = createElement("li", `empty-state candidate-empty is-${tone}`);
  empty.append(createElement("strong", "", message), createElement("span", "", detail));
  elements.candidateList?.append(empty);
  updateSelection();
}

function renderCandidates(candidates, emptyState = null) {
  clearElement(elements.candidateList);
  const values = asArray(candidates).slice(0, 8);
  if (!values.length) {
    renderCandidateEmpty(
      emptyState?.message || "추천 후보 찾기를 실행하세요.",
      emptyState?.detail,
      emptyState?.tone,
    );
    return;
  }
  values.forEach((candidate, index) => {
    const ticker = String(candidate.ticker || candidate.symbol || "").toUpperCase();
    const companyName = String(candidate.company_name || "").trim() || ticker || "종목 미정";
    const item = createElement("li", "candidate-card");
    const label = createElement("label", "candidate-card__select");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.name = "discovery-ticker";
    checkbox.value = ticker;
    checkbox.checked = index < 3;
    checkbox.dataset.companyName = companyName;
    checkbox.setAttribute("aria-label", `${companyName} (${ticker}) 심층 분석 후보 선택`);
    const identity = createElement("span", "candidate-card__identity");
    identity.append(createElement("small", "", `RANK ${candidate.rank ?? index + 1} · ${verdictLabel(candidate.verdict)}`));
    identity.append(createElement("strong", "candidate-card__name", companyName));
    const identityMeta = createElement("span", "candidate-card__meta");
    identityMeta.append(createElement("span", "candidate-card__symbol", ticker || "코드 미정"));
    appendMarketBadge(identityMeta, candidate.market || state.discovery?.market, ticker);
    identity.append(identityMeta);
    const score = createElement("span", "candidate-card__score", formattedScore(candidate.score) || "—");
    label.append(checkbox, identity, score);
    item.append(label);

    const breakdown = scoreBreakdown(candidate);
    if (breakdown.length) {
      const scoreGrid = createElement("dl", "candidate-card__breakdown");
      scoreGrid.setAttribute("aria-label", `${companyName} 세부 평가 점수`);
      breakdown.forEach(([name, value]) => {
        const metric = createElement("div");
        metric.append(createElement("dt", "", name), createElement("dd", "mono", value));
        scoreGrid.append(metric);
      });
      item.append(scoreGrid);
    }

    const comparison = createElement("div", "candidate-card__comparison");
    const reason = createElement("section");
    reason.append(createElement("h3", "", "선별 근거"));
    reason.append(createElement("p", "", compactText(asArray(candidate.reasons || candidate.key_points)[0], 145) || "근거 요약 없음"));
    const risk = createElement("section");
    risk.append(createElement("h3", "", "위험 신호"));
    risk.append(createElement("p", "", compactText(asArray(candidate.risks)[0], 145) || "위험 신호 미보고"));
    comparison.append(reason, risk);
    item.append(comparison);

    const sourceUrl = safeSourceUrl(candidate.source_url || candidate.source);
    if (sourceUrl) {
      const source = createElement("a", "candidate-card__source", "근거 자료 출처 확인 ↗");
      source.href = sourceUrl;
      source.target = "_blank";
      source.rel = "noreferrer";
      item.append(source);
    }
    elements.candidateList?.append(item);
  });
  updateSelection();
}

function renderDiscovery(discovery, job = state.scanJob, emptyState = null) {
  state.discovery = discovery;
  const candidates = asArray(discovery?.candidates);
  updateScanMetrics(job, discovery);
  renderCandidates(
    candidates,
    emptyState || {
      message: "기준을 모두 통과한 후보가 없습니다.",
      detail: "선택한 위험성향과 각 단계의 미통과 수를 확인하세요.",
      tone: "complete",
    },
  );
  setStage("agents", "idle", candidates.length ? "선택 대기" : "후보 없음");
  setStage("review", "idle", "분석 대기");
}

function latestBatchRuns() {
  if (!state.runs.length) return [];
  const firstBatch = state.runs.find((run) => run.discovery_batch_id)?.discovery_batch_id || null;
  state.latestBatchId = firstBatch;
  if (firstBatch) return state.runs.filter((run) => run.discovery_batch_id === firstBatch);
  return state.runs.slice(0, 3);
}

function renderStagesFromRuns() {
  const batch = latestBatchRuns();
  if (!batch.length) return;
  const active = batch.filter((run) => ACTIVE.has(run.status)).length;
  const failed = batch.filter((run) => run.status === "failed").length;
  const review = batch.filter((run) => run.status === "review").length;
  const decided = batch.filter((run) => DECIDED.has(run.status)).length;
  if (active) setStage("agents", "active", `${batch.length - active} / ${batch.length}`);
  else if (failed === batch.length) setStage("agents", "error", "전체 실패");
  else setStage("agents", failed ? "error" : "done", `${batch.length - failed} / ${batch.length}`);
  if (review) setStage("review", "active", `${review}건 대기`);
  else if (decided) setStage("review", "done", `${decided}건 기록`);
  else if (failed && !active) setStage("review", "error", "검토 불가");
  else setStage("review", "idle", "분석 대기");
}

function renderRuns() {
  const focusedControl = document.activeElement;
  const focusedRunId = focusedControl instanceof HTMLElement && elements.runList?.contains(focusedControl)
    ? focusedControl.dataset.runId
    : null;
  const focusedAction = focusedControl instanceof HTMLElement ? focusedControl.dataset.runAction : null;
  clearElement(elements.runList);
  if (!state.runs.length) {
    elements.runList?.append(createElement("li", "empty-state", "서버에 저장된 종목추천 심층분석 내역이 없습니다."));
    setFeedback(elements.runFeedback, "새 추천 배치를 시작하면 진행률과 완료 이력이 여기에 쌓입니다.");
    return;
  }
  const currentBatch = new Set(latestBatchRuns().map((run) => run.run_id));
  state.runs.forEach((run) => {
    const item = createElement("li", "discovery-run-card");
    if (currentBatch.has(run.run_id)) item.dataset.latest = "true";
    const head = createElement("div", "discovery-run-card__header");
    const storedCompanyName = String(run.company_name || "").trim();
    const ticker = String(run.ticker || "").trim();
    const companyName = storedCompanyName || ticker || "종목 미정";
    const identity = createElement("span", "discovery-run-card__identity");
    identity.append(createElement("strong", "", companyName));
    if (storedCompanyName && ticker && storedCompanyName.toUpperCase() !== ticker.toUpperCase()) {
      identity.append(createElement("small", "", ticker));
    }
    head.append(identity);
    appendMarketBadge(head, run.market, run.ticker);
    appendStatusBadge(head, run.status);
    if (currentBatch.has(run.run_id)) head.append(createElement("span", "batch-badge", "최근 배치"));
    const progress = runProgress(run);
    const progressLine = createElement("div", "run-progress");
    const track = createElement("div", "progress-track");
    track.setAttribute("role", "progressbar");
    track.setAttribute("aria-label", `${companyName} (${run.ticker || "코드 미정"}) 심층 분석 진행률`);
    track.setAttribute("aria-valuenow", String(progress));
    track.setAttribute("aria-valuemin", "0");
    track.setAttribute("aria-valuemax", "100");
    const bar = createElement("span", "progress-track__bar");
    bar.style.width = `${progress}%`;
    track.append(bar);
    progressLine.append(track, createElement("strong", "", `${progress}%`));
    const meta = createElement("p", "discovery-run-card__meta", `${formatDateTime(run.completed_at || run.created_at)} · ${run.message || "상세 확인"}`);
    const actions = createElement("div", "discovery-run-card__actions");
    const detail = createElement("a", "button button--secondary", run.status === "review" ? "사람 검토 열기" : "상세 워크벤치");
    detail.href = `/analysis?run=${encodeURIComponent(run.run_id)}`;
    detail.dataset.runId = run.run_id;
    detail.dataset.runAction = "detail";
    const history = createElement("a", "text-link", "완료 이력에서 보기");
    history.href = `/history?run=${encodeURIComponent(run.run_id)}`;
    history.dataset.runId = run.run_id;
    history.dataset.runAction = "history";
    actions.append(detail, history);
    item.append(head, progressLine, meta, actions);
    elements.runList?.append(item);
  });
  if (focusedRunId && focusedAction) {
    const restoredControl = Array.from(elements.runList?.querySelectorAll("[data-run-id][data-run-action]") || [])
      .find((control) => control.dataset.runId === focusedRunId && control.dataset.runAction === focusedAction);
    restoredControl?.focus({ preventScroll: true });
  }
  setFeedback(elements.runFeedback, `서버에 저장된 추천 심층분석 ${state.runs.length}건을 표시합니다.`, "success");
  renderStagesFromRuns();
}

function stopPolling() {
  if (state.pollTimer) window.clearTimeout(state.pollTimer);
  state.pollTimer = null;
}

function schedulePolling(delay = 2_800) {
  stopPolling();
  if (!state.runs.some((run) => ACTIVE.has(run.status))) return;
  state.pollTimer = window.setTimeout(loadRuns, delay);
}

function scheduleEventRefresh() {
  if (state.eventRefreshTimer) window.clearTimeout(state.eventRefreshTimer);
  state.eventRefreshTimer = window.setTimeout(() => {
    state.eventRefreshTimer = null;
    void loadRuns();
  }, 350);
}

async function loadRuns() {
  try {
    const payload = await requestJson(`${API.runs}?workflow=discovery&limit=200`);
    state.runs = asArray(payload.runs);
    renderRuns();
    schedulePolling();
  } catch (error) {
    setFeedback(elements.runFeedback, `추천 분석 이력 조회 실패. ${error.message}`, "error");
    if (state.runs.some((run) => ACTIVE.has(run.status))) schedulePolling(5_000);
  }
}

function stopScanPolling() {
  if (state.scanPollTimer) window.clearTimeout(state.scanPollTimer);
  state.scanPollTimer = null;
}

function scheduleScanPolling(delay = SCAN_POLL_INTERVAL) {
  stopScanPolling();
  if (!state.scanJobId) return;
  state.scanPollTimer = window.setTimeout(pollScanJob, delay);
}

function scanJobPayload(payload) {
  return asObject(payload?.job || payload);
}

function currentScanSummary(job) {
  const stageName = String(job?.current_stage || "universe");
  const stage = backendStage(job, stageName);
  const processed = numericCount(stage?.processed);
  const total = numericCount(stage?.total);
  return stage?.message || `${stageName} 단계에서 ${processed} / ${total || "—"}개를 처리하고 있습니다.`;
}

function releaseScanControls() {
  state.loading = false;
  state.scanJobId = null;
  stopScanPolling();
  setButtonBusy(elements.screenButton, false);
  setFormDisabled(elements.screenForm, false);
  updateSelection();
}

function finishScanJob(job) {
  const status = String(job?.status || "failed").toLowerCase();
  const result = asObject(job?.result);
  const detail = compactText(job?.error || job?.message, 260)
    || "공급원 또는 처리 단계의 상세 오류가 보고되지 않았습니다.";
  const operation = state.scanOperation;

  if (status === "failed") {
    state.discovery = null;
    updateScanMetrics(job);
    renderCandidateEmpty(
      "전체시장 스캔을 완료하지 못했습니다.",
      `${detail} 단계별 실패 수와 공급원 상태를 확인한 뒤 다시 실행하세요.`,
      "failed",
    );
    setStage("agents", "error", "선별 실패");
    setStage("review", "error", "검토 불가");
    setFeedback(elements.feedback, `후보 스캔 실패. ${detail}`, "error");
    operation?.fail(`전체시장 후보 스캔이 실패했습니다. ${detail}`);
  } else if (status === "partial") {
    renderDiscovery(result, job, {
      message: "자료 공백으로 후보를 확정하지 못했습니다.",
      detail: `${detail} 현재 표시값을 정상 완료 결과로 해석하지 마세요.`,
      tone: "partial",
    });
    setFeedback(elements.feedback, `후보 스캔 일부 완료. ${detail}`, "warning");
    operation?.warn(`일부 공급원 또는 종목 자료가 누락됐습니다. ${detail}`);
  } else {
    renderDiscovery(result, job);
    const count = asArray(result.candidates).length;
    const message = count
      ? `${marketLabel(result.market)} 전체시장에서 심층검토 후보 ${count}개를 선별했습니다.`
      : "모든 단계를 정상 완료했지만 현재 기준을 모두 통과한 후보는 없습니다.";
    setFeedback(elements.feedback, message, count ? "success" : "neutral");
    operation?.succeed(message);
  }

  state.scanOperation = null;
  releaseScanControls();
}

function renderScanJob(job) {
  state.scanJob = job;
  renderBackendStages(job);
  updateScanMetrics(job, asObject(job?.result));
  const status = String(job?.status || "queued").toLowerCase();
  if (SCAN_TERMINAL.has(status)) {
    finishScanJob(job);
    return;
  }
  const summary = status === "queued"
    ? "전체시장 스캔이 대기열에 등록됐습니다. 실행 순서를 기다리고 있습니다."
    : currentScanSummary(job);
  setFeedback(elements.feedback, summary);
  state.scanOperation?.update(summary);
}

async function pollScanJob() {
  const jobId = state.scanJobId;
  if (!jobId) return;
  try {
    const payload = await requestJson(
      `${DISCOVERY_SCAN_ENDPOINT}/${encodeURIComponent(jobId)}`,
      {},
      15_000,
    );
    state.scanPollFailures = 0;
    renderScanJob(scanJobPayload(payload));
    if (state.scanJobId) scheduleScanPolling();
  } catch (error) {
    state.scanPollFailures += 1;
    const message = `스캔 상태 조회 ${state.scanPollFailures}회 실패. ${error.message}`;
    setFeedback(elements.feedback, message, "warning");
    state.scanOperation?.update(message);
    if (state.scanPollFailures < 3) {
      scheduleScanPolling(SCAN_POLL_INTERVAL * 2);
      return;
    }
    renderCandidateEmpty(
      "진행 상태 연결이 끊겼습니다.",
      "서버 작업의 성공 여부를 확인하지 못했으므로 정상 완료로 처리하지 않았습니다.",
      "failed",
    );
    setStage(String(state.scanJob?.current_stage || "universe"), "error", "조회 중단");
    state.scanOperation?.warn("전체시장 스캔 상태 연결이 끊겨 결과 확인을 중단했습니다.");
    state.scanOperation = null;
    releaseScanControls();
  }
}

async function submitScreen(event) {
  event.preventDefault();
  if (state.loading) return;
  state.loading = true;
  state.discovery = null;
  state.scanJob = null;
  state.scanPollFailures = 0;
  stopScanPolling();
  setFormDisabled(elements.screenForm, true);
  updateSelection();
  resetBackendStages();
  renderCandidateEmpty(
    "전체시장 원장을 구성하고 있습니다.",
    "재무, 가격·유동성, 업종, 최종 순위 단계가 실시간으로 갱신됩니다.",
    "running",
  );
  setStage("agents", "idle", "선별 대기");
  setStage("review", "idle", "분석 대기");
  const market = elements.market?.value === "kr" ? "kr" : "us";
  const strategy = elements.strategy?.value || "balanced";
  const riskProfile = elements.riskProfile?.value || "balanced";
  state.scanOperation = startSiteOperation({
    key: "discovery-screen",
    title: `${marketLabel(market)} 전체시장 후보 스캔`,
    detail: "전체 상장 보통주 원장을 구성하고 단계별 필터를 준비하고 있습니다.",
  });
  setButtonBusy(elements.screenButton, true, "전체시장 처리 중");
  setFeedback(elements.feedback, `${marketLabel(market)} 전체 상장 보통주 원장을 요청했습니다.`);
  try {
    const payload = await requestJson(DISCOVERY_SCAN_ENDPOINT, {
      method: "POST",
      body: JSON.stringify({ market, strategy, risk_profile: riskProfile, limit: 8 }),
    }, 20_000);
    const job = scanJobPayload(payload);
    if (!job.id) throw new Error("스캔 작업 번호가 생성되지 않았습니다.");
    state.scanJobId = String(job.id);
    renderScanJob(job);
    if (state.scanJobId) scheduleScanPolling();
  } catch (error) {
    setStage("universe", "error", "요청 실패");
    renderCandidateEmpty(
      "전체시장 스캔을 시작하지 못했습니다.",
      error.message,
      "failed",
    );
    setFeedback(elements.feedback, `후보 선별 요청 실패. ${error.message}`, "error");
    state.scanOperation?.fail(`전체시장 후보 선별 요청이 실패했습니다. ${error.message}`);
    state.scanOperation = null;
    releaseScanControls();
  }
}

function setFormDisabled(form, disabled) {
  form?.setAttribute("aria-busy", String(disabled));
  form?.querySelectorAll("input, select, button").forEach((control) => { control.disabled = disabled; });
}

async function submitAnalysis(event) {
  event.preventDefault();
  if (state.loading) return;
  const tickers = selectedTickers();
  if (!tickers.length || tickers.length > 3) {
    setFeedback(elements.feedback, "심층분석 후보를 1개 이상 3개 이하로 선택하세요.", "error");
    return;
  }
  state.loading = true;
  elements.analyzeForm?.setAttribute("aria-busy", "true");
  const selectedNames = selectedCompanyNames();
  const selectionLabel = selectedNames.join(", ") || tickers.join(", ");
  const operation = startSiteOperation({
    title: `${selectionLabel} 심층 분석`,
    detail: "선택 종목을 투자팀에 배정하고 분석 실행 번호를 만들고 있습니다.",
  });
  if (elements.analyzeButton) elements.analyzeButton.disabled = true;
  setButtonBusy(elements.analyzeButton, true, "투자팀 배정 중");
  elements.candidateList?.querySelectorAll("input").forEach((input) => { input.disabled = true; });
  setStage("agents", "active", "배정 중");
  setFeedback(elements.feedback, `${selectionLabel} 심층분석을 여섯 에이전트에게 배정하고 있습니다.`);
  try {
    const market = state.discovery?.market === "kr" ? "kr" : "us";
    const payload = await requestJson(API.discoveryAnalyze, {
      method: "POST",
      body: JSON.stringify({ market, tickers }),
    }, 45_000);
    const created = asArray(payload.runs);
    state.latestBatchId = created[0]?.discovery_batch_id || null;
    const runIds = created.map((run) => run.run_id).filter(Boolean);
    if (!runIds.length) throw new Error("분석 실행 번호가 생성되지 않았습니다.");
    operation.trackRuns(runIds, `${created.length}개 종목을 접수했습니다. 에이전트 분석 진행을 실시간으로 추적합니다.`);
    setFeedback(elements.feedback, `${created.length}개 종목을 접수했습니다. 아래 실행 카드에서 에이전트 진행 상태를 확인하세요. 자동 주문은 생성되지 않습니다.`);
    await loadRuns();
  } catch (error) {
    setStage("agents", "error", "배정 실패");
    setFeedback(elements.feedback, `심층분석 시작 실패. ${error.message}`, "error");
    operation.fail(`심층분석을 시작하지 못했습니다. ${error.message}`);
  } finally {
    state.loading = false;
    elements.analyzeForm?.setAttribute("aria-busy", "false");
    setButtonBusy(elements.analyzeButton, false);
    elements.candidateList?.querySelectorAll("input").forEach((input) => { input.disabled = false; });
    updateSelection();
  }
}

elements.screenForm?.addEventListener("submit", submitScreen);
elements.analyzeForm?.addEventListener("submit", submitAnalysis);
function resetDiscoverySelection() {
  if (state.loading) return;
  state.discovery = null;
  state.scanJob = null;
  renderCandidateEmpty(
    "새 조건으로 스캔할 준비가 됐습니다.",
    "전체 상장 보통주 원장에서 다시 시작합니다.",
  );
  setText(elements.universe, "—");
  setText(elements.fundamentals, "—");
  setText(elements.liquidity, "—");
  setText(elements.shortlist, "—");
  resetBackendStages();
  ["agents", "review"].forEach((stage) => setStage(stage, "idle", "대기"));
  const market = elements.market?.value === "kr" ? "kr" : "us";
  setFeedback(elements.feedback, `${marketLabel(market)} 전체시장 조건이 변경됐습니다. 후보 스캔을 다시 실행하세요.`);
}

[elements.market, elements.strategy, elements.riskProfile].forEach((control) => {
  control?.addEventListener("change", resetDiscoverySelection);
});
elements.candidateList?.addEventListener("change", (event) => {
  const input = event.target.closest('input[name="discovery-ticker"]');
  if (input instanceof HTMLInputElement) updateSelection(input);
});
window.addEventListener("beforeunload", () => {
  stopPolling();
  stopScanPolling();
  if (state.eventRefreshTimer) window.clearTimeout(state.eventRefreshTimer);
});

resetBackendStages();
renderCandidateEmpty(
  "추천 후보 스캔을 시작하세요.",
  "미국 전체 상장 보통주 또는 한국 KOSPI·KOSDAQ 전체 보통주에서 단계별로 후보를 좁힙니다.",
);
await initSiteShell((_payload, eventType) => {
  if (["run", "analysis", "agent", "review", "fault"].includes(eventType)) scheduleEventRefresh();
});
await loadRuns();
