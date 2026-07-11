// 픽셀 투자 사무실의 API 상태와 실시간 상호작용을 관리한다.
(() => {
  "use strict";

  const API = Object.freeze({
    state: "/api/state",
    analyze: "/api/analyze",
    discoveryScreen: "/api/discoveries/screen",
    discoveryAnalyze: "/api/discoveries/analyze",
    events: "/api/events",
    run: (runId) => `/api/runs/${encodeURIComponent(runId)}`,
    review: (runId) => `/api/runs/${encodeURIComponent(runId)}/review`,
  });

  const TERMINAL_STATUSES = new Set(["approved", "rejected", "hold", "complete", "failed"]);
  const ACTIVE_STATUSES = new Set(["queued", "running"]);
  const REVIEWABLE_STATUSES = new Set(["review"]);
  const REVIEW_DECISION_VALUES = Object.freeze({
    approve: "approved",
    hold: "deferred",
    reject: "rejected",
  });
  const DISCOVERY_RUNS_STORAGE_KEY = "pixel-office-discovery-runs";
  const DISCOVERY_ACTIVE_STATUSES = new Set(["queued", "running"]);
  const DISCOVERY_TERMINAL_STATUSES = new Set([
    "review",
    "approved",
    "rejected",
    "hold",
    "complete",
    "failed",
  ]);
  const MAX_VISIBLE_EVENTS = 50;

  const AGENTS = Object.freeze({
    fundamental: {
      label: "기본면",
      aliases: ["fundamental", "fundamentals", "base", "basic", "financial", "기본", "기본면"],
    },
    technical: {
      label: "기술",
      aliases: ["technical", "technicals", "chart", "priceaction", "기술", "차트"],
    },
    news: {
      label: "뉴스",
      aliases: ["news", "newswire", "macro", "newsmacro", "sentiment", "뉴스", "매크로", "심리"],
    },
    bull: {
      label: "BULL",
      aliases: ["bull", "bullish", "optimist", "upside", "강세", "낙관"],
    },
    bear: {
      label: "BEAR",
      aliases: ["bear", "bearish", "skeptic", "downside", "약세", "비관"],
    },
    chair: {
      label: "위원장",
      aliases: [
        "chair",
        "chairman",
        "committee",
        "synthesis",
        "coordinator",
        "headtrader",
        "riskmanager",
        "위원장",
        "종합",
      ],
    },
  });

  const elements = {
    body: document.body,
    analyzeForm: document.querySelector("#analyze-form"),
    analyzeButton: document.querySelector("#analyze-button"),
    ticker: document.querySelector("#ticker"),
    tickerError: document.querySelector("#ticker-error"),
    thesis: document.querySelector("#thesis"),
    thesisCount: document.querySelector("#thesis-count"),
    streamStatus: document.querySelector("#stream-status"),
    localClock: document.querySelector("#local-clock"),
    providerStatus: document.querySelector("#provider-status"),
    providerName: document.querySelector("#provider-name"),
    providerDetail: document.querySelector("#provider-detail"),
    providerAlert: document.querySelector("#provider-alert"),
    providerAlertCode: document.querySelector(".provider-alert__code"),
    providerError: document.querySelector("#provider-error-message"),
    dismissAlert: document.querySelector("#dismiss-alert"),
    runStatus: document.querySelector("#run-status-badge"),
    runId: document.querySelector("#run-id"),
    runTicker: document.querySelector("#run-ticker"),
    runStarted: document.querySelector("#run-started"),
    runProgress: document.querySelector("#run-progress"),
    runProgressBar: document.querySelector("#run-progress-bar"),
    runMessage: document.querySelector("#run-message"),
    agentFloor: document.querySelector("#agent-floor"),
    decisionCard: document.querySelector("#decision-card"),
    decisionRecommendation: document.querySelector("#decision-recommendation"),
    decisionCode: document.querySelector("#decision-code"),
    decisionSummary: document.querySelector("#decision-summary"),
    confidenceValue: document.querySelector("#confidence-value"),
    confidenceTrack: document.querySelector("#confidence-track"),
    confidenceBar: document.querySelector("#confidence-bar"),
    decisionRationale: document.querySelector("#decision-rationale"),
    decisionRisk: document.querySelector("#decision-risk p"),
    reviewLock: document.querySelector("#review-lock"),
    reviewForm: document.querySelector("#review-form"),
    reviewReason: document.querySelector("#review-reason"),
    reviewError: document.querySelector("#review-error"),
    reviewResult: document.querySelector("#review-result"),
    reviewButtons: Array.from(document.querySelectorAll("[data-decision]")),
    discoveryForm: document.querySelector("#dashboard-discovery-form"),
    discoveryStrategy: document.querySelector("#dashboard-discovery-strategy"),
    discoveryScanButton: document.querySelector("#dashboard-discovery-scan"),
    discoveryFeedback: document.querySelector("#dashboard-discovery-feedback"),
    discoveryMetrics: document.querySelector("#dashboard-discovery-metrics"),
    discoveryUniverse: document.querySelector("#dashboard-discovery-universe"),
    discoveryQualified: document.querySelector("#dashboard-discovery-qualified"),
    discoveryShortlist: document.querySelector("#dashboard-discovery-shortlist"),
    discoveryNotice: document.querySelector("#dashboard-discovery-notice"),
    discoverySelection: document.querySelector("#dashboard-discovery-selection"),
    discoveryEmpty: document.querySelector("#dashboard-discovery-empty"),
    discoveryCandidates: document.querySelector("#dashboard-discovery-candidates"),
    discoveryAnalyzeForm: document.querySelector("#dashboard-discovery-analyze-form"),
    discoveryAnalyzeButton: document.querySelector("#dashboard-discovery-analyze"),
    discoveryRunsEmpty: document.querySelector("#dashboard-discovery-runs-empty"),
    discoveryRuns: document.querySelector("#dashboard-discovery-runs"),
    discoveryStages: new Map(
      Array.from(document.querySelectorAll("[data-discovery-stage]")).map((stage) => [
        stage.dataset.discoveryStage,
        stage,
      ]),
    ),
    eventLog: document.querySelector("#event-log"),
    eventCount: document.querySelector("#event-count"),
    clearEvents: document.querySelector("#clear-events"),
    liveRegion: document.querySelector("#global-live-region"),
  };

  const agentRooms = new Map(
    Array.from(document.querySelectorAll("[data-agent]")).map((room) => [room.dataset.agent, room]),
  );

  const runtime = {
    currentRunId: null,
    currentRun: null,
    eventSource: null,
    pollingTimer: null,
    refreshTimer: null,
    eventCount: 0,
    submitting: false,
    reviewing: false,
    discovery: null,
    discoveryRuns: [],
    discoveryBatchId: null,
    discoveryPollTimer: null,
    discoveryScreening: false,
    discoveryLaunching: false,
    lastStreamErrorAt: 0,
    seenEventIds: new Set(),
  };

  const timeFormatter = new Intl.DateTimeFormat("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });

  const shortDateFormatter = new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });

  function firstDefined(...values) {
    return values.find((value) => value !== undefined && value !== null && value !== "");
  }

  function asObject(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function asArray(value) {
    if (Array.isArray(value)) return value;
    if (value === undefined || value === null || value === "") return [];
    return [value];
  }

  function textValue(value, fallback = "") {
    if (value === undefined || value === null) return fallback;
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      return String(value);
    }
    if (Array.isArray(value)) return value.map((item) => textValue(item)).filter(Boolean).join(" · ");
    return textValue(firstDefined(value.summary, value.message, value.text, value.reason), fallback);
  }

  function compactText(value, maxLength = 180) {
    const text = textValue(value).replace(/\s+/g, " ").trim();
    if (text.length <= maxLength) return text;
    return `${text.slice(0, Math.max(0, maxLength - 1)).trim()}…`;
  }

  function normalizedToken(value) {
    return textValue(value)
      .toLocaleLowerCase("en-US")
      .replace(/[\s_.\-/]/g, "");
  }

  function parseDate(value) {
    if (!value) return null;
    const numericValue = typeof value === "number" && value < 10_000_000_000 ? value * 1000 : value;
    const date = new Date(numericValue);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function formatShortDate(value) {
    const date = parseDate(value);
    return date ? shortDateFormatter.format(date) : "—";
  }

  function formatClock(value = new Date()) {
    const date = value instanceof Date ? value : parseDate(value) || new Date();
    return timeFormatter.format(date);
  }

  function announce(message) {
    elements.liveRegion.textContent = "";
    window.setTimeout(() => {
      elements.liveRegion.textContent = message;
    }, 20);
  }

  function setText(element, value, fallback = "—") {
    if (!element) return;
    element.textContent = textValue(value, fallback) || fallback;
  }

  function showAlert(message, code = "API FAULT") {
    if (!message) return;
    setText(elements.providerAlertCode, code);
    setText(elements.providerError, compactText(message, 360));
    elements.providerAlert.hidden = false;
  }

  function hideAlert() {
    elements.providerAlert.hidden = true;
  }

  function errorDetail(payload, fallback) {
    if (!payload) return fallback;
    if (typeof payload === "string") return payload;
    return textValue(
      firstDefined(payload.detail, payload.error, payload.message, payload.reason, payload.errors),
      fallback,
    );
  }

  async function requestJson(url, options = {}, timeoutMs = 20_000) {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    headers.set("Accept", "application/json");

    try {
      const response = await fetch(url, { ...options, headers, signal: controller.signal });
      const contentType = response.headers.get("content-type") || "";
      let payload = null;

      if (response.status !== 204) {
        if (contentType.includes("application/json")) {
          payload = await response.json();
        } else {
          const body = await response.text();
          const isHtmlError = contentType.includes("text/html") && !response.ok;
          payload = body && !isHtmlError ? { message: body } : null;
        }
      }

      if (!response.ok) {
        const error = new Error(errorDetail(payload, `요청이 실패했습니다. HTTP ${response.status}`));
        error.status = response.status;
        error.payload = payload;
        throw error;
      }

      return payload || {};
    } catch (error) {
      if (error.name === "AbortError") {
        throw new Error("API 응답 시간이 초과되었습니다.");
      }
      throw error;
    } finally {
      window.clearTimeout(timeoutId);
    }
  }

  function normalizeProvider(payload) {
    const root = asObject(payload);
    let source = firstDefined(root.provider, root.provider_state, root.llm_provider, root.model_provider, {});

    if (Array.isArray(source)) {
      source = source.find((item) => item?.primary) || source[0] || {};
    }
    if (typeof source === "string") source = { name: source };
    source = asObject(source);

    const rawStatus = normalizedToken(
      firstDefined(source.status, source.state, source.health, root.provider_status, root.provider_health, "checking"),
    );
    const online = ["ok", "ready", "online", "connected", "healthy", "available", "active"];
    const degraded = ["degraded", "warning", "ratelimited", "limited", "partial", "checking", "unknown"];
    const offline = ["error", "failed", "offline", "unavailable", "disconnected", "missing", "unauthorized"];
    let status = "checking";
    if (online.some((token) => rawStatus.includes(token))) status = "online";
    else if (offline.some((token) => rawStatus.includes(token))) status = "offline";
    else if (degraded.some((token) => rawStatus.includes(token))) status = "degraded";

    const name = textValue(
      firstDefined(source.name, source.provider, source.id, root.provider_name),
      "미보고",
    );
    const model = textValue(firstDefined(source.model, source.model_name, root.model, root.model_name));
    const detail = textValue(
      firstDefined(source.detail, source.message, model && `MODEL ${model}`),
      name === "미보고" ? "provider 정보가 응답에 없습니다." : rawStatus || "상태 미보고",
    );
    const error = errorDetail(
      firstDefined(source.error, root.provider_error, root.error?.provider),
      "",
    );

    return { name, model, detail, error, status };
  }

  function renderProvider(provider) {
    elements.providerStatus.classList.remove("is-checking", "is-online", "is-degraded", "is-offline");
    elements.providerStatus.classList.add(`is-${provider.status}`);
    setText(elements.providerName, provider.name, "미보고");
    setText(elements.providerDetail, provider.detail, "상태 미보고");
    elements.providerStatus.setAttribute(
      "aria-label",
      `Provider ${provider.name}, ${provider.status}, ${provider.detail}`,
    );

    if (provider.error || provider.status === "offline") {
      showAlert(provider.error || `${provider.name} provider가 오프라인 상태입니다.`, "PROVIDER FAULT");
    } else if (!runtime.submitting && !runtime.reviewing) {
      hideAlert();
    }
  }

  function normalizeRunStatus(run) {
    const raw = normalizedToken(firstDefined(run.status, run.state, run.phase, run.run_status, "idle"));
    const review = asObject(firstDefined(run.review, run.human_review));
    const reviewDecision = normalizedToken(firstDefined(review.decision, run.review_decision));

    if (["approve", "approved", "accept", "accepted"].includes(reviewDecision)) return "approved";
    if (["reject", "rejected", "decline", "declined"].includes(reviewDecision)) return "rejected";
    if (["hold", "held", "defer", "deferred", "pending"].includes(reviewDecision)) return "hold";
    if (["approved", "approve", "accepted"].some((token) => raw === token)) return "approved";
    if (["rejected", "reject", "declined"].some((token) => raw === token)) return "rejected";
    if (["hold", "held", "deferred", "onhold"].some((token) => raw === token)) return "hold";
    if (["failed", "failure", "error", "cancelled", "canceled"].some((token) => raw.includes(token))) {
      return "failed";
    }
    if (["pendingreview", "awaitingreview", "humanreview", "review", "needsapproval"].some((token) => raw.includes(token))) {
      return "review";
    }
    if (["running", "analyzing", "inprogress", "processing", "executing", "synthesizing"].some((token) => raw.includes(token))) {
      return "running";
    }
    if (["queued", "pending", "created", "submitted", "starting"].some((token) => raw.includes(token))) {
      return "queued";
    }
    if (["completed", "complete", "done", "finished", "success"].some((token) => raw.includes(token))) {
      const hasDecision = Boolean(firstDefined(run.decision, run.synthesis, run.committee_decision, run.recommendation));
      return hasDecision && !reviewDecision ? "review" : "complete";
    }
    return "idle";
  }

  function runStatusMeta(status) {
    const states = {
      idle: ["IDLE", "분석 대기 중입니다."],
      queued: ["QUEUED", "분석 작업이 대기열에 등록되었습니다."],
      running: ["RUNNING", "분석 에이전트가 작업 중입니다."],
      review: ["HUMAN GATE", "위원회 초안이 사람의 결정을 기다립니다."],
      approved: ["APPROVED", "사람 검토를 거쳐 승인되었습니다."],
      rejected: ["REJECTED", "사람 검토를 거쳐 기각되었습니다."],
      hold: ["ON HOLD", "추가 검토를 위해 보류되었습니다."],
      complete: ["COMPLETE", "작업이 완료되었습니다."],
      failed: ["FAILED", "분석 실행이 실패했습니다. 오류를 확인하세요."],
    };
    return states[status] || states.idle;
  }

  function extractAgentEntries(run) {
    const source = firstDefined(
      run.agents,
      run.agent_results,
      run.agent_outputs,
      run.analyses,
      run.outputs,
      run.results,
      [],
    );
    if (Array.isArray(source)) return source.map((item) => asObject(item));
    if (source && typeof source === "object") {
      return Object.entries(source).map(([key, value]) => ({
        ...(typeof value === "object" && value !== null ? value : { output: value }),
        __fallbackKey: key,
      }));
    }
    return [];
  }

  function resolveAgentKey(entry) {
    const candidate = normalizedToken(
      firstDefined(
        entry.agent_id,
        entry.agent,
        entry.role,
        entry.name,
        entry.type,
        entry.kind,
        entry.__fallbackKey,
      ),
    );
    if (!candidate) return null;

    return (
      Object.entries(AGENTS).find(([key, definition]) => {
        return candidate === key || definition.aliases.some((alias) => candidate.includes(normalizedToken(alias)));
      })?.[0] || null
    );
  }

  function normalizeAgentStatus(entry, runStatus = "idle") {
    const raw = normalizedToken(firstDefined(entry.status, entry.state, entry.phase, entry.activity));
    if (entry.error || ["failed", "error", "cancelled", "canceled"].some((token) => raw.includes(token))) {
      return "failed";
    }
    if (["waiting", "needsinput", "approval", "blocked", "paused"].some((token) => raw.includes(token))) {
      return "waiting";
    }
    if (["running", "working", "analyzing", "reading", "searching", "processing", "synthesizing"].some((token) => raw.includes(token))) {
      return "working";
    }
    if (["queued", "pending", "created", "assigned"].some((token) => raw.includes(token))) return "queued";
    if (["completed", "complete", "done", "finished", "success"].some((token) => raw.includes(token))) {
      return "done";
    }
    if (firstDefined(entry.output, entry.result, entry.summary, entry.conclusion)) return "done";
    if (runStatus === "running" || runStatus === "queued") return "queued";
    return "idle";
  }

  function agentStatusLabel(status) {
    return {
      idle: "IDLE",
      queued: "QUEUED",
      working: "WORKING",
      waiting: "WAITING",
      done: "DONE",
      failed: "FAULT",
    }[status] || "IDLE";
  }

  function updateAgentRoom(key, status, task) {
    const room = agentRooms.get(key);
    if (!room) return;
    const safeStatus = ["idle", "queued", "working", "waiting", "done", "failed"].includes(status)
      ? status
      : "idle";
    const statusLabel = agentStatusLabel(safeStatus);
    const taskElement = room.querySelector(".agent-task");
    const statusElement = room.querySelector(".agent-status");
    room.dataset.status = safeStatus;
    setText(taskElement, compactText(task, 92), safeStatus === "idle" ? "호출 대기" : statusLabel);
    setText(statusElement, statusLabel);
    room.setAttribute("aria-label", `${AGENTS[key].label} 분석가, ${statusLabel}, ${taskElement.textContent}`);
  }

  function renderAgents(run, runStatus) {
    const entries = extractAgentEntries(run);
    const assigned = new Set();

    entries.forEach((entry) => {
      const key = resolveAgentKey(entry);
      if (!key) return;
      const status = normalizeAgentStatus(entry, runStatus);
      const task = firstDefined(
        entry.current_task,
        entry.task,
        entry.activity,
        entry.message,
        entry.summary,
        entry.output?.summary,
        entry.output,
        entry.result?.summary,
        entry.error,
      );
      updateAgentRoom(key, status, task);
      assigned.add(key);
    });

    Object.keys(AGENTS).forEach((key) => {
      if (assigned.has(key)) return;
      if (ACTIVE_STATUSES.has(runStatus)) {
        updateAgentRoom(key, "queued", "작업 배정 대기");
      } else if (runStatus === "failed") {
        updateAgentRoom(key, "idle", "실행 중단");
      } else if (!runtime.currentRunId || runStatus === "idle") {
        updateAgentRoom(key, "idle", key === "chair" ? "의견 취합 대기" : "호출 대기");
      }
    });
  }

  function extractDecision(run) {
    let source = firstDefined(run.decision, run.synthesis, run.committee_decision, run.recommendation, {});
    if (typeof source === "string") source = { recommendation: source };
    source = asObject(source);

    const recommendation = textValue(
      firstDefined(source.recommendation, source.decision, source.verdict, source.action, run.recommendation),
    );
    const summary = textValue(
      firstDefined(source.summary, source.conclusion, source.rationale, source.reasoning, run.summary),
    );
    const rationaleSource = firstDefined(
      source.key_points,
      source.reasons,
      source.evidence,
      source.rationale_points,
      Array.isArray(source.rationale) ? source.rationale : null,
    );
    const rationale = asArray(rationaleSource)
      .map((item) => compactText(item, 220))
      .filter(Boolean)
      .slice(0, 5);
    const risks = asArray(firstDefined(source.risks, source.risk_flags, source.caveats, source.dissent, run.risks))
      .map((item) => compactText(item, 180))
      .filter(Boolean);
    const confidenceRaw = firstDefined(source.confidence, source.confidence_score, run.confidence);
    let confidence = Number(confidenceRaw);
    if (!Number.isFinite(confidence)) confidence = null;
    if (confidence !== null && confidence <= 1) confidence *= 100;
    if (confidence !== null) confidence = Math.max(0, Math.min(100, confidence));

    return { recommendation, summary, rationale, risks, confidence, raw: source };
  }

  function normalizeRecommendation(value) {
    const raw = normalizedToken(value);
    if (["approve", "approved", "buy", "invest", "advance", "positive", "bull", "편입", "승인"].some((token) => raw.includes(normalizedToken(token)))) {
      return { className: "approve", code: "GO", label: "승인 제안" };
    }
    if (["hold", "wait", "defer", "neutral", "watch", "보류", "대기"].some((token) => raw.includes(normalizedToken(token)))) {
      return { className: "hold", code: "HOLD", label: "보류 제안" };
    }
    if (["reject", "rejected", "sell", "pass", "avoid", "negative", "bear", "기각", "제외"].some((token) => raw.includes(normalizedToken(token)))) {
      return { className: "reject", code: "NO-GO", label: "기각 제안" };
    }
    return { className: "empty", code: value ? "OPEN" : "—", label: value || "결정 대기" };
  }

  function replaceList(element, items, fallback) {
    element.replaceChildren();
    const values = items.length ? items : [fallback];
    values.forEach((item) => {
      const listItem = document.createElement("li");
      listItem.textContent = item;
      element.append(listItem);
    });
  }

  function renderDecision(run, runStatus) {
    const decision = extractDecision(run);
    const meta = normalizeRecommendation(decision.recommendation);
    elements.decisionCard.classList.remove("is-empty", "is-approve", "is-hold", "is-reject", "is-error");
    elements.decisionCard.classList.add(`is-${runStatus === "failed" ? "error" : meta.className}`);
    setText(elements.decisionRecommendation, runStatus === "failed" ? "분석 실패" : meta.label, "결정 대기");
    setText(elements.decisionCode, runStatus === "failed" ? "FAULT" : meta.code);
    setText(
      elements.decisionSummary,
      firstDefined(
        decision.summary,
        run.error && errorDetail(run.error, ""),
        runStatus === "review" ? "위원장 초안이 도착했으나 요약 필드가 비어 있습니다." : null,
      ),
      "분석이 완료되면 위원장의 초안과 근거가 이곳에 표시됩니다.",
    );
    replaceList(elements.decisionRationale, decision.rationale, "등록된 근거가 없습니다.");
    const visibleRisks = decision.risks.slice(0, 5);
    const hiddenRiskCount = decision.risks.length - visibleRisks.length;
    const riskSummary = visibleRisks.join(" · ");
    setText(
      elements.decisionRisk,
      riskSummary
        ? `${riskSummary}${hiddenRiskCount > 0 ? ` · 그 외 ${hiddenRiskCount}건` : ""}`
        : "명시적으로 보고된 리스크가 없습니다.",
    );

    const confidence = decision.confidence;
    elements.confidenceBar.style.width = confidence === null ? "0%" : `${confidence}%`;
    setText(elements.confidenceValue, confidence === null ? "—" : `${Math.round(confidence)}%`);
    elements.confidenceTrack.setAttribute("aria-valuenow", String(Math.round(confidence || 0)));
  }

  function extractReview(run) {
    let review = firstDefined(run.review, run.human_review, null);
    if (typeof review === "string") review = { decision: review };
    review = asObject(review);
    const decision = textValue(firstDefined(review.decision, run.review_decision));
    const reason = textValue(firstDefined(review.reason, review.comment, run.review_reason));
    return { decision, reason, exists: Boolean(decision) };
  }

  function setReviewEnabled(enabled) {
    elements.reviewReason.disabled = !enabled;
    elements.reviewButtons.forEach((button) => {
      button.disabled = !enabled || runtime.reviewing;
    });
    elements.reviewLock.classList.toggle("is-open", enabled);
    elements.reviewLock.classList.toggle("is-closed", !enabled && Boolean(runtime.currentRunId));
    setText(elements.reviewLock, enabled ? "AWAITING HUMAN" : runtime.currentRunId ? "LOCKED" : "NO RUN");
  }

  function renderReview(run, runStatus) {
    const review = extractReview(run);
    const reviewable = REVIEWABLE_STATUSES.has(runStatus) && !review.exists;
    setReviewEnabled(reviewable);

    if (review.exists) {
      const meta = normalizeRecommendation(review.decision);
      setText(elements.reviewResult, `결정 기록 · ${meta.label}${review.reason ? ` · ${review.reason}` : ""}`);
      if (review.reason && !elements.reviewReason.value) elements.reviewReason.value = review.reason;
    } else if (!reviewable && !runtime.reviewing) {
      setText(
        elements.reviewResult,
        runStatus === "failed" ? "실패한 실행은 승인할 수 없습니다." : "위원장 초안이 도착하면 결정 버튼이 활성화됩니다.",
      );
    } else if (!runtime.reviewing) {
      setText(elements.reviewResult, "사유를 입력한 뒤 사람의 결정을 기록하세요.");
    }
  }

  function calculateProgress(run, runStatus) {
    const raw = firstDefined(run.progress, run.progress_percent, run.percent_complete);
    if (typeof raw === "object" && raw !== null) {
      const value = Number(firstDefined(raw.percent, raw.value));
      if (Number.isFinite(value)) return Math.max(0, Math.min(100, value <= 1 ? value * 100 : value));
    }
    const numeric = Number(raw);
    if (Number.isFinite(numeric)) return Math.max(0, Math.min(100, numeric <= 1 ? numeric * 100 : numeric));

    const entries = extractAgentEntries(run);
    if (entries.length) {
      const done = entries.filter((entry) => ["done", "failed"].includes(normalizeAgentStatus(entry, runStatus))).length;
      return Math.min(100, (done / Object.keys(AGENTS).length) * 100);
    }
    if (["review", "approved", "rejected", "hold", "complete"].includes(runStatus)) return 100;
    if (runStatus === "running") return 20;
    if (runStatus === "queued") return 4;
    return 0;
  }

  function discoveryStrategyLabel(strategy) {
    return {
      balanced: "균형형",
      momentum: "모멘텀형",
      defensive: "방어형",
    }[String(strategy || "balanced").toLowerCase()] || "균형형";
  }

  function discoveryVerdictLabel(verdict) {
    return {
      review_first: "우선 검토",
      watch: "관찰 후보",
      exclude: "기준 미충족",
    }[String(verdict || "watch").toLowerCase()] || "관찰 후보";
  }

  function setDiscoveryFeedback(message, tone = "neutral") {
    setText(elements.discoveryFeedback, message, "");
    elements.discoveryFeedback?.classList.toggle("is-success", tone === "success");
    elements.discoveryFeedback?.classList.toggle("is-error", tone === "error");
  }

  function setDiscoveryStage(stage, status, label) {
    const element = elements.discoveryStages.get(stage);
    if (!element) return;
    element.dataset.status = status;
    setText(element.querySelector("output"), label, "대기");
  }

  function safeDiscoverySource(value) {
    try {
      const url = new URL(String(value || ""));
      return url.protocol === "https:" ? url.href : null;
    } catch {
      return null;
    }
  }

  function discoveryPayload(payload) {
    const root = asObject(firstDefined(payload?.data, payload));
    return asObject(firstDefined(root.discovery, root.screening, root.result, root));
  }

  function discoveryRunsPayload(payload) {
    if (Array.isArray(payload)) return payload;
    const root = asObject(firstDefined(payload?.data, payload));
    return asArray(firstDefined(root.runs, root.analyses, root.results));
  }

  function selectedDiscoveryTickers() {
    return Array.from(
      elements.discoveryCandidates?.querySelectorAll('input[name="dashboard-discovery-ticker"]:checked') || [],
    ).map((input) => String(input.value || "").toUpperCase()).filter(Boolean);
  }

  function updateDiscoverySelection(changedInput = null) {
    let selected = selectedDiscoveryTickers();
    if (changedInput?.checked && selected.length > 3) {
      changedInput.checked = false;
      selected = selectedDiscoveryTickers();
      setDiscoveryFeedback("심층분석 후보는 최대 3개까지 선택할 수 있습니다.", "error");
    }
    setText(elements.discoverySelection, `${selected.length} / 3 SELECTED`);
    if (elements.discoveryAnalyzeButton) {
      elements.discoveryAnalyzeButton.disabled = selected.length === 0 || runtime.discoveryLaunching;
    }
  }

  function renderDiscoveryCandidates(candidates) {
    const values = asArray(candidates).slice(0, 8);
    elements.discoveryCandidates?.replaceChildren();
    if (elements.discoveryEmpty) elements.discoveryEmpty.hidden = values.length > 0;
    if (!elements.discoveryCandidates || !values.length) {
      updateDiscoverySelection();
      return;
    }

    values.forEach((candidate, index) => {
      const ticker = textValue(firstDefined(candidate.ticker, candidate.symbol)).toUpperCase();
      const reasons = asArray(firstDefined(candidate.reasons, candidate.key_points));
      const risks = asArray(candidate.risks);
      const item = document.createElement("li");
      item.className = "dashboard-candidate-card";

      const pick = document.createElement("label");
      pick.className = "dashboard-candidate-card__pick";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.name = "dashboard-discovery-ticker";
      checkbox.value = ticker;
      checkbox.checked = index < 3 && Boolean(ticker);
      checkbox.disabled = !ticker;

      const identity = document.createElement("span");
      identity.className = "dashboard-candidate-card__identity";
      const rank = document.createElement("small");
      rank.textContent = `RANK ${candidate.rank ?? index + 1} · ${discoveryVerdictLabel(candidate.verdict)}`;
      const symbol = document.createElement("strong");
      symbol.textContent = ticker || "종목 미정";
      identity.append(rank, symbol);

      const score = document.createElement("span");
      score.className = "dashboard-candidate-card__score";
      const scoreLabel = document.createElement("small");
      scoreLabel.textContent = "SCORE";
      const scoreValue = Number(candidate.score);
      score.append(scoreLabel, document.createTextNode(Number.isFinite(scoreValue) ? scoreValue.toFixed(2) : "—"));
      pick.append(checkbox, identity, score);

      const signals = document.createElement("div");
      signals.className = "dashboard-candidate-card__signals";
      const reason = document.createElement("p");
      const reasonLabel = document.createElement("strong");
      reasonLabel.textContent = "선별 근거";
      reason.append(reasonLabel, document.createTextNode(compactText(reasons[0], 112) || "근거 요약 없음"));
      const risk = document.createElement("p");
      const riskLabel = document.createElement("strong");
      riskLabel.textContent = "위험 신호";
      risk.append(riskLabel, document.createTextNode(compactText(risks[0], 112) || "위험 신호 미보고"));
      signals.append(reason, risk);
      item.append(pick, signals);

      const sourceUrl = safeDiscoverySource(firstDefined(candidate.source_url, candidate.source));
      if (sourceUrl) {
        const source = document.createElement("a");
        source.className = "dashboard-candidate-card__source";
        source.href = sourceUrl;
        source.target = "_blank";
        source.rel = "noreferrer";
        source.textContent = "가격 데이터 출처 확인 ↗";
        item.append(source);
      }
      elements.discoveryCandidates.append(item);
    });
    updateDiscoverySelection();
  }

  function renderDiscovery(discovery) {
    runtime.discovery = discovery;
    const candidates = asArray(discovery?.candidates);
    if (elements.discoveryMetrics) elements.discoveryMetrics.hidden = !discovery;
    setText(elements.discoveryUniverse, discovery?.universe_size, "—");
    setText(elements.discoveryQualified, discovery?.qualified_count, "—");
    setText(elements.discoveryShortlist, candidates.length, "0");
    const omitted = Number(discovery?.omitted_count || 0);
    const safetyNotice = textValue(
      firstDefined(discovery?.safety_notice, discovery?.disclaimer),
      "가격·거래량 기반 심층검토 후보이며 매수 또는 수익을 보장하지 않습니다.",
    );
    setText(
      elements.discoveryNotice,
      omitted > 0 ? `${safetyNotice} 표시 한도 밖의 기준 통과 종목이 ${omitted}개 더 있습니다.` : safetyNotice,
    );
    renderDiscoveryCandidates(candidates);
    setDiscoveryStage("scan", "done", `${discovery?.evaluated_count ?? discovery?.universe_size ?? 0} / ${discovery?.universe_size ?? 30}`);
    setDiscoveryStage("shortlist", candidates.length ? "done" : "error", `${candidates.length}개`);
    setDiscoveryStage("agents", "idle", candidates.length ? "선택 대기" : "후보 없음");
    setDiscoveryStage("review", "idle", "대기");
  }

  function loadStoredDiscoveryRuns() {
    try {
      const stored = JSON.parse(window.localStorage.getItem(DISCOVERY_RUNS_STORAGE_KEY) || "[]");
      if (!Array.isArray(stored)) return [];
      return stored
        .filter((run) => run && typeof run === "object" && (run.run_id || run.id))
        .slice(0, 12);
    } catch {
      return [];
    }
  }

  function discoveryRunId(run) {
    return textValue(firstDefined(run?.run_id, run?.id));
  }

  function mergeDiscoveryRuns(preferredRuns, fallbackRuns = []) {
    const fallbacks = new Map(
      asArray(fallbackRuns)
        .map((run) => [discoveryRunId(run), asObject(run)])
        .filter(([runId]) => runId),
    );
    const merged = [];
    const seen = new Set();

    for (const run of asArray(preferredRuns)) {
      const runId = discoveryRunId(run);
      if (!runId || seen.has(runId)) continue;
      merged.push({ ...asObject(fallbacks.get(runId)), ...asObject(run), run_id: runId });
      seen.add(runId);
    }
    for (const run of asArray(fallbackRuns)) {
      const runId = discoveryRunId(run);
      if (!runId || seen.has(runId)) continue;
      merged.push({ ...asObject(run), run_id: runId });
      seen.add(runId);
    }
    return merged.slice(0, 12);
  }

  function saveDiscoveryRuns(runs) {
    const merged = mergeDiscoveryRuns(runs, loadStoredDiscoveryRuns());
    try {
      const compact = merged.map((run) => ({
        run_id: discoveryRunId(run),
        ticker: textValue(firstDefined(run.ticker, run.symbol)).toUpperCase(),
        status: normalizeRunStatus(run),
        discovery_batch_id: textValue(run.discovery_batch_id),
      })).filter((run) => run.run_id);
      const serialized = JSON.stringify(compact);
      if (window.localStorage.getItem(DISCOVERY_RUNS_STORAGE_KEY) !== serialized) {
        window.localStorage.setItem(DISCOVERY_RUNS_STORAGE_KEY, serialized);
      }
    } catch {
      // 저장소를 사용할 수 없어도 현재 탭에서 진행 상태를 계속 추적한다.
    }
    return merged;
  }

  function discoveryRunIsTerminal(run) {
    return DISCOVERY_TERMINAL_STATUSES.has(normalizeRunStatus(run));
  }

  function renderDiscoveryStagesFromRuns(runs) {
    if (!runs.length) return;
    const statuses = runs.map((run) => normalizeRunStatus(run));
    const activeCount = statuses.filter((status) => DISCOVERY_ACTIVE_STATUSES.has(status)).length;
    const failedCount = statuses.filter((status) => status === "failed").length;
    const reviewCount = statuses.filter((status) => status === "review").length;
    const decidedCount = statuses.filter((status) => ["approved", "rejected", "hold", "complete"].includes(status)).length;
    if (activeCount > 0) {
      setDiscoveryStage("agents", "active", `${runs.length - activeCount} / ${runs.length}`);
    } else if (failedCount === runs.length) {
      setDiscoveryStage("agents", "error", "전체 실패");
    } else {
      setDiscoveryStage("agents", failedCount ? "error" : "done", `${runs.length - failedCount} / ${runs.length}`);
    }
    if (reviewCount > 0) {
      setDiscoveryStage("review", "active", `${reviewCount}건 대기`);
    } else if (decidedCount > 0) {
      setDiscoveryStage("review", "done", `${decidedCount}건 기록`);
    } else if (failedCount > 0 && activeCount === 0) {
      setDiscoveryStage("review", "error", "검토 불가");
    } else {
      setDiscoveryStage("review", "idle", "분석 대기");
    }
  }

  function discoveryStageRuns(runs) {
    const values = asArray(runs);
    const storedBatchId = textValue(values[0]?.discovery_batch_id);
    if (!runtime.discoveryBatchId && storedBatchId) runtime.discoveryBatchId = storedBatchId;
    if (runtime.discoveryBatchId) {
      const currentBatch = values.filter(
        (run) => textValue(run.discovery_batch_id) === runtime.discoveryBatchId,
      );
      if (currentBatch.length) return currentBatch;
    }
    return values.slice(0, 3);
  }

  function renderDiscoveryRuns(runs, { persist = true } = {}) {
    const values = persist ? saveDiscoveryRuns(asArray(runs)) : asArray(runs).slice(0, 12);
    const activeElement = document.activeElement;
    const focusedRunId = (
      activeElement instanceof HTMLElement
      && elements.discoveryRuns?.contains(activeElement)
    ) ? textValue(activeElement.dataset.discoveryRunId) : "";
    runtime.discoveryRuns = values;
    elements.discoveryRuns?.replaceChildren();
    if (elements.discoveryRunsEmpty) elements.discoveryRunsEmpty.hidden = values.length > 0;
    if (!elements.discoveryRuns || !values.length) return;

    for (const run of values) {
      const runId = textValue(firstDefined(run.run_id, run.id));
      const ticker = textValue(firstDefined(run.ticker, run.symbol), "종목 미정").toUpperCase();
      const status = normalizeRunStatus(run);
      const [statusLabel, defaultMessage] = runStatusMeta(status);
      const progress = calculateProgress(run, status);
      const agents = extractAgentEntries(run);
      const completedAgents = agents.filter((agent) => normalizeAgentStatus(agent, status) === "done").length;
      const item = document.createElement("li");
      item.className = "dashboard-discovery-run";
      item.dataset.status = status;

      const heading = document.createElement("div");
      heading.className = "dashboard-discovery-run__head";
      const symbol = document.createElement("strong");
      symbol.textContent = ticker;
      const statusElement = document.createElement("span");
      statusElement.textContent = statusLabel;
      heading.append(symbol, statusElement);

      const meta = document.createElement("div");
      meta.className = "dashboard-discovery-run__meta";
      const agentCount = document.createElement("span");
      agentCount.textContent = `${Math.min(completedAgents, 6)} / 6 AGENTS`;
      const progressText = document.createElement("span");
      progressText.textContent = `${Math.round(progress)}%`;
      meta.append(agentCount, progressText);

      const track = document.createElement("div");
      track.className = "dashboard-discovery-run__track";
      track.setAttribute("role", "progressbar");
      track.setAttribute("aria-label", `${ticker} 심층분석 진행률`);
      track.setAttribute("aria-valuemin", "0");
      track.setAttribute("aria-valuemax", "100");
      track.setAttribute("aria-valuenow", String(Math.round(progress)));
      const bar = document.createElement("span");
      bar.style.width = `${progress}%`;
      track.append(bar);

      const message = document.createElement("p");
      message.className = "dashboard-discovery-run__message";
      message.textContent = compactText(firstDefined(run.message, run.error, defaultMessage), 160);
      const openButton = document.createElement("button");
      openButton.type = "button";
      openButton.className = "dashboard-discovery-run__open";
      openButton.dataset.discoveryRunId = runId;
      openButton.textContent = status === "review" ? "의사결정 카드에서 검토" : "현재 작업표에서 자세히 보기";
      openButton.disabled = !runId;
      item.append(heading, meta, track, message, openButton);
      elements.discoveryRuns.append(item);
    }
    if (focusedRunId) {
      const focusTarget = Array.from(
        elements.discoveryRuns.querySelectorAll("[data-discovery-run-id]"),
      ).find((button) => button.dataset.discoveryRunId === focusedRunId);
      focusTarget?.focus({ preventScroll: true });
    }
    const stageRuns = discoveryStageRuns(values);
    if (!runtime.discovery) {
      setDiscoveryStage("scan", "done", "이전 완료");
      setDiscoveryStage("shortlist", "done", `${stageRuns.length}개 선택`);
    }
    renderDiscoveryStagesFromRuns(stageRuns);
  }

  function stopDiscoveryPolling() {
    if (runtime.discoveryPollTimer) window.clearTimeout(runtime.discoveryPollTimer);
    runtime.discoveryPollTimer = null;
  }

  function scheduleDiscoveryPolling(delay = 2_800) {
    stopDiscoveryPolling();
    if (!runtime.discoveryRuns.some((run) => !discoveryRunIsTerminal(run))) return;
    runtime.discoveryPollTimer = window.setTimeout(() => {
      void pollDiscoveryRuns();
    }, delay);
  }

  async function pollDiscoveryRuns(forceRunId = "") {
    stopDiscoveryPolling();
    if (!runtime.discoveryRuns.length) return;
    const updated = await Promise.all(runtime.discoveryRuns.map(async (storedRun) => {
      const runId = discoveryRunId(storedRun);
      if (discoveryRunIsTerminal(storedRun) && runId !== forceRunId) return storedRun;
      if (!runId) return storedRun;
      try {
        const payload = await requestJson(API.run(runId), {}, 15_000);
        const run = asObject(firstDefined(payload.run, payload.data?.run, payload.data, payload));
        return {
          ...storedRun,
          ...run,
          run_id: runId,
          ticker: firstDefined(run.ticker, storedRun.ticker),
        };
      } catch (error) {
        return { ...storedRun, poll_error: error.message };
      }
    }));
    renderDiscoveryRuns(updated);
    const current = updated.find((run) => textValue(firstDefined(run.run_id, run.id)) === runtime.currentRunId);
    if (current) renderRun(current);
    if (updated.some((run) => !discoveryRunIsTerminal(run))) scheduleDiscoveryPolling();
  }

  function syncTrackedDiscoveryRun(runId, run) {
    if (!runId || !runtime.discoveryRuns.some((item) => discoveryRunId(item) === runId)) return;
    renderDiscoveryRuns(runtime.discoveryRuns.map((item) => (
      discoveryRunId(item) === runId
        ? { ...asObject(item), ...asObject(run), run_id: runId }
        : item
    )));
  }

  function syncDiscoveryRunsFromStorage(event) {
    if (event.key !== DISCOVERY_RUNS_STORAGE_KEY) return;
    let incoming = [];
    try {
      const parsed = JSON.parse(event.newValue || "[]");
      incoming = Array.isArray(parsed) ? parsed : [];
    } catch {
      return;
    }
    const merged = mergeDiscoveryRuns(incoming, runtime.discoveryRuns);
    const incomingBatchId = textValue(incoming[0]?.discovery_batch_id);
    if (incomingBatchId) runtime.discoveryBatchId = incomingBatchId;
    renderDiscoveryRuns(merged, { persist: false });
    scheduleDiscoveryPolling(350);
  }

  async function submitDiscoveryScreen(event) {
    event.preventDefault();
    if (runtime.discoveryScreening) return;
    runtime.discoveryScreening = true;
    elements.discoveryScanButton.disabled = true;
    const strategy = String(elements.discoveryStrategy?.value || "balanced");
    setDiscoveryFeedback(`${discoveryStrategyLabel(strategy)} 전략으로 30종목 완료 일봉을 비교하고 있습니다.`);
    setDiscoveryStage("scan", "active", "조회 중");
    setDiscoveryStage("shortlist", "idle", "대기");
    try {
      const payload = await requestJson(API.discoveryScreen, {
        method: "POST",
        body: JSON.stringify({ strategy, limit: 8 }),
      }, 120_000);
      const discovery = discoveryPayload(payload);
      renderDiscovery(discovery);
      const count = asArray(discovery.candidates).length;
      setDiscoveryFeedback(
        `${count}개 심층검토 후보를 선별했습니다. 상위 ${Math.min(3, count)}개를 기본 선택했습니다.`,
        "success",
      );
      addEvent({ source: "DISCOVERY", message: `${discoveryStrategyLabel(strategy)} 전략 후보 ${count}개 선별`, level: "complete" });
      announce("종목 발굴 결과가 준비되었습니다. 실제 주문은 생성되지 않습니다.");
    } catch (error) {
      setDiscoveryStage("scan", "error", "실패");
      setDiscoveryStage("shortlist", "error", "중단");
      setDiscoveryFeedback(`종목 발굴 실패. ${error.message}`, "error");
      addEvent({ source: "DISCOVERY API", message: error.message, level: "error" });
    } finally {
      runtime.discoveryScreening = false;
      elements.discoveryScanButton.disabled = false;
      updateDiscoverySelection();
    }
  }

  async function submitDiscoveryAnalysis(event) {
    event.preventDefault();
    if (runtime.discoveryLaunching) return;
    const tickers = selectedDiscoveryTickers();
    if (!tickers.length || tickers.length > 3) {
      setDiscoveryFeedback("심층분석 후보를 1개 이상 3개 이하로 선택하세요.", "error");
      return;
    }
    runtime.discoveryLaunching = true;
    elements.discoveryAnalyzeButton.disabled = true;
    elements.discoveryCandidates?.querySelectorAll("input").forEach((input) => { input.disabled = true; });
    setDiscoveryStage("agents", "active", "배정 중");
    setDiscoveryFeedback(`${tickers.join(", ")} 심층분석을 여섯 에이전트에게 배정하고 있습니다.`);
    try {
      const payload = await requestJson(API.discoveryAnalyze, {
        method: "POST",
        body: JSON.stringify({ tickers }),
      }, 45_000);
      const rawRuns = discoveryRunsPayload(payload);
      const batchId = `batch-${discoveryRunId(rawRuns[0]) || Date.now()}`;
      runtime.discoveryBatchId = batchId;
      const runs = rawRuns.map((run) => ({ ...asObject(run), discovery_batch_id: batchId }));
      renderDiscoveryRuns(runs);
      scheduleDiscoveryPolling(800);
      setDiscoveryFeedback(`${runs.length}개 종목의 심층분석을 시작했습니다. 아래 진행표가 자동 갱신됩니다.`, "success");
      addEvent({ source: "DISCOVERY", message: `${tickers.join(", ")} 심층분석 배정`, level: "system" });
      announce("선택한 추천 후보의 심층분석이 시작되었습니다.");
    } catch (error) {
      setDiscoveryStage("agents", "error", "배정 실패");
      setDiscoveryFeedback(`심층분석 시작 실패. ${error.message}`, "error");
      addEvent({ source: "DISCOVERY API", message: error.message, level: "error" });
    } finally {
      runtime.discoveryLaunching = false;
      elements.discoveryCandidates?.querySelectorAll("input").forEach((input) => {
        input.disabled = !input.value;
      });
      updateDiscoverySelection();
    }
  }

  function handleDiscoverySelection(event) {
    const input = event.target.closest('input[name="dashboard-discovery-ticker"]');
    if (!(input instanceof HTMLInputElement)) return;
    updateDiscoverySelection(input);
  }

  async function openDiscoveryRun(event) {
    const button = event.target.closest("[data-discovery-run-id]");
    if (!(button instanceof HTMLButtonElement)) return;
    const runId = String(button.dataset.discoveryRunId || "");
    if (!runId) return;
    button.disabled = true;
    try {
      const payload = await requestJson(API.run(runId), {}, 15_000);
      runtime.currentRunId = runId;
      renderRun(payload);
      addEvent({ source: "DISCOVERY", message: `RUN ${runId.slice(-8)}을 현재 작업표로 열었습니다.`, level: "system" });
      const target = normalizeRunStatus(runtime.currentRun || {}) === "review"
        ? document.querySelector(".decision-panel")
        : document.querySelector(".floor-panel");
      target?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    } catch (error) {
      setDiscoveryFeedback(`실행 상세 조회 실패. ${error.message}`, "error");
    } finally {
      button.disabled = false;
    }
  }

  function renderRun(payload) {
    const run = asObject(firstDefined(payload.run, payload.data?.run, payload.data, payload));
    const runId = textValue(firstDefined(run.run_id, run.id, run.uuid, runtime.currentRunId));
    if (runId) runtime.currentRunId = runId;
    runtime.currentRun = run;

    const status = normalizeRunStatus(run);
    const [statusLabel, defaultMessage] = runStatusMeta(status);
    const progress = calculateProgress(run, status);
    const entries = extractAgentEntries(run);
    const completedCount = entries.filter((entry) => ["done", "failed"].includes(normalizeAgentStatus(entry, status))).length;
    const ticker = textValue(firstDefined(run.ticker, run.symbol, run.candidate?.ticker, run.input?.ticker));
    const startedAt = firstDefined(run.started_at, run.created_at, run.submitted_at, run.updated_at);
    const runError = errorDetail(firstDefined(run.error, run.failure), "");

    elements.runStatus.className = `run-status is-${status}`;
    setText(elements.runStatus, statusLabel);
    setText(elements.runId, runId || "미배정");
    setText(elements.runTicker, ticker);
    setText(elements.runStarted, formatShortDate(startedAt));
    setText(elements.runProgress, `${Math.min(completedCount, 6)} / 6`);
    elements.runProgressBar.style.width = `${progress}%`;
    setText(
      elements.runMessage,
      firstDefined(run.message, run.status_message, run.current_activity, runError, defaultMessage),
    );

    elements.body.classList.toggle("is-busy", ACTIVE_STATUSES.has(status));
    renderAgents(run, status);
    renderDecision(run, status);
    renderReview(run, status);

    if (runError) showAlert(runError, "RUN FAULT");
    if (TERMINAL_STATUSES.has(status) || status === "review") stopPolling();
    else if (runtime.currentRunId && ACTIVE_STATUSES.has(status)) schedulePoll();
  }

  function renderIdle() {
    runtime.currentRun = null;
    runtime.currentRunId = null;
    elements.runStatus.className = "run-status is-idle";
    setText(elements.runStatus, "IDLE");
    setText(elements.runId, "미배정");
    setText(elements.runTicker, "—");
    setText(elements.runStarted, "—");
    setText(elements.runProgress, "0 / 6");
    elements.runProgressBar.style.width = "0%";
    setText(elements.runMessage, "분석 대기 중입니다.");
    Object.keys(AGENTS).forEach((key) => {
      updateAgentRoom(key, "idle", key === "chair" ? "의견 취합 대기" : "호출 대기");
    });
    renderDecision({}, "idle");
    renderReview({}, "idle");
  }

  async function fetchRun({ silent = false } = {}) {
    const requestedRunId = runtime.currentRunId;
    if (!requestedRunId) return null;
    try {
      const payload = await requestJson(API.run(requestedRunId), {}, 15_000);
      if (runtime.currentRunId !== requestedRunId) return null;
      renderRun(payload);
      return payload;
    } catch (error) {
      if (!silent) {
        showAlert(error.message, "RUN API FAULT");
        addEvent({ source: "RUN API", message: error.message, level: "error" });
      }
      schedulePoll(5_000);
      return null;
    }
  }

  function stopPolling() {
    if (runtime.pollingTimer) window.clearTimeout(runtime.pollingTimer);
    runtime.pollingTimer = null;
  }

  function schedulePoll(delay = 2_800) {
    stopPolling();
    if (!runtime.currentRunId) return;
    runtime.pollingTimer = window.setTimeout(() => fetchRun({ silent: true }), delay);
  }

  function normalizeStatePayload(payload) {
    const root = asObject(firstDefined(payload.data, payload));
    const activeRun = firstDefined(
      root.active_run,
      root.current_run,
      root.run,
      root.latest_run,
      Array.isArray(root.runs) ? root.runs[0] : null,
    );
    const activeRunId = textValue(
      firstDefined(
        typeof activeRun === "object" && activeRun ? activeRun.run_id : null,
        typeof activeRun === "object" && activeRun ? activeRun.id : null,
        typeof activeRun === "string" ? activeRun : null,
        root.active_run_id,
        root.current_run_id,
      ),
    );
    return { root, activeRun, activeRunId };
  }

  async function loadInitialState({ silent = false } = {}) {
    try {
      const payload = await requestJson(API.state, {}, 15_000);
      const { root, activeRun, activeRunId } = normalizeStatePayload(payload);
      renderProvider(normalizeProvider(root));

      asArray(firstDefined(root.events, root.recent_events)).slice(-12).forEach((event) => {
        addEvent(normalizeEvent(event, "STATE"));
      });

      if (activeRun && typeof activeRun === "object") {
        renderRun(activeRun);
      } else if (activeRunId) {
        runtime.currentRunId = activeRunId;
        await fetchRun({ silent });
      } else if (!runtime.currentRunId) {
        renderIdle();
      }

      const stateError = errorDetail(firstDefined(root.error, root.state_error), "");
      if (stateError) showAlert(stateError, "STATE FAULT");
      return payload;
    } catch (error) {
      renderProvider({
        name: "STATE API",
        detail: "GET /api/state 응답 없음",
        error: error.message,
        status: "offline",
      });
      if (!silent) addEvent({ source: "STATE API", message: error.message, level: "error" });
      return null;
    }
  }

  function setAnalyzeBusy(busy) {
    runtime.submitting = busy;
    elements.analyzeButton.disabled = busy;
    elements.ticker.disabled = busy;
    elements.thesis.disabled = busy;
    elements.body.classList.toggle("is-busy", busy || ACTIVE_STATUSES.has(normalizeRunStatus(runtime.currentRun || {})));
    const label = elements.analyzeButton.querySelector(".primary-action__label");
    setText(label, busy ? "접수 중…" : "위원회 분석 개시");
  }

  function validateTicker() {
    const ticker = elements.ticker.value.trim().toUpperCase();
    elements.ticker.value = ticker;
    if (!ticker) {
      setText(elements.tickerError, "종목 코드를 입력하세요.", "");
      elements.ticker.setAttribute("aria-invalid", "true");
      return null;
    }
    if (!/^[A-Z0-9][A-Z0-9.\-]{0,11}$/.test(ticker)) {
      setText(elements.tickerError, "영문·숫자·점·하이픈만 사용할 수 있습니다.", "");
      elements.ticker.setAttribute("aria-invalid", "true");
      return null;
    }
    setText(elements.tickerError, "", "");
    elements.ticker.removeAttribute("aria-invalid");
    return ticker;
  }

  async function submitAnalysis(event) {
    event?.preventDefault();
    if (runtime.submitting) return;
    const ticker = validateTicker();
    if (!ticker) {
      elements.ticker.focus();
      return;
    }

    const thesis = elements.thesis.value.trim();
    const body = thesis ? { ticker, thesis } : { ticker };
    setAnalyzeBusy(true);
    hideAlert();
    setText(elements.runMessage, `${ticker} 분석 요청을 접수하고 있습니다.`);
    addEvent({ source: "INTAKE", message: `${ticker} 분석 요청 전송`, level: "system" });

    try {
      const payload = await requestJson(API.analyze, {
        method: "POST",
        body: JSON.stringify(body),
      });
      const run = asObject(firstDefined(payload.run, payload.data, payload));
      const runId = textValue(firstDefined(payload.run_id, run.run_id, run.id, payload.id));
      if (!runId) throw new Error("분석 API 응답에 run_id가 없습니다.");

      runtime.currentRunId = runId;
      runtime.currentRun = null;
      elements.reviewReason.value = "";
      setText(elements.reviewResult, "위원장 초안이 도착하면 결정 버튼이 활성화됩니다.");
      renderRun({
        ...run,
        run_id: runId,
        ticker: firstDefined(run.ticker, ticker),
        thesis: firstDefined(run.thesis, thesis),
        status: firstDefined(run.status, "queued"),
      });
      addEvent({ source: "ORCHESTRATOR", message: `RUN ${runId} 생성`, level: "system" });
      announce(`${ticker} 분석 작업이 시작되었습니다.`);
      await fetchRun({ silent: true });
      schedulePoll();
    } catch (error) {
      showAlert(error.message, "ANALYZE FAULT");
      setText(elements.runMessage, error.message);
      addEvent({ source: "ANALYZE API", message: error.message, level: "error" });
      announce(`분석 요청 실패. ${error.message}`);
    } finally {
      setAnalyzeBusy(false);
    }
  }

  function setReviewBusy(busy) {
    runtime.reviewing = busy;
    const run = runtime.currentRun || {};
    const reviewable = REVIEWABLE_STATUSES.has(normalizeRunStatus(run)) && !extractReview(run).exists;
    elements.reviewReason.disabled = busy || !reviewable;
    elements.reviewButtons.forEach((button) => {
      button.disabled = busy || elements.reviewReason.disabled;
    });
  }

  async function submitReview(decision) {
    if (!runtime.currentRunId || runtime.reviewing) return;
    const reviewedRunId = runtime.currentRunId;
    const reason = elements.reviewReason.value.trim();
    setText(elements.reviewError, "", "");
    if (reason.length < 4) {
      setText(elements.reviewError, "결정 사유를 4자 이상 입력하세요.", "");
      elements.reviewReason.focus();
      return;
    }

    const apiDecision = REVIEW_DECISION_VALUES[decision];
    if (!apiDecision) return;
    const label = { approve: "승인", hold: "보류", reject: "기각" }[decision];
    setReviewBusy(true);
    setText(elements.reviewResult, `${label} 결정을 기록하고 있습니다…`);

    try {
      const payload = await requestJson(API.review(runtime.currentRunId), {
        method: "POST",
        body: JSON.stringify({ decision: apiDecision, reason }),
      });
      const candidateRun = firstDefined(payload.run, payload.data?.run);
      if (candidateRun && typeof candidateRun === "object") renderRun(candidateRun);
      else {
        runtime.currentRun = {
          ...asObject(runtime.currentRun),
          human_review: { decision: apiDecision, reason },
        };
        renderReview(runtime.currentRun, normalizeRunStatus(runtime.currentRun));
        await fetchRun({ silent: true });
      }
      syncTrackedDiscoveryRun(reviewedRunId, runtime.currentRun);
      setText(elements.reviewResult, `${label} 결정이 저널에 기록되었습니다. · ${reason}`);
      addEvent({ source: "HUMAN GATE", message: `${label} · ${reason}`, level: "review" });
      announce(`${label} 결정이 기록되었습니다.`);
      setReviewEnabled(false);
      elements.reviewResult.setAttribute("tabindex", "-1");
      elements.reviewResult.focus();
    } catch (error) {
      showAlert(error.message, "REVIEW FAULT");
      setText(elements.reviewError, error.message, "");
      setText(elements.reviewResult, "결정이 기록되지 않았습니다.");
      addEvent({ source: "REVIEW API", message: error.message, level: "error" });
      announce(`결정 기록 실패. ${error.message}`);
    } finally {
      setReviewBusy(false);
    }
  }

  function normalizeEvent(event, fallbackSource = "EVENT") {
    const value = asObject(event);
    const kind = textValue(firstDefined(value.kind, value.type, value.event, value.status));
    const source = textValue(
      firstDefined(value.source, value.agent_name, value.agent_id, value.agent, value.role, fallbackSource),
      fallbackSource,
    );
    const message = textValue(
      firstDefined(value.message, value.summary, value.detail, value.activity, value.status_message, kind),
      "상태 변경",
    );
    const rawLevel = normalizedToken(firstDefined(value.level, value.severity, kind));
    let level = "system";
    if (["error", "failed", "fault"].some((token) => rawLevel.includes(token))) level = "error";
    else if (["review", "approval", "human"].some((token) => rawLevel.includes(token))) level = "review";
    else if (["complete", "done", "success", "approved"].some((token) => rawLevel.includes(token))) level = "complete";
    return {
      id: textValue(firstDefined(value.event_id, value.id, value.seq)),
      source,
      message: compactText(message, 300),
      level,
      time: firstDefined(value.created_at, value.timestamp, value.time),
      raw: value,
    };
  }

  function addEvent(event) {
    const normalized = event.raw ? event : normalizeEvent(event);
    if (normalized.id) {
      if (runtime.seenEventIds.has(normalized.id)) return;
      runtime.seenEventIds.add(normalized.id);
      if (runtime.seenEventIds.size > 500) {
        runtime.seenEventIds.delete(runtime.seenEventIds.values().next().value);
      }
    }

    const entry = document.createElement("li");
    entry.className = `event-entry is-${normalized.level || "system"}`;
    const time = document.createElement("time");
    time.className = "mono";
    const eventDate = parseDate(normalized.time) || new Date();
    time.dateTime = eventDate.toISOString();
    time.textContent = formatClock(eventDate);
    const source = document.createElement("span");
    source.className = "event-source";
    source.textContent = compactText(normalized.source, 28) || "EVENT";
    const message = document.createElement("span");
    message.className = "event-message";
    message.textContent = normalized.message || "상태 변경";
    entry.append(time, source, message);

    if (runtime.eventCount === 0) elements.eventLog.replaceChildren();
    elements.eventLog.prepend(entry);
    while (elements.eventLog.children.length > MAX_VISIBLE_EVENTS) {
      elements.eventLog.lastElementChild.remove();
    }
    runtime.eventCount += 1;
    setText(elements.eventCount, `${String(runtime.eventCount).padStart(3, "0")} EVENTS`);
  }

  function updateAgentFromEvent(payload) {
    const entry = asObject(firstDefined(payload.agent_state, payload.agent, payload));
    const key = resolveAgentKey(entry);
    if (!key) return false;
    const status = normalizeAgentStatus(entry, normalizeRunStatus(runtime.currentRun || {}));
    const task = firstDefined(entry.message, entry.activity, entry.task, entry.summary, entry.error);
    updateAgentRoom(key, status, task);
    return true;
  }

  function eventRunId(payload) {
    return textValue(firstDefined(payload.run_id, payload.run?.run_id, payload.run?.id, payload.data?.run_id));
  }

  function queueRunRefresh(delay = 180) {
    if (runtime.refreshTimer) window.clearTimeout(runtime.refreshTimer);
    runtime.refreshTimer = window.setTimeout(() => fetchRun({ silent: true }), delay);
  }

  function handleServerEvent(rawData, eventType = "message", lastEventId = "") {
    let payload = rawData;
    if (typeof rawData === "string") {
      try {
        payload = JSON.parse(rawData);
      } catch {
        payload = { message: rawData };
      }
    }
    payload = asObject(payload);
    if (lastEventId && !payload.event_id) payload.event_id = lastEventId;
    if (!payload.type && eventType !== "message") payload.type = eventType;

    const normalized = normalizeEvent(payload, eventType.toUpperCase());
    if (eventType !== "heartbeat" && normalized.message) addEvent(normalized);

    const providerPayload = firstDefined(payload.provider, eventType === "provider" ? payload : null);
    if (providerPayload) renderProvider(normalizeProvider({ provider: providerPayload }));
    if (payload.provider_error) {
      renderProvider(normalizeProvider({ provider: { ...asObject(payload.provider), error: payload.provider_error } }));
    }

    const incomingRunId = eventRunId(payload);
    const belongsToDiscovery = runtime.discoveryRuns.some(
      (run) => textValue(firstDefined(run.run_id, run.id)) === incomingRunId,
    );
    if (
      incomingRunId
      && !runtime.currentRunId
      && !belongsToDiscovery
      && !runtime.discoveryLaunching
    ) {
      runtime.currentRunId = incomingRunId;
    }
    if (belongsToDiscovery && eventType === "review") {
      void pollDiscoveryRuns(incomingRunId);
    }
    if (incomingRunId && runtime.currentRunId && incomingRunId !== runtime.currentRunId) return;
    if (incomingRunId && !runtime.currentRunId) return;

    updateAgentFromEvent(payload);

    const runPayload = firstDefined(payload.run, eventType === "run" ? payload : null);
    if (runPayload && typeof runPayload === "object" && firstDefined(runPayload.status, runPayload.state, runPayload.agents)) {
      renderRun(runPayload);
    } else if (runtime.currentRunId && eventType !== "heartbeat") {
      queueRunRefresh();
    }
  }

  function setStreamStatus(status, label) {
    elements.streamStatus.className = `status-chip is-${status}`;
    elements.streamStatus.innerHTML = '<span class="status-lamp" aria-hidden="true"></span>';
    elements.streamStatus.append(document.createTextNode(label));
    elements.streamStatus.setAttribute("aria-label", `실시간 이벤트 ${label}`);
  }

  function connectEventStream() {
    if (!("EventSource" in window)) {
      setStreamStatus("degraded", "미지원");
      addEvent({ source: "EVENT LINK", message: "이 브라우저는 SSE를 지원하지 않아 조회 폴링만 사용합니다.", level: "error" });
      return;
    }
    runtime.eventSource?.close();
    setStreamStatus("connecting", "연결 중");
    const source = new EventSource(API.events);
    runtime.eventSource = source;

    source.onopen = () => {
      setStreamStatus("online", "연결됨");
      runtime.lastStreamErrorAt = 0;
      addEvent({ source: "EVENT LINK", message: "실시간 스트림 연결", level: "complete" });
    };

    source.onmessage = (event) => handleServerEvent(event.data, "message", event.lastEventId);
    ["state", "run", "agent", "provider", "analysis", "review", "fault", "heartbeat"].forEach((type) => {
      source.addEventListener(type, (event) => handleServerEvent(event.data, type, event.lastEventId));
    });

    source.onerror = () => {
      setStreamStatus(navigator.onLine ? "degraded" : "offline", navigator.onLine ? "재연결 중" : "네트워크 없음");
      const now = Date.now();
      if (now - runtime.lastStreamErrorAt > 12_000) {
        addEvent({
          source: "EVENT LINK",
          message: "SSE 연결이 끊겼습니다. 자동 재연결 중이며 실행 조회는 계속됩니다.",
          level: "error",
        });
        runtime.lastStreamErrorAt = now;
      }
      if (runtime.currentRunId) schedulePoll(1_500);
    };
  }

  function updateClock() {
    const now = new Date();
    elements.localClock.dateTime = now.toISOString();
    elements.localClock.textContent = formatClock(now);
  }

  function updateThesisCount() {
    setText(elements.thesisCount, `${String(elements.thesis.value.length).padStart(3, "0")}/800`);
  }

  function bindEvents() {
    elements.analyzeForm.addEventListener("submit", submitAnalysis);
    elements.discoveryForm?.addEventListener("submit", submitDiscoveryScreen);
    elements.discoveryAnalyzeForm?.addEventListener("submit", submitDiscoveryAnalysis);
    elements.discoveryCandidates?.addEventListener("change", handleDiscoverySelection);
    elements.discoveryRuns?.addEventListener("click", openDiscoveryRun);
    elements.ticker.addEventListener("input", () => {
      const caret = elements.ticker.selectionStart;
      elements.ticker.value = elements.ticker.value.toUpperCase();
      if (caret !== null) elements.ticker.setSelectionRange(caret, caret);
      if (elements.ticker.hasAttribute("aria-invalid")) validateTicker();
    });
    elements.ticker.addEventListener("blur", validateTicker);
    elements.thesis.addEventListener("input", updateThesisCount);
    elements.reviewButtons.forEach((button) => {
      button.addEventListener("click", () => submitReview(button.dataset.decision));
    });
    elements.dismissAlert.addEventListener("click", hideAlert);
    elements.clearEvents.addEventListener("click", () => {
      elements.eventLog.replaceChildren();
      runtime.eventCount = 0;
      setText(elements.eventCount, "000 EVENTS");
      addEvent({ source: "LOCAL UI", message: "화면의 이벤트 표시를 비웠습니다. 서버 저널은 변경되지 않습니다.", level: "system" });
    });

    document.addEventListener("keydown", (event) => {
      const withinAnalyzeForm = elements.analyzeForm.contains(document.activeElement);
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && withinAnalyzeForm) {
        event.preventDefault();
        submitAnalysis(event);
        return;
      }
      const editing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName);
      if (!editing && event.key === "/") {
        event.preventDefault();
        elements.ticker.focus();
      }
      if (event.key === "Escape" && !elements.providerAlert.hidden) {
        hideAlert();
      }
    });

    window.addEventListener("online", () => {
      addEvent({ source: "NETWORK", message: "네트워크 연결 복구", level: "complete" });
      connectEventStream();
      loadInitialState({ silent: true });
    });
    window.addEventListener("offline", () => {
      setStreamStatus("offline", "네트워크 없음");
      showAlert("브라우저가 오프라인 상태입니다.", "NETWORK FAULT");
    });
    window.addEventListener("storage", syncDiscoveryRunsFromStorage);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) {
        if (runtime.currentRunId) fetchRun({ silent: true });
        else loadInitialState({ silent: true });
        scheduleDiscoveryPolling(350);
      } else {
        stopDiscoveryPolling();
      }
    });
    window.addEventListener("beforeunload", () => {
      runtime.eventSource?.close();
      stopPolling();
      stopDiscoveryPolling();
    });
  }

  async function initialize() {
    bindEvents();
    updateThesisCount();
    updateClock();
    window.setInterval(updateClock, 1_000);
    renderIdle();
    renderDiscoveryRuns(loadStoredDiscoveryRuns());
    scheduleDiscoveryPolling(500);
    connectEventStream();
    await loadInitialState();
  }

  initialize();
})();
