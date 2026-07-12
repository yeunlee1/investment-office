// 메인 사이트의 공통 API 호출과 상태 표현, 상단 셸을 관리한다.
export const API = Object.freeze({
  state: "/api/state",
  runs: "/api/runs",
  run: (runId) => `/api/runs/${encodeURIComponent(runId)}`,
  analyze: "/api/analyze",
  schedules: "/api/schedules",
  schedule: (scheduleId) => `/api/schedules/${encodeURIComponent(scheduleId)}`,
  cancelSchedule: (scheduleId) => `/api/schedules/${encodeURIComponent(scheduleId)}/cancel`,
  discoveryScreen: "/api/discoveries/screen",
  discoveryAnalyze: "/api/discoveries/analyze",
  decisions: "/api/decisions",
  decision: (runId) => `/api/decisions/${encodeURIComponent(runId)}`,
  tasks: (runId) => `/api/runs/${encodeURIComponent(runId)}/tasks`,
  taskReport: (taskId) => `/api/tasks/${encodeURIComponent(taskId)}/report-requests`,
  taskResume: (taskId) => `/api/tasks/${encodeURIComponent(taskId)}/resume`,
  taskCancel: (taskId) => `/api/tasks/${encodeURIComponent(taskId)}/cancel`,
  runCommittee: (runId) => `/api/runs/${encodeURIComponent(runId)}/committee`,
  startCommittee: (runId) => `/api/runs/${encodeURIComponent(runId)}/committee/start`,
  committee: (sessionId) => `/api/committee/${encodeURIComponent(sessionId)}`,
  committeeCommands: (sessionId) => `/api/committee/${encodeURIComponent(sessionId)}/commands`,
  committeeMinutes: (sessionId) => `/api/committee/${encodeURIComponent(sessionId)}/minutes`,
  review: (runId) => `/api/runs/${encodeURIComponent(runId)}/review`,
  events: "/api/events",
  marketOverview: "/api/markets/overview",
  dataSources: "/api/data-sources",
});

export const ROLE_ORDER = Object.freeze([
  "fundamental",
  "technical",
  "news",
  "bull",
  "bear",
  "head_trader",
]);

const dateTimeFormatter = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const clockFormatter = new Intl.DateTimeFormat("ko-KR", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

const operationTimeFormatter = new Intl.DateTimeFormat("ko-KR", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

const OPERATION_STORAGE_KEY = "signal-foundry:site-operations:v1";
const OPERATION_TTL_MS = 24 * 60 * 60 * 1_000;
const OPERATION_RECENT_LIMIT = 6;
const RUN_SUCCESS_STATUSES = new Set([
  "approved",
  "complete",
  "completed",
  "done",
  "hold",
  "ready_for_review",
  "rejected",
  "review",
]);
const RUN_FAILURE_STATUSES = new Set(["cancelled", "canceled", "failed"]);
const TASK_CANCELLED_STATUSES = new Set(["cancelled", "canceled"]);
const operationRuntime = {
  active: new Map(),
  recent: [],
  initialized: false,
  timer: null,
  reconcileTimer: null,
  reconciling: false,
  scheduleRecoveryTimer: null,
  scheduleRecoveryInFlight: false,
};

export class ApiError extends Error {
  constructor(message, status = 0, payload = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

function apiFieldLabel(value) {
  return {
    decision: "결정",
    instructions: "업무 지시",
    market: "시장",
    participants: "참가자",
    reason: "사유",
    role: "역할",
    scheduled_for: "예약 시각",
    thesis: "분석 관점",
    ticker: "종목 코드",
    tickers: "종목 목록",
    title: "제목",
    topic: "회의 주제",
  }[String(value || "")] || String(value || "입력값");
}

function apiValidationMessage(value) {
  const message = String(value || "").trim();
  if (!message) return "입력값을 확인하세요.";
  if (/[가-힣]/.test(message)) return message.replace(/^Value error,\s*/i, "");
  if (/^Field required$/i.test(message)) return "필수 입력값입니다.";
  if (/^String should have at least \d+ characters?/i.test(message)) return "입력한 문장이 너무 짧습니다.";
  if (/^String should have at most \d+ characters?/i.test(message)) return "입력한 문장이 허용 길이를 초과했습니다.";
  if (/^List should have at least \d+ items?/i.test(message)) return "목록에 필요한 항목 수가 부족합니다.";
  if (/^List should have at most \d+ items?/i.test(message)) return "목록의 항목 수가 허용 범위를 초과했습니다.";
  if (/^Input should be/i.test(message)) return "입력값의 형식 또는 허용 범위를 확인하세요.";
  return "입력값이 올바르지 않습니다.";
}

export function formatApiErrorMessage(payload, status) {
  const detail = payload && typeof payload === "object" ? payload.detail : payload;
  if (typeof detail === "string" && detail.trim()) {
    if (/[가-힣]/.test(detail)) return detail.trim();
    return status >= 500
      ? "서버 내부 오류가 발생했습니다. 서버 로그를 확인하세요."
      : "요청을 처리하지 못했습니다. 입력값과 서버 상태를 확인하세요.";
  }
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (typeof item === "string") return apiValidationMessage(item);
      if (!item || typeof item !== "object") return "";
      const location = asArray(item.loc).filter((part) => part !== "body").map(apiFieldLabel).join(" · ");
      const message = apiValidationMessage(item.msg || item.message);
      return location ? `${location}: ${message}` : message;
    }).filter(Boolean);
    if (messages.length) return messages.join(" · ");
  }
  if (detail && typeof detail === "object") {
    const message = detail.message || detail.error || detail.reason;
    if (message && /[가-힣]/.test(String(message))) return String(message);
    if (message) return status >= 500
      ? "서버 내부 오류가 발생했습니다. 서버 로그를 확인하세요."
      : "요청을 처리하지 못했습니다. 입력값과 서버 상태를 확인하세요.";
  }
  return `서버 요청이 실패했습니다. 상태 코드 ${status}`;
}

function operationElements() {
  return {
    monitor: document.querySelector("#site-operation-monitor"),
    title: document.querySelector("#site-operation-title"),
    detail: document.querySelector("#site-operation-detail"),
    event: document.querySelector("#site-operation-event"),
    status: document.querySelector("#site-operation-status"),
    elapsed: document.querySelector("#site-operation-elapsed"),
    toggle: document.querySelector("#site-operation-toggle"),
    history: document.querySelector("#site-operation-history"),
    list: document.querySelector("#site-operation-list"),
    count: document.querySelector("#site-operation-count"),
    live: document.querySelector("#site-live-region"),
  };
}

function operationStatusLabel(status) {
  return {
    failed: "실패",
    idle: "대기",
    running: "작업 중",
    success: "완료",
    warning: "확인 필요",
  }[status] || "상태 확인";
}

function operationId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `operation-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function serializeOperationState() {
  try {
    const payload = {
      active: Array.from(operationRuntime.active.values()),
      recent: operationRuntime.recent.slice(0, OPERATION_RECENT_LIMIT),
    };
    window.sessionStorage.setItem(OPERATION_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // 브라우저 저장소를 사용할 수 없어도 현재 페이지의 작업 추적은 계속한다.
  }
}

function restoreOperationState() {
  try {
    const payload = JSON.parse(window.sessionStorage.getItem(OPERATION_STORAGE_KEY) || "{}");
    const now = Date.now();
    const interrupted = [];
    const active = asArray(payload.active).filter((entry) => {
      const updatedAt = Number(entry?.updatedAt || entry?.startedAt || 0);
      const valid = entry?.id && entry?.status === "running" && Number.isFinite(updatedAt) && now - updatedAt <= OPERATION_TTL_MS;
      const hasTrackedResources = Object.keys(entry.runStatuses || {}).length || Object.keys(entry.taskStatuses || {}).length;
      if (valid && !hasTrackedResources) {
        interrupted.push({
          ...entry,
          status: "warning",
          detail: "페이지가 전환되어 이 요청의 최종 결과를 확인하지 못했습니다. 필요한 경우 다시 실행하세요.",
          completedAt: now,
          updatedAt: now,
        });
        return false;
      }
      return valid;
    });
    operationRuntime.active = new Map(active.map((entry) => [entry.id, entry]));
    operationRuntime.recent = [...interrupted, ...asArray(payload.recent)]
      .filter((entry) => entry?.id && entry?.status !== "running" && Number.isFinite(Number(entry?.updatedAt || entry?.completedAt)))
      .slice(0, OPERATION_RECENT_LIMIT);
  } catch {
    operationRuntime.active = new Map();
    operationRuntime.recent = [];
  }
}

function latestActiveOperation() {
  return Array.from(operationRuntime.active.values()).sort(
    (left, right) => Number(right.updatedAt || 0) - Number(left.updatedAt || 0),
  )[0] || null;
}

function operationElapsedLabel(entry) {
  if (!entry?.startedAt) return "--";
  if (entry.status !== "running") return operationTimeFormatter.format(new Date(entry.completedAt || entry.updatedAt));
  const seconds = Math.max(0, Math.floor((Date.now() - Number(entry.startedAt)) / 1_000));
  if (seconds < 60) return `${seconds}초 경과`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}분 ${seconds % 60}초 경과`;
}

function renderOperationHistory(elements) {
  if (!elements.list) return;
  clearElement(elements.list);
  const entries = operationRuntime.recent.slice(0, OPERATION_RECENT_LIMIT);
  setText(elements.count, entries.length, "0");
  if (!entries.length) {
    elements.list.append(createElement("li", "operation-monitor__empty", "아직 기록된 작업이 없습니다."));
    return;
  }
  entries.forEach((entry) => {
    const item = createElement("li", "operation-monitor__item");
    item.dataset.state = entry.status;
    const status = createElement("span", "operation-monitor__item-status mono", operationStatusLabel(entry.status));
    const copy = createElement("span", "operation-monitor__item-copy");
    copy.append(createElement("strong", "", entry.title));
    copy.append(createElement("small", "", entry.detail));
    const completedAt = new Date(Number(entry.completedAt || entry.updatedAt || Date.now()));
    const time = createElement("time", "mono", operationTimeFormatter.format(completedAt));
    time.dateTime = completedAt.toISOString();
    item.append(status, copy, time);
    elements.list.append(item);
  });
}

function renderOperationMonitor() {
  const elements = operationElements();
  if (!elements.monitor) return;
  const active = latestActiveOperation();
  const entry = active || operationRuntime.recent[0] || null;
  const state = entry?.status || "idle";
  elements.monitor.dataset.state = state;
  elements.monitor.setAttribute("aria-busy", String(Boolean(active)));
  setText(elements.title, entry?.title || "명령 대기", "명령 대기");
  setText(
    elements.detail,
    entry?.detail || "작업을 요청하면 현재 단계와 결과가 여기에 표시됩니다.",
    "작업 상태 없음",
  );
  setText(elements.status, operationStatusLabel(state), "대기");
  setText(elements.elapsed, entry ? operationElapsedLabel(entry) : "--", "--");
  if (elements.elapsed) {
    const timestamp = entry?.completedAt || entry?.updatedAt || entry?.startedAt;
    elements.elapsed.dateTime = timestamp ? new Date(Number(timestamp)).toISOString() : "";
  }
  renderOperationHistory(elements);
}

function updateStoredOperation(id, updater) {
  const entry = operationRuntime.active.get(id);
  if (!entry) return null;
  updater(entry);
  entry.updatedAt = Date.now();
  operationRuntime.active.set(id, entry);
  serializeOperationState();
  renderOperationMonitor();
  return entry;
}

function finishStoredOperation(id, status, detail) {
  const entry = operationRuntime.active.get(id);
  if (!entry) return;
  entry.status = status;
  entry.detail = String(detail || entry.detail || "작업이 끝났습니다.");
  entry.updatedAt = Date.now();
  entry.completedAt = entry.updatedAt;
  operationRuntime.active.delete(id);
  operationRuntime.recent = [entry, ...operationRuntime.recent.filter((item) => item.id !== id)]
    .slice(0, OPERATION_RECENT_LIMIT);
  serializeOperationState();
  renderOperationMonitor();
  setText(operationElements().live, `${entry.title}. ${entry.detail}`, "");
}

function trackedStatus(payload, eventType) {
  const eventName = String(payload?.event_type || eventType || "").toLowerCase();
  if (eventName === "analysis_completed") return "completed";
  if (eventName === "analysis_failed") return "failed";
  if (eventName === "human_review_recorded") return "completed";
  if (eventType === "fault") return "failed";
  if (eventType === "scheduled_analysis") {
    return String(payload?.status || "running").toLowerCase();
  }
  if (["analysis", "review", "run"].includes(String(eventType || "").toLowerCase())) {
    return String(payload?.run_status || payload?.run?.status || payload?.data?.run_status || "running").toLowerCase();
  }
  return "running";
}

function ensureScheduledOperation(schedule, message = "") {
  const item = asObject(schedule);
  const runId = String(item.run_id || item.analysis_run_id || "");
  const status = String(item.status || "").toLowerCase();
  if (!runId || !["claimed", "dispatched", "running"].includes(status)) return false;
  if (Array.from(operationRuntime.active.values()).some((entry) => Object.hasOwn(entry.runStatuses || {}, runId))) {
    return false;
  }
  const ticker = String(item.ticker || "예약 종목");
  const detail = message || "실행 중인 예약 분석을 확인해 진행 상태 추적을 복구했습니다.";
  const operation = startSiteOperation({
    title: `${ticker} 예약 분석 실행`,
    detail,
  });
  operation.trackRuns([runId], detail);
  return true;
}

export function recoverActiveScheduledOperations(payload) {
  return asArray(asObject(payload).schedules).reduce(
    (count, schedule) => count + Number(ensureScheduledOperation(schedule)),
    0,
  );
}

function updateTrackedOperation(entry, runId, status, message) {
  const statuses = { ...(entry.runStatuses || {}) };
  if (!Object.hasOwn(statuses, runId)) return;
  statuses[runId] = status;
  entry.runStatuses = statuses;
  const values = Object.values(statuses);
  const doneCount = values.filter((value) => RUN_SUCCESS_STATUSES.has(value)).length;
  const failedCount = values.filter((value) => RUN_FAILURE_STATUSES.has(value)).length;
  const total = values.length;
  entry.detail = message || `${total}개 실행 중 ${doneCount + failedCount}개가 끝났습니다.`;
  entry.updatedAt = Date.now();
  operationRuntime.active.set(entry.id, entry);
  if (doneCount + failedCount === total) {
    const detail = failedCount
      ? `${total}개 실행 중 ${failedCount}개가 실패했습니다. 상세 화면에서 원인을 확인하세요.`
      : `${total}개 분석이 끝나 사람의 검토를 기다립니다.`;
    finishStoredOperation(entry.id, failedCount ? "failed" : "success", detail);
    return;
  }
  serializeOperationState();
  renderOperationMonitor();
}

function updateTrackedTask(entry, taskId, status, message) {
  const statuses = { ...(entry.taskStatuses || {}) };
  if (!Object.hasOwn(statuses, taskId)) return;
  statuses[taskId] = status;
  entry.taskStatuses = statuses;
  const values = Object.values(statuses);
  const doneCount = values.filter((value) => RUN_SUCCESS_STATUSES.has(value)).length;
  const failedCount = values.filter((value) => value === "failed").length;
  const cancelledCount = values.filter((value) => TASK_CANCELLED_STATUSES.has(value)).length;
  const total = values.length;
  entry.detail = message || `${total}개 업무 중 ${doneCount + failedCount + cancelledCount}개가 끝났습니다.`;
  entry.updatedAt = Date.now();
  operationRuntime.active.set(entry.id, entry);
  if (doneCount + failedCount + cancelledCount === total) {
    if (failedCount) {
      finishStoredOperation(entry.id, "failed", `${total}개 업무 중 ${failedCount}개가 실패했습니다. 업무 탭에서 오류를 확인하세요.`);
    } else if (cancelledCount) {
      finishStoredOperation(entry.id, "warning", `${cancelledCount}개 업무가 취소되어 실행을 마쳤습니다.`);
    } else {
      finishStoredOperation(entry.id, "success", `${total}개 에이전트 업무가 완료됐습니다.`);
    }
    return;
  }
  serializeOperationState();
  renderOperationMonitor();
}

function handleOperationEvent(payload, eventType) {
  const elements = operationElements();
  const message = String(payload?.message || "").trim();
  if (message) {
    setText(elements.event, message, "새 이벤트 대기");
    if (elements.event) elements.event.dataset.state = eventType === "fault" ? "failed" : "running";
  } else if (eventType === "provider") {
    setText(elements.event, "실시간 서버 이벤트 연결됨", "새 이벤트 대기");
    if (elements.event) elements.event.dataset.state = "connected";
  }
  const runId = String(payload?.run_id || "");
  const scheduleStatus = String(payload?.status || "").toLowerCase();
  if (eventType === "scheduled_analysis" && runId && ["claimed", "dispatched", "running"].includes(scheduleStatus)) {
    ensureScheduledOperation(payload, message || "예약 시각이 도래해 분석 실행을 시작하고 있습니다.");
  }
  if (runId) {
    const status = trackedStatus(payload, eventType);
    Array.from(operationRuntime.active.values()).forEach((entry) => {
      if (Object.hasOwn(entry.runStatuses || {}, runId)) updateTrackedOperation(entry, runId, status, message);
    });
  }
  const taskId = String(payload?.work_item_id || "");
  if (taskId) {
    const taskStatus = String(payload?.status || "running").toLowerCase();
    Array.from(operationRuntime.active.values()).forEach((entry) => {
      if (Object.hasOwn(entry.taskStatuses || {}, taskId)) updateTrackedTask(entry, taskId, taskStatus, message);
    });
  }
}

async function reconcileTrackedOperations() {
  if (operationRuntime.reconciling) return;
  operationRuntime.reconciling = true;
  try {
    const runIds = Array.from(operationRuntime.active.values())
      .flatMap((entry) => Object.keys(entry.runStatuses || {}))
      .filter((runId, index, values) => runId && values.indexOf(runId) === index)
      .slice(0, 12);
    await Promise.all(runIds.map(async (runId) => {
      try {
        const payload = await requestJson(API.run(runId), {}, 15_000);
        const run = asObject(payload.run);
        const status = String(run.status || "running").toLowerCase();
        Array.from(operationRuntime.active.values()).forEach((entry) => {
          if (Object.hasOwn(entry.runStatuses || {}, runId)) {
            updateTrackedOperation(entry, runId, status, String(run.message || ""));
          }
        });
      } catch {
        // 실시간 이벤트가 다시 도착할 수 있으므로 일시적인 재조회 실패로 추적을 끝내지 않는다.
      }
    }));
    const taskRunIds = Array.from(operationRuntime.active.values())
      .flatMap((entry) => Object.values(entry.taskRunIds || {}))
      .map((runId) => String(runId || ""))
      .filter((runId, index, values) => runId && values.indexOf(runId) === index)
      .slice(0, 12);
    await Promise.all(taskRunIds.map(async (runId) => {
      try {
        const payload = await requestJson(API.tasks(runId), {}, 15_000);
        asArray(payload.tasks).forEach((task) => {
          const taskId = String(task?.id || "");
          const status = String(task?.status || "running").toLowerCase();
          Array.from(operationRuntime.active.values()).forEach((entry) => {
            if (Object.hasOwn(entry.taskStatuses || {}, taskId)) {
              updateTrackedTask(entry, taskId, status, String(task?.error || task?.message || ""));
            }
          });
        });
      } catch {
        // 업무 SSE가 다시 도착할 수 있으므로 일시적인 재조회 실패로 추적을 끝내지 않는다.
      }
    }));
  } finally {
    operationRuntime.reconciling = false;
  }
}

function buildOperationHandle(id) {
  return Object.freeze({
    id,
    update(detail) {
      updateStoredOperation(id, (entry) => { entry.detail = String(detail || entry.detail); });
    },
    trackRuns(runIds, detail = "서버가 분석 작업을 실행하고 있습니다.") {
      const values = asArray(runIds).map((runId) => String(runId || "")).filter(Boolean);
      updateStoredOperation(id, (entry) => {
        entry.detail = detail;
        entry.runStatuses = Object.fromEntries(values.map((runId) => [runId, "queued"]));
      });
      void reconcileTrackedOperations();
    },
    trackTasks(tasks, detail = "담당 에이전트가 업무를 실행하고 있습니다.") {
      const values = asArray(tasks).map((task) => ({
        id: String(task?.id || ""),
        runId: String(task?.runId || task?.analysis_run_id || ""),
      })).filter((task) => task.id && task.runId);
      updateStoredOperation(id, (entry) => {
        entry.detail = detail;
        entry.taskStatuses = Object.fromEntries(values.map((task) => [task.id, "queued"]));
        entry.taskRunIds = Object.fromEntries(values.map((task) => [task.id, task.runId]));
      });
      void reconcileTrackedOperations();
    },
    succeed(detail) {
      finishStoredOperation(id, "success", detail);
    },
    warn(detail) {
      finishStoredOperation(id, "warning", detail);
    },
    fail(detail) {
      finishStoredOperation(id, "failed", detail);
    },
  });
}

export function startSiteOperation({ title, detail, key = "" }) {
  initOperationMonitor();
  if (key) {
    const existing = Array.from(operationRuntime.active.values()).find((entry) => entry.key === key);
    if (existing) return buildOperationHandle(existing.id);
  }
  const now = Date.now();
  const entry = {
    id: operationId(),
    key,
    title: String(title || "작업 처리"),
    detail: String(detail || "요청을 서버에 전달하고 있습니다."),
    status: "running",
    startedAt: now,
    updatedAt: now,
    completedAt: null,
    runStatuses: {},
    taskStatuses: {},
    taskRunIds: {},
  };
  operationRuntime.active.set(entry.id, entry);
  serializeOperationState();
  renderOperationMonitor();
  setText(operationElements().live, `${entry.title}. ${entry.detail}`, "");
  return buildOperationHandle(entry.id);
}

export function setButtonBusy(button, busy, busyLabel = "처리 중") {
  if (!(button instanceof HTMLButtonElement)) return;
  const label = button.querySelector("[data-button-label]") || button.querySelector("span") || button;
  if (busy) {
    if (!button.dataset.idleLabel) button.dataset.idleLabel = label.textContent || "";
    label.textContent = busyLabel;
    button.classList.add("is-busy");
    button.setAttribute("aria-busy", "true");
    button.disabled = true;
    return;
  }
  if (button.dataset.idleLabel !== undefined) label.textContent = button.dataset.idleLabel;
  delete button.dataset.idleLabel;
  button.classList.remove("is-busy");
  button.removeAttribute("aria-busy");
  button.disabled = false;
}

function initOperationMonitor() {
  if (operationRuntime.initialized) return;
  operationRuntime.initialized = true;
  restoreOperationState();
  const elements = operationElements();
  elements.toggle?.addEventListener("click", () => {
    const expanded = elements.toggle.getAttribute("aria-expanded") === "true";
    elements.toggle.setAttribute("aria-expanded", String(!expanded));
    if (elements.history) elements.history.hidden = expanded;
  });
  renderOperationMonitor();
  operationRuntime.timer = window.setInterval(renderOperationMonitor, 1_000);
  operationRuntime.reconcileTimer = window.setInterval(() => {
    void reconcileTrackedOperations();
  }, 10_000);
  void reconcileTrackedOperations();
}

export async function requestJson(url, options = {}, timeoutMs = 20_000) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  try {
    const response = await fetch(url, { ...options, headers, signal: controller.signal });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      throw new ApiError(formatApiErrorMessage(payload, response.status), response.status, payload);
    }
    return payload;
  } catch (error) {
    if (error?.name === "AbortError") throw new ApiError("요청 시간이 초과되었습니다.");
    if (error instanceof TypeError) throw new ApiError("로컬 서버에 연결할 수 없습니다. 서버 실행 상태를 확인하세요.");
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

export function asArray(value) {
  return Array.isArray(value) ? value : [];
}

export function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

export function createElement(tag, className = "", text = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== "") element.textContent = String(text);
  return element;
}

export function clearElement(element) {
  element?.replaceChildren();
}

export function setText(element, value, fallback = "—") {
  if (!element) return;
  const nextValue = value === null || value === undefined || value === "" ? fallback : String(value);
  if (element.textContent !== nextValue) element.textContent = nextValue;
}

export function setFeedback(element, message, tone = "neutral") {
  if (!element) return;
  setText(element, message, "");
  element.dataset.tone = tone;
  element.setAttribute("role", "status");
  element.setAttribute("aria-live", "polite");
  element.setAttribute("aria-atomic", "true");
}

export function formatDateTime(value, fallback = "—") {
  if (!value) return fallback;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? fallback : dateTimeFormatter.format(date);
}

export function formatPercent(value, fallback = "—") {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  const normalized = number <= 1 ? number * 100 : number;
  return `${Math.round(normalized)}%`;
}

export function compactText(value, maxLength = 180) {
  const normalized = String(value || "").replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`;
}

export function classifyDiscoveryOutcome(discovery) {
  const candidates = asArray(discovery?.candidates);
  const excluded = asArray(discovery?.excluded);
  const universeSize = Number(discovery?.universe_size || 0);
  const evaluatedCount = Number(discovery?.evaluated_count || 0);
  const failedCount = excluded.filter((item) => !item?.eod).length;
  const unavailableCount = Math.max(0, universeSize - evaluatedCount);
  if (evaluatedCount === 0) {
    const reason = compactText(asArray(excluded[0]?.reasons)[0], 180) || "가격 데이터 공급원이 준비되지 않았습니다.";
    return {
      state: "failed",
      message: `${universeSize || 30}개 종목 모두 가격 데이터 단계에서 제외되어 실제 평가는 0건입니다. ${reason}`,
    };
  }
  if (evaluatedCount < universeSize || failedCount) {
    return {
      state: "warning",
      message: `${universeSize}개 중 ${evaluatedCount}개를 평가했고 ${unavailableCount}개는 평가할 자료가 부족했습니다. 이 중 가격 조회 실패는 ${failedCount}개이며 후보 ${candidates.length}개를 확인하세요.`,
    };
  }
  return {
    state: "success",
    message: candidates.length
      ? `${evaluatedCount}개를 모두 평가해 후보 ${candidates.length}개를 선별했습니다. 매수 보장이 아닌 심층검토 대상입니다.`
      : `${evaluatedCount}개를 모두 평가했지만 현재 기준을 충족한 후보는 없습니다.`,
  };
}

export function statusInfo(status) {
  const key = String(status || "idle").toLowerCase();
  const values = {
    idle: ["대기", "idle"],
    queued: ["대기열", "queued"],
    scheduled: ["예약됨", "scheduled"],
    claimed: ["실행 준비", "running"],
    dispatched: ["실행 시작", "running"],
    running: ["분석 중", "running"],
    stop_requested: ["종료 중", "running"],
    review: ["검토 필요", "review"],
    approved: ["승인", "approved"],
    rejected: ["기각", "rejected"],
    hold: ["보류", "hold"],
    complete: ["완료", "complete"],
    completed: ["완료", "complete"],
    done: ["완료", "complete"],
    failed: ["실패", "failed"],
    missing: ["누락", "failed"],
    cancelled: ["취소", "cancelled"],
    canceled: ["취소", "cancelled"],
    stopped: ["중단", "cancelled"],
  };
  const [label, tone] = values[key] || [key || "상태 없음", "idle"];
  return { key, label, tone };
}

export function workflowInfo(workflow) {
  const key = String(workflow || "unknown").toLowerCase();
  return {
    manual: { key, label: "개별 종목", tone: "manual" },
    discovery: { key, label: "종목 추천", tone: "discovery" },
    scheduled: { key, label: "예약 분석", tone: "scheduled" },
    unknown: { key, label: "기존 미분류", tone: "unknown" },
  }[key] || { key, label: "기존 미분류", tone: "unknown" };
}

export function roleLabel(role) {
  return {
    fundamental: "기본면",
    technical: "차트 분석팀",
    news: "뉴스",
    sentiment: "심리",
    bull: "강세 논리",
    bear: "약세 논리",
    head_trader: "위원장",
    risk_manager: "리스크",
  }[String(role || "").toLowerCase()] || String(role || "에이전트");
}

export function runProgress(run) {
  const direct = Number(run?.progress);
  if (Number.isFinite(direct)) return Math.max(0, Math.min(100, direct));
  const agents = asArray(run?.agents);
  if (!agents.length) return ["review", "approved", "rejected", "hold", "complete"].includes(run?.status) ? 100 : 0;
  const completed = agents.filter((agent) => ["done", "completed", "failed"].includes(String(agent?.status || ""))).length;
  return Math.round((completed / 6) * 100);
}

export function appendStatusBadge(parent, status) {
  const info = statusInfo(status);
  const badge = createElement("span", "status-badge", info.label);
  badge.dataset.tone = info.tone;
  parent.append(badge);
  return badge;
}

export function appendWorkflowBadge(parent, workflow) {
  const info = workflowInfo(workflow);
  const badge = createElement("span", "workflow-badge", info.label);
  badge.dataset.tone = info.tone;
  parent.append(badge);
  return badge;
}

export function marketInfo(market, ticker = "") {
  const normalized = String(market || "").trim().toLowerCase();
  if (normalized === "us") return { key: "us", label: "미국" };
  if (normalized === "kr") return { key: "kr", label: "한국" };
  const symbol = String(ticker || "").trim().toUpperCase();
  if (/^(?:KR-)?\d{6}$/.test(symbol)) return { key: "kr", label: "한국" };
  return { key: "unknown", label: "시장 미정" };
}

export function appendMarketBadge(parent, market, ticker = "") {
  const info = marketInfo(market, ticker);
  const badge = createElement("span", "market-badge", info.label);
  badge.dataset.market = info.key;
  parent.append(badge);
  return badge;
}

export function safeSourceUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function updateClock() {
  const clock = document.querySelector("#site-clock");
  if (!clock) return;
  const now = new Date();
  clock.dateTime = now.toISOString();
  clock.textContent = clockFormatter.format(now);
}

function renderShellState(payload) {
  const state = asObject(payload);
  const providerElement = document.querySelector("#site-provider");
  const schedulerElement = document.querySelector("#site-scheduler");
  if (Object.hasOwn(state, "provider")) {
    const provider = asObject(state.provider);
    setText(providerElement, provider.name ? `${provider.name} · ${provider.status || "unknown"}` : "Provider 확인 중");
    if (providerElement) providerElement.dataset.status = provider.status === "ready" ? "ready" : "degraded";
  }
  if (Object.hasOwn(state, "scheduler")) {
    const scheduler = asObject(state.scheduler);
    setText(schedulerElement, scheduler.status === "ready" ? "예약 엔진 정상" : `예약 엔진 ${scheduler.status || "확인 중"}`);
    if (schedulerElement) schedulerElement.dataset.status = scheduler.status === "ready" ? "ready" : "degraded";
  }
}

async function restoreActiveScheduledOperations(attempt = 0) {
  if (operationRuntime.scheduleRecoveryInFlight) return;
  operationRuntime.scheduleRecoveryInFlight = true;
  const eventElement = operationElements().event;
  try {
    recoverActiveScheduledOperations(await requestJson(API.schedules));
    if (operationRuntime.scheduleRecoveryTimer) {
      window.clearTimeout(operationRuntime.scheduleRecoveryTimer);
      operationRuntime.scheduleRecoveryTimer = null;
    }
    if (eventElement?.textContent === "실행 중인 예약 작업 상태를 확인하지 못했습니다.") {
      setText(eventElement, "실행 중인 예약 작업 상태를 다시 확인했습니다.", "새 이벤트 대기");
      eventElement.dataset.state = "connected";
    }
  } catch {
    setText(eventElement, "실행 중인 예약 작업 상태를 확인하지 못했습니다.", "새 이벤트 대기");
    if (eventElement) eventElement.dataset.state = "failed";
    if (attempt < 2) {
      if (operationRuntime.scheduleRecoveryTimer) window.clearTimeout(operationRuntime.scheduleRecoveryTimer);
      operationRuntime.scheduleRecoveryTimer = window.setTimeout(() => {
        operationRuntime.scheduleRecoveryTimer = null;
        void restoreActiveScheduledOperations(attempt + 1);
      }, 1_500 * (attempt + 1));
    }
  } finally {
    operationRuntime.scheduleRecoveryInFlight = false;
  }
}

export async function initSiteShell(onEvent = null) {
  initOperationMonitor();
  updateClock();
  window.setInterval(updateClock, 1_000);
  try {
    renderShellState(await requestJson(API.state));
  } catch (error) {
    setText(document.querySelector("#site-provider"), `연결 확인 실패 · ${error.message}`);
  }

  if (!("EventSource" in window)) {
    void restoreActiveScheduledOperations();
    return null;
  }
  const source = new EventSource(API.events);
  const handler = (event) => {
    try {
      const payload = JSON.parse(event.data || "{}");
      if (payload.provider) renderShellState({ provider: payload.provider });
      handleOperationEvent(payload, event.type);
      if (typeof onEvent === "function") onEvent(payload, event.type);
    } catch {
      if (typeof onEvent === "function") onEvent({}, event.type);
    }
  };
  ["run", "analysis", "agent", "review", "schedule", "scheduled_analysis", "task", "work_item", "committee", "minutes", "provider", "fault"].forEach((type) => {
    source.addEventListener(type, handler);
  });
  source.addEventListener("open", () => {
    void restoreActiveScheduledOperations();
  });
  void restoreActiveScheduledOperations();
  source.onerror = () => {
    const providerElement = document.querySelector("#site-provider");
    if (providerElement) providerElement.dataset.status = "degraded";
    setText(operationElements().event, "실시간 연결 재시도 중", "새 이벤트 대기");
    void reconcileTrackedOperations();
  };
  window.addEventListener("beforeunload", () => {
    source.close();
    if (operationRuntime.timer) window.clearInterval(operationRuntime.timer);
    if (operationRuntime.reconcileTimer) window.clearInterval(operationRuntime.reconcileTimer);
    if (operationRuntime.scheduleRecoveryTimer) window.clearTimeout(operationRuntime.scheduleRecoveryTimer);
  }, { once: true });
  return source;
}
