// 종목추천 페이지에서 1차 선별과 복수 심층분석, 서버 기반 완료 이력을 관리한다.
import {
  API,
  appendMarketBadge,
  appendStatusBadge,
  asArray,
  asObject,
  clearElement,
  classifyDiscoveryOutcome,
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
} from "./site-common.js?v=6";

const elements = {
  screenForm: document.querySelector("#discovery-screen-form"),
  screenButton: document.querySelector('#discovery-screen-form button[type="submit"]'),
  market: document.querySelector("#discovery-market"),
  strategy: document.querySelector("#discovery-strategy"),
  feedback: document.querySelector("#discovery-feedback"),
  universe: document.querySelector("#discovery-universe"),
  qualified: document.querySelector("#discovery-qualified"),
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
  setText(element.querySelector("output"), label, "대기");
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

function renderCandidates(candidates) {
  clearElement(elements.candidateList);
  const values = asArray(candidates).slice(0, 8);
  if (!values.length) {
    elements.candidateList?.append(createElement("li", "empty-state", "추천 후보 찾기를 실행하면 비교 카드가 표시됩니다."));
    updateSelection();
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
    const score = createElement("span", "candidate-card__score", Number.isFinite(Number(candidate.score)) ? Number(candidate.score).toFixed(2) : "—");
    label.append(checkbox, identity, score);
    item.append(label);

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
      const source = createElement("a", "candidate-card__source", "가격 데이터 출처 확인 ↗");
      source.href = sourceUrl;
      source.target = "_blank";
      source.rel = "noreferrer";
      item.append(source);
    }
    elements.candidateList?.append(item);
  });
  updateSelection();
}

function renderDiscovery(discovery) {
  state.discovery = discovery;
  const candidates = asArray(discovery?.candidates);
  setText(elements.universe, discovery?.universe_size, "—");
  setText(elements.qualified, discovery?.qualified_count, "—");
  setText(elements.shortlist, candidates.length, "0");
  renderCandidates(candidates);
  const universeSize = Number(discovery?.universe_size || 0);
  const evaluatedCount = Number(discovery?.evaluated_count || 0);
  setStage("scan", evaluatedCount > 0 ? "done" : "error", `${evaluatedCount} / ${universeSize || 30}`);
  setStage("shortlist", evaluatedCount > 0 ? "done" : "error", evaluatedCount > 0 ? `${candidates.length}개` : "평가 불가");
  setStage("agents", "idle", candidates.length ? "선택 대기" : evaluatedCount > 0 ? "후보 없음" : "스캔 실패");
  setStage("review", "idle", "분석 대기");
  return classifyDiscoveryOutcome(discovery);
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
  if (!state.discovery) {
    setStage("scan", "done", "이전 실행");
    setStage("shortlist", "done", `${batch.length}개 선택`);
  }
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

async function submitScreen(event) {
  event.preventDefault();
  if (state.loading) return;
  state.loading = true;
  setFormDisabled(elements.screenForm, true);
  updateSelection();
  const market = elements.market?.value === "kr" ? "kr" : "us";
  const strategy = elements.strategy?.value || "balanced";
  const operation = startSiteOperation({
    key: "discovery-screen",
    title: `${marketLabel(market)} 추천 후보 스캔`,
    detail: "대표주 30종목의 가격 데이터를 요청하고 완료 일봉과 정량 점수를 비교하고 있습니다.",
  });
  setButtonBusy(elements.screenButton, true, "30종목 조회 중");
  setFeedback(elements.feedback, `${marketLabel(market)} 대표주 30종목의 가격 데이터를 불러와 완료 일봉을 비교하고 있습니다.`);
  setStage("scan", "active", "조회 중");
  setStage("shortlist", "idle", "대기");
  try {
    const payload = await requestJson(API.discoveryScreen, {
      method: "POST",
      body: JSON.stringify({ market, strategy, limit: 8 }),
    }, 120_000);
    const outcome = renderDiscovery(asObject(payload.discovery));
    if (outcome.state === "failed") {
      setFeedback(elements.feedback, `후보 스캔 실패. ${outcome.message}`, "error");
      operation.fail(outcome.message);
    } else if (outcome.state === "warning") {
      setFeedback(elements.feedback, `후보 스캔 일부 완료. ${outcome.message}`, "warning");
      operation.warn(outcome.message);
    } else {
      setFeedback(elements.feedback, outcome.message, "success");
      operation.succeed(outcome.message);
    }
  } catch (error) {
    setStage("scan", "error", "실패");
    setStage("shortlist", "error", "중단");
    setFeedback(elements.feedback, `후보 선별 실패. ${error.message}`, "error");
    operation.fail(`후보 선별 요청이 실패했습니다. ${error.message}`);
  } finally {
    state.loading = false;
    setButtonBusy(elements.screenButton, false);
    setFormDisabled(elements.screenForm, false);
    updateSelection();
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
elements.market?.addEventListener("change", () => {
  state.discovery = null;
  renderCandidates([]);
  setText(elements.universe, "—");
  setText(elements.qualified, "—");
  setText(elements.shortlist, "—");
  ["scan", "shortlist", "agents", "review"].forEach((stage) => setStage(stage, "idle", "대기"));
  const market = elements.market?.value === "kr" ? "kr" : "us";
  setFeedback(elements.feedback, `${marketLabel(market)} 시장 유니버스를 선택했습니다. 후보 스캔을 다시 실행하세요.`);
});
elements.candidateList?.addEventListener("change", (event) => {
  const input = event.target.closest('input[name="discovery-ticker"]');
  if (input instanceof HTMLInputElement) updateSelection(input);
});
window.addEventListener("beforeunload", () => {
  stopPolling();
  if (state.eventRefreshTimer) window.clearTimeout(state.eventRefreshTimer);
});

renderCandidates([]);
await initSiteShell((_payload, eventType) => {
  if (["run", "analysis", "agent", "review", "fault"].includes(eventType)) scheduleEventRefresh();
});
await loadRuns();
