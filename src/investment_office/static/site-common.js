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

export class ApiError extends Error {
  constructor(message, status = 0, payload = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
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
      const detail = typeof payload === "object" && payload ? payload.detail : payload;
      throw new ApiError(String(detail || `HTTP ${response.status}`), response.status, payload);
    }
    return payload;
  } catch (error) {
    if (error?.name === "AbortError") throw new ApiError("요청 시간이 초과되었습니다.");
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
  element.textContent = value === null || value === undefined || value === "" ? fallback : String(value);
}

export function setFeedback(element, message, tone = "neutral") {
  if (!element) return;
  setText(element, message, "");
  element.dataset.tone = tone;
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
    technical: "기술",
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

export async function initSiteShell(onEvent = null) {
  updateClock();
  window.setInterval(updateClock, 1_000);
  try {
    renderShellState(await requestJson(API.state));
  } catch (error) {
    setText(document.querySelector("#site-provider"), `연결 확인 실패 · ${error.message}`);
  }

  if (!("EventSource" in window)) return null;
  const source = new EventSource(API.events);
  const handler = (event) => {
    try {
      const payload = JSON.parse(event.data || "{}");
      if (payload.provider) renderShellState({ provider: payload.provider });
      if (typeof onEvent === "function") onEvent(payload, event.type);
    } catch {
      if (typeof onEvent === "function") onEvent({}, event.type);
    }
  };
  ["run", "analysis", "agent", "review", "schedule", "task", "work_item", "committee", "minutes", "provider", "fault"].forEach((type) => {
    source.addEventListener(type, handler);
  });
  source.onerror = () => {
    const providerElement = document.querySelector("#site-provider");
    if (providerElement) providerElement.dataset.status = "degraded";
  };
  window.addEventListener("beforeunload", () => source.close(), { once: true });
  return source;
}
