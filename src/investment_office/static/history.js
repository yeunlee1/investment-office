// 완료 이력 페이지에서 모든 실행을 필터링하고 저장된 상세 결과를 조회한다.
import {
  API,
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
  requestJson,
  roleLabel,
  setFeedback,
  setText,
  workflowInfo,
} from "./site-common.js?v=1";

const elements = {
  filterForm: document.querySelector("#history-filter-form"),
  workflow: document.querySelector("#history-workflow"),
  status: document.querySelector("#history-status"),
  ticker: document.querySelector("#history-ticker"),
  period: document.querySelector("#history-period"),
  count: document.querySelector("#history-count"),
  list: document.querySelector("#history-list"),
  feedback: document.querySelector("#history-feedback"),
  detail: document.querySelector("#history-detail"),
  live: document.querySelector("#site-live-region"),
};

const query = new URLSearchParams(window.location.search);
const state = {
  runs: [],
  filtered: [],
  selectedRunId: query.get("run") || null,
  detailToken: 0,
  refreshTimer: null,
  detailRefreshPending: false,
};

const requestedWorkflow = query.get("workflow");
if (elements.workflow && ["manual", "discovery", "scheduled", "unknown"].includes(requestedWorkflow)) {
  elements.workflow.value = requestedWorkflow;
}

function currentFilters() {
  return {
    workflow: elements.workflow?.value || "all",
    status: elements.status?.value || "all",
    ticker: String(elements.ticker?.value || "").trim().toUpperCase(),
    period: Number(elements.period?.value || 0),
  };
}

function applyFilters() {
  const filters = currentFilters();
  const cutoff = filters.period ? Date.now() - filters.period * 24 * 60 * 60 * 1000 : 0;
  state.filtered = state.runs.filter((run) => {
    if (filters.workflow !== "all" && run.workflow !== filters.workflow) return false;
    if (filters.status !== "all" && run.status !== filters.status) return false;
    if (filters.ticker && !String(run.ticker || "").includes(filters.ticker)) return false;
    const timestamp = new Date(run.completed_at || run.created_at || 0).getTime();
    return !cutoff || (Number.isFinite(timestamp) && timestamp >= cutoff);
  });
  renderHistoryList();
}

function renderHistoryList() {
  const focusedControl = document.activeElement;
  const focusedRunId = focusedControl instanceof HTMLElement && elements.list?.contains(focusedControl)
    ? focusedControl.dataset.historyRun
    : null;
  clearElement(elements.list);
  setText(elements.count, `${state.filtered.length}건`);
  if (!state.filtered.length) {
    elements.list?.append(createElement("li", "empty-state", "선택한 조건에 맞는 실행 이력이 없습니다."));
    return;
  }
  state.filtered.forEach((run) => {
    const item = createElement("li");
    const button = createElement("button", "history-card");
    if (run.run_id === state.selectedRunId) button.classList.add("is-selected");
    button.type = "button";
    button.dataset.historyRun = run.run_id;
    const identity = createElement("span", "history-row__identity");
    identity.append(createElement("strong", "", run.ticker || "종목 미정"));
    appendWorkflowBadge(identity, run.workflow);
    const status = createElement("span", "history-row__status");
    appendStatusBadge(status, run.status);
    const decision = asObject(run.decision);
    status.append(createElement("small", "", compactText(decision.recommendation || run.message, 55) || "결정 내용 없음"));
    const time = createElement("time", "history-row__time", formatDateTime(run.completed_at || run.created_at));
    button.append(identity, status, time);
    item.append(button);
    elements.list?.append(item);
  });
  if (focusedRunId) {
    const restoredControl = Array.from(elements.list?.querySelectorAll("[data-history-run]") || [])
      .find((control) => control.dataset.historyRun === focusedRunId);
    restoredControl?.focus({ preventScroll: true });
  }
}

async function loadHistory({ refreshDetail = true } = {}) {
  try {
    setFeedback(elements.feedback, "저장된 실행 이력을 불러오는 중입니다.");
    const payload = await requestJson(`${API.runs}?limit=200`);
    state.runs = asArray(payload.runs);
    applyFilters();
    setFeedback(elements.feedback, `최신 ${state.runs.length}건을 불러왔습니다. 기존 미분류는 과거 저장 형식의 실행입니다.`, "success");
    if (refreshDetail && state.selectedRunId) await loadDetail(state.selectedRunId, { updateUrl: false });
  } catch (error) {
    setFeedback(elements.feedback, `이력 조회 실패. ${error.message}`, "error");
  }
}

async function loadDetail(runId, { updateUrl = true } = {}) {
  if (!runId) return;
  state.selectedRunId = runId;
  renderHistoryList();
  const token = ++state.detailToken;
  if (updateUrl) {
    const url = new URL(window.location.href);
    url.searchParams.set("run", runId);
    window.history.replaceState({}, "", url);
  }
  clearElement(elements.detail);
  const loadingTitle = createElement("h2", "sr-only", "기록 상세");
  loadingTitle.id = "history-detail-title";
  elements.detail?.append(loadingTitle);
  elements.detail?.append(createElement("p", "empty-state", "상세 기록을 불러오는 중입니다."));
  try {
    const [runPayload, tasksPayload, committeePayload, archivePayload] = await Promise.all([
      requestJson(API.run(runId)),
      requestJson(API.tasks(runId)),
      requestJson(API.runCommittee(runId)),
      requestJson(API.decision(runId)),
    ]);
    if (token !== state.detailToken) return;
    const committee = committeePayload.committee || null;
    const minutesPayload = committee?.session_id
      ? await requestJson(API.committeeMinutes(committee.session_id))
      : { minutes: null };
    if (token !== state.detailToken) return;
    renderDetail({
      run: asObject(runPayload.run),
      tasks: asArray(tasksPayload.tasks),
      committee,
      minutes: minutesPayload.minutes,
      archive: archivePayload.decision,
    });
  } catch (error) {
    clearElement(elements.detail);
    const errorTitle = createElement("h2", "sr-only", "기록 상세");
    errorTitle.id = "history-detail-title";
    elements.detail?.append(errorTitle);
    elements.detail?.append(createElement("p", "inline-error", `상세 기록 조회 실패. ${error.message}`));
  }
}

function renderDetail({ run, tasks, committee, minutes, archive }) {
  clearElement(elements.detail);
  const header = createElement("header", "history-detail__head");
  const titleGroup = createElement("div");
  titleGroup.append(createElement("p", "eyebrow", `${workflowInfo(run.workflow).label} · ${formatDateTime(run.completed_at || run.created_at)}`));
  const title = createElement("h2", "", run.ticker || "종목 미정");
  title.id = "history-detail-title";
  titleGroup.append(title);
  const badges = createElement("div", "badge-row");
  appendStatusBadge(badges, run.status);
  appendWorkflowBadge(badges, run.workflow);
  header.append(titleGroup, badges);
  elements.detail?.append(header);

  const actionRow = createElement("div", "history-detail__actions");
  const open = createElement("a", "button", "워크벤치에서 열기");
  open.href = `/analysis?run=${encodeURIComponent(run.run_id)}`;
  const runId = createElement("code", "run-code", run.run_id || "RUN ID 없음");
  actionRow.append(open, runId);
  elements.detail?.append(actionRow);

  if (run.error) elements.detail?.append(createElement("p", "inline-error", run.error));
  const decision = asObject(run.decision);
  const review = asObject(run.human_review);
  const decisionSection = createElement("section", "history-detail__section");
  decisionSection.append(createElement("h3", "", "최종 분석 초안"));
  if (Object.keys(decision).length) {
    const verdict = createElement("div", "decision-summary-line");
    verdict.append(createElement("strong", "", decision.recommendation || decision.action || "결론 없음"));
    verdict.append(createElement("span", "", formatPercent(decision.confidence)));
    const positionCap = Number(decision.position_cap_pct);
    const riskGateSummary = decision.risk_eligible === false
      ? "위험 정책상 신규 매수가 허용되지 않습니다."
      : Number.isFinite(positionCap) && positionCap > 0
        ? `위험 정책상 최대 비중은 ${positionCap.toFixed(2)}%입니다.`
        : "";
    const summary = [riskGateSummary, decision.summary].filter(Boolean).join(" ");
    decisionSection.append(verdict, createElement("p", "", summary || "요약 없음"));
    appendTwoLists(decisionSection, "핵심 근거", decision.key_points, "주요 리스크", decision.risks);
  } else {
    decisionSection.append(createElement("p", "empty-state", "이 실행에는 저장된 결정 초안이 없습니다."));
  }
  if (Object.keys(review).length) {
    const human = createElement("aside", "human-review-note");
    human.append(createElement("strong", "", `사람 결정 · ${review.decision || run.status}`));
    human.append(createElement("p", "", review.reason || review.rationale || "사유 없음"));
    decisionSection.append(human);
  }
  elements.detail?.append(decisionSection);

  const agentsSection = createElement("section", "history-detail__section");
  agentsSection.append(createElement("h3", "", `에이전트 보고서 · ${asArray(run.agents).length}건`));
  const agentGrid = createElement("div", "history-agent-grid");
  asArray(run.agents).forEach((agent) => {
    const card = createElement("article", "history-agent-card");
    const head = createElement("div", "history-agent-card__head");
    head.append(createElement("strong", "", roleLabel(agent.role)));
    appendStatusBadge(head, agent.status);
    card.append(head, createElement("p", "", compactText(agent.summary || agent.error, 210) || "보고 내용 없음"));
    agentGrid.append(card);
  });
  if (!asArray(run.agents).length) agentGrid.append(createElement("p", "empty-state", "저장된 에이전트 보고서가 없습니다."));
  agentsSection.append(agentGrid);
  elements.detail?.append(agentsSection);

  const operations = createElement("div", "history-detail__columns");
  const taskSection = createElement("section", "history-detail__section");
  taskSection.append(createElement("h3", "", `추가 업무 · ${tasks.length}건`));
  const taskList = createElement("ul", "compact-list");
  tasks.forEach((task) => taskList.append(createElement("li", "", `${roleLabel(task.role)} · ${task.title} · ${task.status}`)));
  if (!tasks.length) taskList.append(createElement("li", "empty-state", "추가 업무 없음"));
  taskSection.append(taskList);

  const meetingSection = createElement("section", "history-detail__section");
  meetingSection.append(createElement("h3", "", "AI 회의와 회의록"));
  if (committee) {
    meetingSection.append(createElement("p", "", `${committee.topic} · ${committee.status} · ${asArray(committee.turns).length}회 발언`));
    if (minutes) {
      meetingSection.append(createElement("h4", "", "위원장 요약"));
      meetingSection.append(createElement("p", "", minutes.chairman_summary || "요약 없음"));
      meetingSection.append(createElement("h4", "", "위원장 결론"));
      meetingSection.append(createElement("p", "", minutes.chairman_recommendation || "결론 없음"));
    }
  } else {
    meetingSection.append(createElement("p", "empty-state", "저장된 회의가 없습니다."));
  }
  operations.append(taskSection, meetingSection);
  elements.detail?.append(operations);

  if (archive) {
    const archiveNote = createElement("details", "archive-raw");
    archiveNote.append(createElement("summary", "", "아카이브 메타데이터"));
    const pre = createElement("pre");
    pre.textContent = JSON.stringify({
      candidate_status: archive.candidate_status,
      effective_status: archive.effective_status,
      scheduled_analysis: archive.scheduled_analysis,
      human_approved: archive.human_approved,
    }, null, 2);
    archiveNote.append(pre);
    elements.detail?.append(archiveNote);
  }
}

function appendTwoLists(parent, firstTitle, firstItems, secondTitle, secondItems) {
  const columns = createElement("div", "report-columns");
  [[firstTitle, firstItems], [secondTitle, secondItems]].forEach(([title, values]) => {
    const section = createElement("section");
    section.append(createElement("h4", "", title));
    const list = createElement("ul", "compact-list");
    asArray(values).slice(0, 8).forEach((item) => list.append(createElement("li", "", item)));
    if (!asArray(values).length) list.append(createElement("li", "empty-state", "저장된 항목 없음"));
    section.append(list);
    columns.append(section);
  });
  parent.append(columns);
}

function scheduleRefresh(refreshDetail = false) {
  state.detailRefreshPending ||= refreshDetail;
  if (state.refreshTimer) window.clearTimeout(state.refreshTimer);
  state.refreshTimer = window.setTimeout(() => {
    const shouldRefreshDetail = state.detailRefreshPending;
    state.detailRefreshPending = false;
    void loadHistory({ refreshDetail: shouldRefreshDetail });
  }, 400);
}

elements.filterForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  void loadHistory();
});
[elements.workflow, elements.status, elements.period].forEach((control) => control?.addEventListener("change", applyFilters));
elements.ticker?.addEventListener("input", applyFilters);
elements.list?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-history-run]");
  if (button) void loadDetail(button.dataset.historyRun);
});

await initSiteShell((payload) => scheduleRefresh(payload.run_id === state.selectedRunId));
await loadHistory();
