// 메인 허브에서 두 분석 작업공간과 최근 완료 이력을 요약한다.
import {
  API,
  appendMarketBadge,
  appendStatusBadge,
  appendWorkflowBadge,
  asArray,
  clearElement,
  compactText,
  createElement,
  formatDateTime,
  initSiteShell,
  requestJson,
  setText,
} from "./site-common.js?v=5";

const elements = {
  total: document.querySelector("#hub-total"),
  active: document.querySelector("#hub-active"),
  review: document.querySelector("#hub-review"),
  scheduled: document.querySelector("#hub-scheduled"),
  manualRuns: document.querySelector("#hub-manual-runs"),
  discoveryRuns: document.querySelector("#hub-discovery-runs"),
  recentRuns: document.querySelector("#hub-recent-runs"),
  live: document.querySelector("#site-live-region"),
};

let refreshTimer = null;

function runCard(run, compact = false) {
  const item = createElement("li", compact ? "hub-run hub-run--compact" : "hub-run");
  const link = createElement("a", "hub-run__link");
  link.href = `/analysis?run=${encodeURIComponent(run.run_id)}`;

  const header = createElement("div", "hub-run__head");
  header.append(createElement("strong", "hub-run__ticker", run.ticker || "종목 미정"));
  appendMarketBadge(header, run.market, run.ticker);
  appendStatusBadge(header, run.status);
  link.append(header);

  if (!compact) {
    const meta = createElement("div", "hub-run__meta");
    appendWorkflowBadge(meta, run.workflow);
    meta.append(createElement("time", "", formatDateTime(run.completed_at || run.created_at)));
    link.append(meta);
    link.append(createElement("p", "hub-run__message", compactText(run.message || run.error, 110) || "상세 실행을 확인하세요."));
  }
  item.append(link);
  return item;
}

function renderRunGroup(container, runs, emptyText) {
  const focusedControl = document.activeElement;
  const focusedHref = focusedControl instanceof HTMLAnchorElement && container?.contains(focusedControl)
    ? focusedControl.getAttribute("href")
    : null;
  clearElement(container);
  if (!container) return;
  if (!runs.length) {
    container.append(createElement("li", "empty-state", emptyText));
    return;
  }
  runs.forEach((run) => container.append(runCard(run)));
  if (focusedHref) {
    const restoredControl = Array.from(container.querySelectorAll("a[href]"))
      .find((control) => control.getAttribute("href") === focusedHref);
    restoredControl?.focus({ preventScroll: true });
  }
}

function renderRecent(container, runs) {
  const focusedControl = document.activeElement;
  const focusedHref = focusedControl instanceof HTMLAnchorElement && container?.contains(focusedControl)
    ? focusedControl.getAttribute("href")
    : null;
  clearElement(container);
  if (!container) return;
  if (!runs.length) {
    container.append(createElement("li", "empty-state", "완료된 분석이 아직 없습니다."));
    return;
  }
  runs.forEach((run) => container.append(runCard(run, true)));
  if (focusedHref) {
    const restoredControl = Array.from(container.querySelectorAll("a[href]"))
      .find((control) => control.getAttribute("href") === focusedHref);
    restoredControl?.focus({ preventScroll: true });
  }
}

async function loadHub() {
  try {
    const [runPayload, schedulePayload] = await Promise.all([
      requestJson(`${API.runs}?limit=80`),
      requestJson(API.schedules),
    ]);
    const runs = asArray(runPayload.runs);
    const schedules = asArray(schedulePayload.schedules);
    const activeStatuses = new Set(["queued", "scheduled", "claimed", "dispatched", "running"]);
    const terminalStatuses = new Set(["approved", "rejected", "hold", "complete", "failed"]);
    const activeSchedules = schedules.filter((schedule) => ["scheduled", "claimed", "dispatched"].includes(schedule.status));
    const statusSummary = runPayload.summary?.by_status;
    const hasStatusSummary = statusSummary && typeof statusSummary === "object";
    const activeCount = hasStatusSummary
      ? Array.from(activeStatuses).reduce((total, status) => total + Number(statusSummary[status] || 0), 0)
      : runs.filter((run) => activeStatuses.has(run.status)).length;
    const reviewCount = hasStatusSummary
      ? Number(statusSummary.review || 0)
      : runs.filter((run) => run.status === "review").length;

    setText(elements.total, runPayload.summary?.total ?? runs.length, "0");
    setText(elements.active, activeCount, "0");
    setText(elements.review, reviewCount, "0");
    setText(elements.scheduled, activeSchedules.length, "0");

    const manualRuns = runs.filter((run) => ["manual", "scheduled", "unknown"].includes(run.workflow)).slice(0, 4);
    const discoveryRuns = runs.filter((run) => run.workflow === "discovery").slice(0, 4);
    const recent = runs.filter((run) => terminalStatuses.has(run.status)).slice(0, 7);
    renderRunGroup(elements.manualRuns, manualRuns, "개별 종목 분석 내역이 없습니다.");
    renderRunGroup(elements.discoveryRuns, discoveryRuns, "종목 추천 심층분석 내역이 없습니다.");
    renderRecent(elements.recentRuns, recent);
    setText(elements.live, "운용 현황을 갱신했습니다.", "");
  } catch (error) {
    setText(elements.live, `운용 현황을 불러오지 못했습니다. ${error.message}`, "");
    [elements.manualRuns, elements.discoveryRuns, elements.recentRuns].forEach((container) => {
      clearElement(container);
      container?.append(createElement("li", "empty-state empty-state--error", error.message));
    });
  }
}

function scheduleRefresh() {
  if (refreshTimer) window.clearTimeout(refreshTimer);
  refreshTimer = window.setTimeout(loadHub, 350);
}

await initSiteShell(scheduleRefresh);
await loadHub();
