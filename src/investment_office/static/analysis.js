// 개별 종목 페이지에서 분석 실행, 예약, 에이전트 업무, 회의와 사람 검토를 관리한다.
import {
  API,
  ROLE_ORDER,
  appendMarketBadge,
  appendStatusBadge,
  appendWorkflowBadge,
  asArray,
  asObject,
  clearElement,
  compactText,
  createElement,
  formatDateTime,
  formatPercent,
  initSiteShell,
  marketInfo,
  requestJson,
  roleLabel,
  runProgress,
  safeSourceUrl,
  setFeedback,
  setText,
  statusInfo,
} from "./site-common.js?v=1";

const elements = {
  analysisForm: document.querySelector("#individual-analysis-form"),
  market: document.querySelector("#individual-market"),
  ticker: document.querySelector("#individual-ticker"),
  tickerSymbol: document.querySelector("#individual-ticker-symbol"),
  tickerHelp: document.querySelector("#individual-ticker-help"),
  thesis: document.querySelector("#individual-thesis"),
  analysisFeedback: document.querySelector("#individual-feedback"),
  scheduleForm: document.querySelector("#schedule-form"),
  scheduleMarket: document.querySelector("#schedule-market"),
  scheduleTicker: document.querySelector("#schedule-ticker"),
  scheduleTickerSymbol: document.querySelector("#schedule-ticker-symbol"),
  scheduleThesis: document.querySelector("#schedule-thesis"),
  scheduleTime: document.querySelector("#schedule-time"),
  scheduleFeedback: document.querySelector("#schedule-feedback"),
  scheduleRefresh: document.querySelector("#schedule-refresh"),
  scheduleList: document.querySelector("#schedule-list"),
  runList: document.querySelector("#analysis-run-list"),
  runFeedback: document.querySelector("#analysis-run-feedback"),
  selectedTicker: document.querySelector("#selected-run-ticker"),
  selectedMarket: document.querySelector("#selected-run-market"),
  selectedStatus: document.querySelector("#selected-run-status"),
  selectedId: document.querySelector("#selected-run-id"),
  selectedMessage: document.querySelector("#selected-run-message"),
  selectedProgress: document.querySelector("#selected-run-progress"),
  selectedProgressTrack: document.querySelector("#selected-run-progress-track"),
  selectedProgressBar: document.querySelector("#selected-run-progress-bar"),
  agentStrip: document.querySelector("#agent-strip"),
  agentReports: document.querySelector("#agent-reports"),
  tabs: Array.from(document.querySelectorAll("[data-workbench-tab]")),
  panels: Array.from(document.querySelectorAll("[role='tabpanel'][id^='workbench-']")),
  taskForm: document.querySelector("#task-form"),
  taskRole: document.querySelector("#task-role"),
  taskTitle: document.querySelector("#task-title"),
  taskInstructions: document.querySelector("#task-instructions"),
  taskFeedback: document.querySelector("#task-feedback"),
  taskList: document.querySelector("#task-list"),
  committeeStartForm: document.querySelector("#committee-start-form"),
  committeeTopic: document.querySelector("#committee-topic"),
  committeeMaxTurns: document.querySelector("#committee-max-turns"),
  committeeFeedback: document.querySelector("#committee-feedback"),
  committeeStatus: document.querySelector("#committee-status"),
  committeeTimeline: document.querySelector("#committee-timeline"),
  committeeLedger: document.querySelector("#committee-ledger"),
  committeeCommandForm: document.querySelector("#committee-command-form"),
  committeeCommandRole: document.querySelector("#committee-command-role"),
  committeeCommandPrompt: document.querySelector("#committee-command-prompt"),
  committeeRequest: document.querySelector("#committee-request"),
  committeeFinish: document.querySelector("#committee-finish"),
  committeeStop: document.querySelector("#committee-stop"),
  committeeMinutes: document.querySelector("#committee-minutes"),
  decisionCard: document.querySelector("#decision-card"),
  decisionRecommendation: document.querySelector("#decision-recommendation"),
  decisionConfidence: document.querySelector("#decision-confidence"),
  decisionSummary: document.querySelector("#decision-summary"),
  decisionPoints: document.querySelector("#decision-points"),
  decisionRisks: document.querySelector("#decision-risks"),
  reviewForm: document.querySelector("#review-form"),
  reviewReason: document.querySelector("#review-reason"),
  reviewButtons: Array.from(document.querySelectorAll("[data-review-decision]")),
  reviewFeedback: document.querySelector("#review-feedback"),
  live: document.querySelector("#site-live-region"),
};

const state = {
  runs: [],
  currentRunId: new URLSearchParams(window.location.search).get("run") || null,
  run: null,
  tasks: [],
  taskReports: new Map(),
  committee: null,
  selectionToken: 0,
  runTimer: null,
  committeeTimer: null,
  listRefreshTimer: null,
  scheduleRefreshPending: false,
};

const ACTIVE_RUN_STATUSES = new Set(["queued", "scheduled", "claimed", "dispatched", "running"]);
const ACTIVE_COMMITTEE_STATUSES = new Set(["running", "stop_requested"]);

function normalizeTicker(value, market) {
  const ticker = String(value || "").trim();
  return market === "kr" ? ticker : ticker.toUpperCase();
}

function tickerIsValid(ticker, market) {
  return market === "kr"
    ? /^\d{6}$/.test(ticker)
    : /^[A-Z0-9][A-Z0-9.\-]{0,14}$/.test(ticker);
}

function syncMarketInput(select, input, symbol, help = null) {
  const market = select?.value === "kr" ? "kr" : "us";
  if (input) {
    input.placeholder = market === "kr" ? "005930" : "NVDA";
    input.inputMode = market === "kr" ? "numeric" : "text";
    input.maxLength = market === "kr" ? 6 : 15;
    input.value = normalizeTicker(input.value, market);
  }
  setText(symbol, market === "kr" ? "₩" : "$", market === "kr" ? "₩" : "$");
  setText(
    help,
    market === "kr"
      ? "한국 거래소의 6자리 종목코드를 입력하세요."
      : "미국 종목 티커를 입력하세요. 영문, 숫자, 점과 하이픈을 사용할 수 있습니다.",
  );
}

function setFormDisabled(form, disabled) {
  form?.querySelectorAll("input, textarea, select, button").forEach((control) => {
    control.disabled = disabled;
  });
}

function scheduleListRefresh(includeSchedules = false) {
  state.scheduleRefreshPending ||= includeSchedules;
  if (state.listRefreshTimer) window.clearTimeout(state.listRefreshTimer);
  state.listRefreshTimer = window.setTimeout(() => {
    const refreshSchedules = state.scheduleRefreshPending;
    state.scheduleRefreshPending = false;
    const requests = [loadRunList({ preserveSelection: true })];
    if (refreshSchedules) requests.push(loadSchedules());
    void Promise.all(requests);
  }, 350);
}

function setScheduleDefault() {
  if (!elements.scheduleTime) return;
  const target = new Date(Date.now() + 60 * 60 * 1000);
  const local = new Date(target.getTime() - target.getTimezoneOffset() * 60_000);
  const minimum = new Date(Date.now() + 5 * 60 * 1000);
  const localMinimum = new Date(minimum.getTime() - minimum.getTimezoneOffset() * 60_000);
  elements.scheduleTime.value = local.toISOString().slice(0, 16);
  elements.scheduleTime.min = localMinimum.toISOString().slice(0, 16);
}

function renderRunList() {
  const focusedControl = document.activeElement;
  const focusedRunId = focusedControl instanceof HTMLElement && elements.runList?.contains(focusedControl)
    ? focusedControl.dataset.runId
    : null;
  clearElement(elements.runList);
  const visible = state.runs.filter((run) => ["manual", "scheduled", "unknown"].includes(run.workflow));
  if (!visible.length) {
    elements.runList?.append(createElement("li", "empty-state", "개별 종목 분석 내역이 없습니다."));
    return;
  }
  visible.forEach((run) => {
    const item = createElement("li", "run-row");
    if (run.run_id === state.currentRunId) item.dataset.selected = "true";
    const button = createElement("button", "run-row__button");
    button.type = "button";
    button.dataset.runId = run.run_id;
    const head = createElement("span", "run-row__head");
    head.append(createElement("strong", "", run.ticker || "종목 미정"));
    appendMarketBadge(head, run.market, run.ticker);
    appendStatusBadge(head, run.status);
    const meta = createElement("span", "run-row__meta");
    meta.append(createElement("span", "", formatDateTime(run.created_at)));
    appendWorkflowBadge(meta, run.workflow);
    const message = createElement("span", "run-row__message", compactText(run.message || run.error, 90) || "상세 확인");
    button.append(head, meta, message);
    item.append(button);
    elements.runList?.append(item);
  });
  if (focusedRunId) {
    const restoredControl = Array.from(elements.runList?.querySelectorAll("[data-run-id]") || [])
      .find((control) => control.dataset.runId === focusedRunId);
    restoredControl?.focus({ preventScroll: true });
  }
}

async function loadRunList({ preserveSelection = false } = {}) {
  try {
    const payload = await requestJson(`${API.runs}?limit=200`);
    state.runs = asArray(payload.runs);
    if (!preserveSelection || !state.currentRunId) {
      state.currentRunId = state.currentRunId || state.runs.find((run) => ["manual", "scheduled", "unknown"].includes(run.workflow))?.run_id || null;
    }
    renderRunList();
    setFeedback(elements.runFeedback, `${state.runs.filter((run) => ["manual", "scheduled", "unknown"].includes(run.workflow)).length}개 실행을 불러왔습니다.`, "success");
    if (state.currentRunId) await selectRun(state.currentRunId, { updateUrl: false });
    else renderEmptyRun();
  } catch (error) {
    setFeedback(elements.runFeedback, `실행 목록 조회 실패. ${error.message}`, "error");
  }
}

function renderEmptyRun() {
  state.run = null;
  setText(elements.selectedTicker, "실행을 선택하세요.");
  setText(elements.selectedMarket, "시장 미정");
  if (elements.selectedMarket) elements.selectedMarket.dataset.market = "unknown";
  setText(elements.selectedStatus, "대기");
  if (elements.selectedStatus) elements.selectedStatus.dataset.tone = "idle";
  setText(elements.selectedId, "—");
  setText(elements.selectedMessage, "왼쪽 실행 목록에서 분석을 선택하면 상세 기능이 열립니다.");
  setText(elements.selectedProgress, "0%");
  elements.selectedProgressTrack?.setAttribute("aria-valuenow", "0");
  if (elements.selectedProgressBar) elements.selectedProgressBar.style.width = "0%";
  clearElement(elements.agentStrip);
  clearElement(elements.agentReports);
  renderTasks([]);
  renderCommittee(null);
  renderDecision(null);
}

async function selectRun(runId, { updateUrl = true } = {}) {
  if (!runId) return;
  state.currentRunId = runId;
  const token = ++state.selectionToken;
  if (updateUrl) {
    const url = new URL(window.location.href);
    url.searchParams.set("run", runId);
    window.history.replaceState({}, "", url);
  }
  renderRunList();
  setFeedback(elements.runFeedback, "선택한 실행을 불러오는 중입니다.");
  stopRunPolling();
  stopCommitteePolling();
  try {
    const [runPayload, taskPayload, committeePayload] = await Promise.all([
      requestJson(API.run(runId)),
      requestJson(API.tasks(runId)),
      requestJson(API.runCommittee(runId)),
    ]);
    if (token !== state.selectionToken) return;
    state.run = asObject(runPayload.run);
    state.tasks = asArray(taskPayload.tasks);
    state.committee = committeePayload.committee || null;
    renderSelectedRun();
    renderTasks(state.tasks);
    renderCommittee(state.committee);
    setFeedback(elements.runFeedback, `${state.run.ticker || "선택 실행"} 상세를 표시합니다.`, "success");
    if (ACTIVE_RUN_STATUSES.has(state.run.status)) scheduleRunPolling();
    if (ACTIVE_COMMITTEE_STATUSES.has(state.committee?.status)) scheduleCommitteePolling();
  } catch (error) {
    if (token !== state.selectionToken) return;
    setFeedback(elements.runFeedback, `실행 상세 조회 실패. ${error.message}`, "error");
  }
}

function renderSelectedRun() {
  const run = state.run || {};
  const status = statusInfo(run.status);
  const progress = runProgress(run);
  setText(elements.selectedTicker, run.ticker, "종목 미정");
  const market = marketInfo(run.market, run.ticker);
  setText(elements.selectedMarket, market.label);
  if (elements.selectedMarket) elements.selectedMarket.dataset.market = market.key;
  setText(elements.selectedStatus, status.label);
  if (elements.selectedStatus) elements.selectedStatus.dataset.tone = status.tone;
  setText(elements.selectedId, run.run_id, "—");
  setText(elements.selectedMessage, run.message || run.error, "현재 상태 설명이 없습니다.");
  setText(elements.selectedProgress, `${Math.round(progress)}%`);
  elements.selectedProgressTrack?.setAttribute("aria-valuenow", String(Math.round(progress)));
  if (elements.selectedProgressBar) elements.selectedProgressBar.style.width = `${progress}%`;
  renderAgents(run.agents);
  renderDecision(run);
}

function orderedAgents(agents) {
  return asArray(agents).slice().sort((left, right) => {
    const leftIndex = ROLE_ORDER.indexOf(left.role);
    const rightIndex = ROLE_ORDER.indexOf(right.role);
    return (leftIndex < 0 ? 99 : leftIndex) - (rightIndex < 0 ? 99 : rightIndex);
  });
}

function renderAgents(agents) {
  const values = orderedAgents(agents);
  clearElement(elements.agentStrip);
  clearElement(elements.agentReports);
  if (!values.length) {
    elements.agentStrip?.append(createElement("li", "empty-state", "에이전트 결과를 기다리고 있습니다."));
    elements.agentReports?.append(createElement("p", "empty-state", "분석이 시작되면 역할별 보고서가 표시됩니다."));
    return;
  }

  values.forEach((agent) => {
    const stripItem = createElement("li", "agent-chip");
    stripItem.dataset.status = agent.status || "queued";
    const mark = createElement("span", "agent-chip__mark", roleLabel(agent.role).slice(0, 1));
    const info = createElement("span", "agent-chip__text");
    info.append(createElement("strong", "", roleLabel(agent.role)));
    info.append(createElement("small", "", statusInfo(agent.status).label));
    stripItem.append(mark, info);
    elements.agentStrip?.append(stripItem);

    const report = createElement("details", "agent-report");
    if (agent.role === "head_trader") report.open = true;
    const summary = createElement("summary", "agent-report__summary");
    summary.append(createElement("strong", "", roleLabel(agent.role)));
    appendStatusBadge(summary, agent.status);
    summary.append(createElement("span", "", formatPercent(agent.confidence)));
    report.append(summary);
    report.append(createElement("p", "agent-report__lead", agent.summary || agent.error || "보고 내용이 없습니다."));

    const result = asObject(agent.result);
    const points = asArray(result.key_points).slice(0, 6);
    const risks = asArray(result.risks).slice(0, 6);
    if (points.length || risks.length) {
      const columns = createElement("div", "report-columns");
      const pointSection = createElement("section");
      pointSection.append(createElement("h4", "", "핵심 관찰"));
      const pointList = createElement("ul", "compact-list");
      points.forEach((point) => pointList.append(createElement("li", "", point)));
      pointSection.append(pointList);
      const riskSection = createElement("section");
      riskSection.append(createElement("h4", "", "위험 신호"));
      const riskList = createElement("ul", "compact-list compact-list--risk");
      risks.forEach((risk) => riskList.append(createElement("li", "", risk)));
      riskSection.append(riskList);
      columns.append(pointSection, riskSection);
      report.append(columns);
    }

    const sources = asArray(result.evidence).map((evidence) => ({ ...evidence, url: safeSourceUrl(evidence.source_url) })).filter((evidence) => evidence.url).slice(0, 4);
    if (sources.length) {
      const sourceList = createElement("div", "source-links");
      sources.forEach((source) => {
        const link = createElement("a", "", compactText(source.claim, 70) || "근거 출처");
        link.href = source.url;
        link.target = "_blank";
        link.rel = "noreferrer";
        sourceList.append(link);
      });
      report.append(sourceList);
    }
    elements.agentReports?.append(report);
  });
}

function renderTasks(tasks) {
  clearElement(elements.taskList);
  setFormDisabled(elements.taskForm, !state.currentRunId);
  const values = asArray(tasks);
  if (!values.length) {
    elements.taskList?.append(createElement("li", "empty-state", "이 실행에 별도 업무가 없습니다."));
    return;
  }
  values.forEach((task) => {
    const item = createElement("li", "task-card");
    const head = createElement("div", "task-card__head");
    head.append(createElement("strong", "", task.title || "업무"));
    appendStatusBadge(head, task.status);
    const meta = createElement("p", "task-card__meta", `${roleLabel(task.role)} · 시도 ${task.attempt || 1} · ${formatDateTime(task.updated_at)}`);
    const instructions = createElement("p", "task-card__instructions", task.instructions || "지시 내용 없음");
    item.append(head, meta, instructions);
    const result = asObject(task.result);
    const progress = asObject(task.progress);
    const storedReport = state.taskReports.get(task.id);
    if (Object.keys(result).length || Object.keys(progress).length || storedReport) {
      const output = createElement("pre", "task-card__output");
      const outputValue = storedReport || (Object.keys(result).length ? result : progress);
      output.textContent = JSON.stringify(outputValue, null, 2);
      item.append(output);
    }
    if (task.error) item.append(createElement("p", "inline-error", task.error));
    const actions = createElement("div", "card-actions");
    const reportButton = createElement("button", "button button--secondary", "저장 상태 보고");
    reportButton.type = "button";
    reportButton.dataset.taskAction = "report";
    reportButton.dataset.taskId = task.id;
    actions.append(reportButton);
    if (["failed", "cancelled"].includes(task.status)) {
      const resumeButton = createElement("button", "button button--secondary", "새 시도로 재개");
      resumeButton.type = "button";
      resumeButton.dataset.taskAction = "resume";
      resumeButton.dataset.taskId = task.id;
      actions.append(resumeButton);
    }
    if (task.status === "queued") {
      const cancelButton = createElement("button", "button button--danger", "대기 업무 취소");
      cancelButton.type = "button";
      cancelButton.dataset.taskAction = "cancel";
      cancelButton.dataset.taskId = task.id;
      actions.append(cancelButton);
    }
    item.append(actions);
    elements.taskList?.append(item);
  });
}

function renderCommittee(committee) {
  clearElement(elements.committeeTimeline);
  clearElement(elements.committeeLedger);
  clearElement(elements.committeeMinutes);
  state.committee = committee || null;
  const active = ACTIVE_COMMITTEE_STATUSES.has(committee?.status);
  setFormDisabled(elements.committeeStartForm, !state.currentRunId || active);
  setFormDisabled(elements.committeeCommandForm, !active);
  if (elements.committeeFinish) elements.committeeFinish.disabled = !active;
  if (elements.committeeStop) elements.committeeStop.disabled = !active;

  if (!committee) {
    setText(elements.committeeStatus, "소집 전");
    if (elements.committeeStatus) elements.committeeStatus.dataset.tone = "idle";
    elements.committeeTimeline?.append(createElement("li", "empty-state", "선택 실행에 열린 회의가 없습니다."));
    elements.committeeLedger?.append(createElement("li", "empty-state", "회의가 시작되면 주장과 근거 원장이 표시됩니다."));
    return;
  }

  const info = statusInfo(committee.status);
  setText(elements.committeeStatus, `${committee.topic || "투자위원회"} · ${info.label}`);
  if (elements.committeeStatus) elements.committeeStatus.dataset.tone = info.tone;
  asArray(committee.turns).forEach((turn) => {
    const item = createElement("li", "committee-turn");
    const head = createElement("div", "committee-turn__head");
    head.append(createElement("span", "sequence-mark", String(turn.sequence || 0).padStart(2, "0")));
    head.append(createElement("strong", "", roleLabel(turn.role)));
    appendStatusBadge(head, turn.status);
    item.append(head, createElement("p", "", turn.content || turn.error || "발언 내용이 없습니다."));
    elements.committeeTimeline?.append(item);
  });
  if (!asArray(committee.turns).length) elements.committeeTimeline?.append(createElement("li", "empty-state", "첫 발언을 준비하고 있습니다."));

  asArray(committee.claim_ledger).forEach((claim) => {
    const item = createElement("li", "ledger-item");
    item.append(createElement("span", "ledger-item__kind", claim.kind || "claim"));
    item.append(createElement("p", "", claim.text || "주장 내용 없음"));
    item.append(createElement("small", "", `${asArray(claim.roles).map(roleLabel).join(", ") || "역할 미정"} · ${claim.evidence_status || "근거 상태 미정"}`));
    elements.committeeLedger?.append(item);
  });
  if (!asArray(committee.claim_ledger).length) elements.committeeLedger?.append(createElement("li", "empty-state", "정리된 주장 원장이 아직 없습니다."));
  if (!active && committee.session_id) void loadMinutes(committee.session_id);
}

async function loadMinutes(sessionId) {
  try {
    const payload = await requestJson(API.committeeMinutes(sessionId));
    if (state.committee?.session_id !== sessionId) return;
    const minutes = payload.minutes;
    clearElement(elements.committeeMinutes);
    if (!minutes) {
      elements.committeeMinutes?.append(createElement("p", "empty-state", "회의록 생성 전입니다."));
      return;
    }
    elements.committeeMinutes?.append(createElement("h4", "", "확정 회의록"));
    const grid = createElement("div", "minutes-grid");
    [
      ["위원장 요약", minutes.chairman_summary],
      ["위원장 결론", minutes.chairman_recommendation],
      ["강세 논리", minutes.bull_case],
      ["약세 논리", minutes.bear_case],
    ].forEach(([label, value]) => {
      if (!value) return;
      const section = createElement("section");
      section.append(createElement("h5", "", label), createElement("p", "", value));
      grid.append(section);
    });
    elements.committeeMinutes?.append(grid);
    const gaps = asArray(minutes.data_gaps);
    if (gaps.length) {
      elements.committeeMinutes?.append(createElement("h5", "", "데이터 공백"));
      const list = createElement("ul", "compact-list");
      gaps.forEach((gap) => list.append(createElement("li", "", gap)));
      elements.committeeMinutes?.append(list);
    }
  } catch (error) {
    if (state.committee?.session_id !== sessionId) return;
    elements.committeeMinutes?.append(createElement("p", "inline-error", `회의록 조회 실패. ${error.message}`));
  }
}

function renderDecision(run) {
  const decision = asObject(run?.decision);
  const review = asObject(run?.human_review);
  const hasDecision = Object.keys(decision).length > 0;
  if (elements.decisionCard) elements.decisionCard.hidden = !hasDecision;
  setText(elements.decisionRecommendation, decision.recommendation || decision.action, "결정 초안 대기");
  setText(elements.decisionConfidence, formatPercent(decision.confidence), "—");
  const positionCap = Number(decision.position_cap_pct);
  const riskGateSummary = decision.risk_eligible === false
    ? "위험 정책상 신규 매수가 허용되지 않습니다."
    : Number.isFinite(positionCap) && positionCap > 0
      ? `위험 정책상 최대 비중은 ${positionCap.toFixed(2)}%입니다.`
      : "";
  setText(
    elements.decisionSummary,
    [riskGateSummary, decision.summary].filter(Boolean).join(" "),
    "분석 완료 후 위원장 초안이 표시됩니다.",
  );
  renderTextList(elements.decisionPoints, decision.key_points, "핵심 근거 대기 중입니다.");
  renderTextList(elements.decisionRisks, decision.risks, "위험 신호 대기 중입니다.");

  const reviewable = run?.status === "review" && !Object.keys(review).length;
  setFormDisabled(elements.reviewForm, !reviewable);
  if (Object.keys(review).length) {
    setFeedback(elements.reviewFeedback, `${statusInfo(run.status).label} 결정이 기록되었습니다. ${review.reason || ""}`, "success");
  } else if (reviewable) {
    setFeedback(elements.reviewFeedback, "사유를 입력한 뒤 승인·보류·기각을 기록하세요.");
  } else {
    setFeedback(elements.reviewFeedback, "분석 초안이 검토 단계에 도달하면 사람 결정이 활성화됩니다.");
  }
}

function renderTextList(container, values, emptyText) {
  clearElement(container);
  const items = asArray(values);
  if (!items.length) {
    container?.append(createElement("li", "empty-state", emptyText));
    return;
  }
  items.slice(0, 8).forEach((value) => container?.append(createElement("li", "", value)));
}

function stopRunPolling() {
  if (state.runTimer) window.clearTimeout(state.runTimer);
  state.runTimer = null;
}

function scheduleRunPolling(delay = 2_800) {
  stopRunPolling();
  if (!state.currentRunId) return;
  state.runTimer = window.setTimeout(() => selectRun(state.currentRunId, { updateUrl: false }), delay);
}

function stopCommitteePolling() {
  if (state.committeeTimer) window.clearTimeout(state.committeeTimer);
  state.committeeTimer = null;
}

function scheduleCommitteePolling(delay = 1_600) {
  stopCommitteePolling();
  if (!state.committee?.session_id) return;
  state.committeeTimer = window.setTimeout(refreshCommittee, delay);
}

async function refreshCommittee() {
  if (!state.committee?.session_id) return;
  const sessionId = state.committee.session_id;
  const runId = state.currentRunId;
  try {
    const payload = await requestJson(API.committee(sessionId));
    if (state.currentRunId !== runId || state.committee?.session_id !== sessionId) return;
    renderCommittee(payload.committee);
    if (ACTIVE_COMMITTEE_STATUSES.has(payload.committee?.status)) scheduleCommitteePolling();
  } catch (error) {
    setFeedback(elements.committeeFeedback, `회의 갱신 실패. ${error.message}`, "error");
  }
}

async function loadSchedules() {
  try {
    const payload = await requestJson(API.schedules);
    renderSchedules(payload.schedules);
  } catch (error) {
    setFeedback(elements.scheduleFeedback, `예약 목록 조회 실패. ${error.message}`, "error");
  }
}

function renderSchedules(schedules) {
  clearElement(elements.scheduleList);
  const values = asArray(schedules);
  if (!values.length) {
    elements.scheduleList?.append(createElement("li", "empty-state", "등록된 예약 분석이 없습니다."));
    return;
  }
  values.forEach((schedule) => {
    const item = createElement("li", "schedule-row");
    const head = createElement("div", "schedule-row__head");
    head.append(createElement("strong", "", schedule.ticker || "종목 미정"));
    appendMarketBadge(head, schedule.market, schedule.ticker);
    appendStatusBadge(head, schedule.status);
    item.append(head);
    item.append(createElement("time", "schedule-row__time", formatDateTime(schedule.scheduled_for)));
    if (schedule.thesis) item.append(createElement("p", "", compactText(schedule.thesis, 100)));
    if (schedule.error) item.append(createElement("p", "inline-error", schedule.error));
    const actions = createElement("div", "card-actions");
    const open = createElement("a", "button button--secondary", "실행 열기");
    open.href = `/analysis?run=${encodeURIComponent(schedule.run_id)}`;
    actions.append(open);
    if (schedule.status === "scheduled") {
      const cancel = createElement("button", "button button--danger", "예약 취소");
      cancel.type = "button";
      cancel.dataset.scheduleAction = "cancel";
      cancel.dataset.scheduleId = schedule.id;
      actions.append(cancel);
    }
    item.append(actions);
    elements.scheduleList?.append(item);
  });
}

async function submitAnalysis(event) {
  event.preventDefault();
  const market = elements.market?.value === "kr" ? "kr" : "us";
  const ticker = normalizeTicker(elements.ticker?.value, market);
  const thesis = String(elements.thesis?.value || "").trim();
  if (!tickerIsValid(ticker, market)) {
    setFeedback(elements.analysisFeedback, market === "kr" ? "한국 종목코드는 숫자 6자리로 입력하세요." : "올바른 미국 종목 코드를 입력하세요.", "error");
    elements.ticker?.focus();
    return;
  }
  setFormDisabled(elements.analysisForm, true);
  setFeedback(elements.analysisFeedback, `${ticker} 분석을 투자팀에 배정하고 있습니다.`);
  try {
    const payload = await requestJson(API.analyze, {
      method: "POST",
      body: JSON.stringify(thesis ? { market, ticker, thesis } : { market, ticker }),
    }, 45_000);
    const run = payload.run || {};
    setFeedback(elements.analysisFeedback, `${ticker} 분석이 시작되었습니다.`, "success");
    await loadRunList({ preserveSelection: true });
    await selectRun(run.run_id || payload.run_id);
  } catch (error) {
    setFeedback(elements.analysisFeedback, `분석 시작 실패. ${error.message}`, "error");
  } finally {
    setFormDisabled(elements.analysisForm, false);
  }
}

async function submitSchedule(event) {
  event.preventDefault();
  const market = elements.scheduleMarket?.value === "kr" ? "kr" : "us";
  const ticker = normalizeTicker(elements.scheduleTicker?.value, market);
  const thesis = String(elements.scheduleThesis?.value || "").trim();
  const localTime = String(elements.scheduleTime?.value || "");
  const scheduledDate = new Date(localTime);
  if (!tickerIsValid(ticker, market) || Number.isNaN(scheduledDate.getTime())) {
    setFeedback(elements.scheduleFeedback, "종목 코드와 미래 예약 시각을 확인하세요.", "error");
    return;
  }
  setFormDisabled(elements.scheduleForm, true);
  setFeedback(elements.scheduleFeedback, `${ticker} 일회성 분석 예약을 등록하고 있습니다.`);
  try {
    const body = { market, ticker, scheduled_for: scheduledDate.toISOString() };
    if (thesis) body.thesis = thesis;
    const payload = await requestJson(API.schedules, { method: "POST", body: JSON.stringify(body) });
    setFeedback(elements.scheduleFeedback, `${ticker} 예약을 등록했습니다.`, "success");
    await Promise.all([loadSchedules(), loadRunList({ preserveSelection: true })]);
    if (payload.run?.run_id) await selectRun(payload.run.run_id);
  } catch (error) {
    setFeedback(elements.scheduleFeedback, `예약 등록 실패. ${error.message}`, "error");
  } finally {
    setFormDisabled(elements.scheduleForm, false);
  }
}

async function submitTask(event) {
  event.preventDefault();
  if (!state.currentRunId) return;
  const body = {
    role: elements.taskRole?.value,
    title: String(elements.taskTitle?.value || "").trim(),
    instructions: String(elements.taskInstructions?.value || "").trim(),
  };
  if (!body.role || !body.title || !body.instructions) {
    setFeedback(elements.taskFeedback, "역할, 제목, 업무 지시를 모두 입력하세요.", "error");
    return;
  }
  setFormDisabled(elements.taskForm, true);
  try {
    await requestJson(API.tasks(state.currentRunId), { method: "POST", body: JSON.stringify(body) });
    setFeedback(elements.taskFeedback, `${roleLabel(body.role)}에게 업무를 배정했습니다.`, "success");
    elements.taskTitle.value = "";
    elements.taskInstructions.value = "";
    await selectRun(state.currentRunId, { updateUrl: false });
  } catch (error) {
    setFeedback(elements.taskFeedback, `업무 배정 실패. ${error.message}`, "error");
  } finally {
    setFormDisabled(elements.taskForm, false);
  }
}

async function handleTaskAction(event) {
  const button = event.target.closest("[data-task-action]");
  if (!(button instanceof HTMLButtonElement)) return;
  const taskId = button.dataset.taskId;
  const action = button.dataset.taskAction;
  if (!taskId || !action) return;
  button.disabled = true;
  try {
    if (action === "report") {
      const payload = await requestJson(API.taskReport(taskId), { method: "POST" });
      state.taskReports.set(taskId, payload.report);
      setFeedback(elements.taskFeedback, "저장된 최신 업무 상태를 불러왔습니다.", "success");
      renderTasks(state.tasks);
      return;
    }
    const url = action === "resume" ? API.taskResume(taskId) : API.taskCancel(taskId);
    await requestJson(url, { method: "POST" });
    setFeedback(elements.taskFeedback, action === "resume" ? "업무를 새 시도로 재개했습니다." : "대기 업무를 취소했습니다.", "success");
    await selectRun(state.currentRunId, { updateUrl: false });
  } catch (error) {
    setFeedback(elements.taskFeedback, `업무 처리 실패. ${error.message}`, "error");
  } finally {
    button.disabled = false;
  }
}

async function startCommittee(event) {
  event.preventDefault();
  if (!state.currentRunId) return;
  const participants = Array.from(document.querySelectorAll('input[name="committee-participant"]:checked')).map((input) => input.value);
  const body = {
    topic: String(elements.committeeTopic?.value || "").trim(),
    participants,
    max_turns: Number(elements.committeeMaxTurns?.value || 12),
  };
  if (!body.topic || participants.length < 2) {
    setFeedback(elements.committeeFeedback, "회의 주제와 참가 역할 2개 이상을 선택하세요.", "error");
    return;
  }
  setFormDisabled(elements.committeeStartForm, true);
  try {
    const payload = await requestJson(API.startCommittee(state.currentRunId), { method: "POST", body: JSON.stringify(body) }, 45_000);
    renderCommittee(payload.committee);
    setFeedback(elements.committeeFeedback, "투자위원회 회의를 소집했습니다.", "success");
    scheduleCommitteePolling(800);
  } catch (error) {
    setFeedback(elements.committeeFeedback, `회의 소집 실패. ${error.message}`, "error");
    setFormDisabled(elements.committeeStartForm, false);
  }
}

async function sendCommitteeCommand(command, { role = null, prompt = null, reason = null } = {}) {
  if (!state.committee?.session_id) return;
  const body = { command };
  if (role) body.role = role;
  if (prompt) body.prompt = prompt;
  if (reason) body.reason = reason;
  try {
    await requestJson(API.committeeCommands(state.committee.session_id), { method: "POST", body: JSON.stringify(body) });
    setFeedback(elements.committeeFeedback, command === "directed_speak" ? "추가 발언을 요청했습니다." : "회의 제어 명령을 전달했습니다.", "success");
    scheduleCommitteePolling(500);
  } catch (error) {
    setFeedback(elements.committeeFeedback, `회의 명령 실패. ${error.message}`, "error");
  }
}

async function requestCommitteeSpeech(event) {
  event.preventDefault();
  const role = elements.committeeCommandRole?.value;
  const prompt = String(elements.committeeCommandPrompt?.value || "").trim();
  if (!role || !prompt) {
    setFeedback(elements.committeeFeedback, "발언 역할과 질문을 입력하세요.", "error");
    return;
  }
  await sendCommitteeCommand("directed_speak", { role, prompt });
}

async function submitReview(decision) {
  if (!state.currentRunId) return;
  const reason = String(elements.reviewReason?.value || "").trim();
  if (reason.length < 4) {
    setFeedback(elements.reviewFeedback, "결정 사유를 4자 이상 입력하세요.", "error");
    elements.reviewReason?.focus();
    return;
  }
  const apiDecision = { approve: "approved", hold: "deferred", reject: "rejected" }[decision];
  if (!apiDecision) return;
  elements.reviewButtons.forEach((button) => { button.disabled = true; });
  try {
    await requestJson(API.review(state.currentRunId), {
      method: "POST",
      body: JSON.stringify({ decision: apiDecision, reason }),
    });
    setFeedback(elements.reviewFeedback, "사람의 최종 결정을 기록했습니다.", "success");
    await loadRunList({ preserveSelection: true });
  } catch (error) {
    setFeedback(elements.reviewFeedback, `결정 기록 실패. ${error.message}`, "error");
    elements.reviewButtons.forEach((button) => { button.disabled = false; });
  }
}

function activateTab(name) {
  elements.tabs.forEach((button) => {
    const active = button.dataset.workbenchTab === name;
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  elements.panels.forEach((panel) => {
    panel.hidden = panel.id !== `workbench-${name}`;
  });
}

function handleTabKeydown(event) {
  const keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
  if (!keys.includes(event.key)) return;
  const currentIndex = elements.tabs.indexOf(event.currentTarget);
  if (currentIndex < 0) return;
  event.preventDefault();
  let nextIndex = currentIndex;
  if (event.key === "Home") nextIndex = 0;
  if (event.key === "End") nextIndex = elements.tabs.length - 1;
  if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % elements.tabs.length;
  if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + elements.tabs.length) % elements.tabs.length;
  const nextButton = elements.tabs[nextIndex];
  activateTab(nextButton.dataset.workbenchTab);
  nextButton.focus();
}

function bindEvents() {
  elements.analysisForm?.addEventListener("submit", submitAnalysis);
  elements.scheduleForm?.addEventListener("submit", submitSchedule);
  elements.market?.addEventListener("change", () => syncMarketInput(elements.market, elements.ticker, elements.tickerSymbol, elements.tickerHelp));
  elements.scheduleMarket?.addEventListener("change", () => syncMarketInput(elements.scheduleMarket, elements.scheduleTicker, elements.scheduleTickerSymbol));
  elements.scheduleRefresh?.addEventListener("click", loadSchedules);
  elements.scheduleList?.addEventListener("click", async (event) => {
    const button = event.target.closest('[data-schedule-action="cancel"]');
    if (!(button instanceof HTMLButtonElement)) return;
    button.disabled = true;
    try {
      await requestJson(API.cancelSchedule(button.dataset.scheduleId), { method: "POST" });
      setFeedback(elements.scheduleFeedback, "예약을 취소했습니다.", "success");
      await Promise.all([loadSchedules(), loadRunList({ preserveSelection: true })]);
    } catch (error) {
      setFeedback(elements.scheduleFeedback, `예약 취소 실패. ${error.message}`, "error");
      button.disabled = false;
    }
  });
  elements.runList?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-run-id]");
    if (button) void selectRun(button.dataset.runId);
  });
  elements.tabs.forEach((button) => {
    button.addEventListener("click", () => activateTab(button.dataset.workbenchTab));
    button.addEventListener("keydown", handleTabKeydown);
  });
  elements.taskForm?.addEventListener("submit", submitTask);
  elements.taskList?.addEventListener("click", handleTaskAction);
  elements.committeeStartForm?.addEventListener("submit", startCommittee);
  elements.committeeCommandForm?.addEventListener("submit", requestCommitteeSpeech);
  elements.committeeFinish?.addEventListener("click", () => sendCommitteeCommand("finish"));
  elements.committeeStop?.addEventListener("click", () => sendCommitteeCommand("stop", { reason: "사용자가 사이트에서 회의를 중단했습니다." }));
  elements.reviewButtons.forEach((button) => button.addEventListener("click", () => submitReview(button.dataset.reviewDecision)));
  window.addEventListener("beforeunload", () => {
    stopRunPolling();
    stopCommitteePolling();
  });
}

bindEvents();
syncMarketInput(elements.market, elements.ticker, elements.tickerSymbol, elements.tickerHelp);
syncMarketInput(elements.scheduleMarket, elements.scheduleTicker, elements.scheduleTickerSymbol);
setScheduleDefault();
activateTab("agents");
await initSiteShell((payload, eventType) => {
  if (payload.run_id === state.currentRunId) void selectRun(state.currentRunId, { updateUrl: false });
  scheduleListRefresh(eventType === "schedule");
});
await Promise.all([loadSchedules(), loadRunList()]);
