// 2D 투자 사무실의 이동, NPC, 상호작용과 분석 API 상태를 관리한다.
(() => {
  "use strict";

  const WORLD = Object.freeze({ width: 1440, height: 900, tile: 30 });
  const PLAYER_RADIUS = 17;
  const PLAYER_SPEED = 235;
  const INTERACTION_DISTANCE = 124;
  const DISCOVERY_RUNS_STORAGE_KEY = "pixel-office-discovery-runs";
  const API = Object.freeze({
    state: "/api/state",
    analyze: "/api/analyze",
    events: "/api/events",
    schedules: "/api/schedules",
    cancelSchedule: (scheduleId) => `/api/schedules/${encodeURIComponent(scheduleId)}/cancel`,
    decisions: "/api/decisions?limit=50",
    decision: (runId) => `/api/decisions/${encodeURIComponent(runId)}`,
    discoveryScreen: "/api/discoveries/screen",
    discoveryAnalyze: "/api/discoveries/analyze",
    run: (runId) => `/api/runs/${encodeURIComponent(runId)}`,
    review: (runId) => `/api/runs/${encodeURIComponent(runId)}/review`,
    tasks: (runId) => `/api/runs/${encodeURIComponent(runId)}/tasks`,
    taskReport: (taskId) => `/api/tasks/${encodeURIComponent(taskId)}/report-requests`,
    taskResume: (taskId) => `/api/tasks/${encodeURIComponent(taskId)}/resume`,
    taskCancel: (taskId) => `/api/tasks/${encodeURIComponent(taskId)}/cancel`,
    runCommittee: (runId) => `/api/runs/${encodeURIComponent(runId)}/committee`,
    startCommittee: (runId) => `/api/runs/${encodeURIComponent(runId)}/committee/start`,
    committee: (committeeId) => `/api/committee/${encodeURIComponent(committeeId)}`,
    committeeCommands: (committeeId) => `/api/committee/${encodeURIComponent(committeeId)}/commands`,
    committeeMinutes: (committeeId) => `/api/committee/${encodeURIComponent(committeeId)}/minutes`,
  });

  const ROLE_LABELS = Object.freeze({
    fundamental: "기본면 분석가",
    technical: "기술 분석가",
    news: "뉴스 분석가",
    bull: "BULL 연구원",
    bear: "BEAR 연구원",
    head_trader: "투자위원장",
  });

  const STATUS_LABELS = Object.freeze({
    idle: "대기",
    queued: "대기열",
    running: "분석 중",
    done: "보고 완료",
    failed: "오류",
  });

  const STATUS_COLORS = Object.freeze({
    idle: "#778078",
    queued: "#f5bd3f",
    running: "#42e8d2",
    done: "#65e58a",
    failed: "#ff6b61",
  });

  const ROOMS = Object.freeze([
    {
      id: "fundamental",
      role: "fundamental",
      label: "기본면 연구실",
      code: "FUNDAMENTALS // 01",
      x: 45,
      y: 105,
      width: 400,
      height: 210,
      color: "#d9aa36",
      desk: { x: 250, y: 215 },
      npc: { x: 170, y: 218 },
    },
    {
      id: "technical",
      role: "technical",
      label: "차트 분석실",
      code: "TECHNICAL // 02",
      x: 520,
      y: 105,
      width: 400,
      height: 210,
      color: "#42d6cf",
      desk: { x: 725, y: 215 },
      npc: { x: 645, y: 218 },
    },
    {
      id: "news",
      role: "news",
      label: "뉴스 와이어룸",
      code: "NEWSWIRE // 03",
      x: 995,
      y: 105,
      width: 400,
      height: 210,
      color: "#ff7168",
      desk: { x: 1200, y: 215 },
      npc: { x: 1120, y: 218 },
    },
    {
      id: "bull",
      role: "bull",
      label: "BULL 워룸",
      code: "UPSIDE CASE // 04",
      x: 45,
      y: 370,
      width: 400,
      height: 210,
      color: "#55df8c",
      desk: { x: 250, y: 480 },
      npc: { x: 170, y: 483 },
    },
    {
      id: "chair",
      role: "head_trader",
      label: "투자위원회실",
      code: "HUMAN GATE // 06",
      x: 520,
      y: 370,
      width: 400,
      height: 300,
      color: "#e8e3d4",
      desk: { x: 720, y: 495 },
      npc: { x: 720, y: 440 },
      committee: true,
    },
    {
      id: "bear",
      role: "bear",
      label: "BEAR 워룸",
      code: "DOWNSIDE CASE // 05",
      x: 995,
      y: 370,
      width: 400,
      height: 210,
      color: "#9a7bec",
      desk: { x: 1200, y: 480 },
      npc: { x: 1120, y: 483 },
    },
  ]);

  const INTAKE = Object.freeze({
    id: "intake",
    label: "후보 접수 데스크",
    code: "INTAKE // A-01",
    x: 45,
    y: 680,
    width: 350,
    height: 165,
    color: "#f6bd3d",
    desk: { x: 220, y: 760 },
  });

  const FURNITURE = Object.freeze([
    ...ROOMS.map((room) => ({
      x: room.desk.x - 58,
      y: room.desk.y - 20,
      width: 116,
      height: 48,
    })),
    { x: INTAKE.desk.x - 85, y: INTAKE.desk.y - 18, width: 170, height: 45 },
    { x: 1030, y: 700, width: 300, height: 80 },
    { x: 610, y: 720, width: 220, height: 44 },
  ]);

  const canvas = document.getElementById("office-canvas");
  const context = canvas?.getContext("2d", { alpha: false });
  if (!canvas || !context) return;

  const elements = Object.freeze({
    runStatus: document.getElementById("hud-run-status"),
    ticker: document.getElementById("hud-ticker"),
    progress: document.getElementById("hud-progress"),
    provider: document.getElementById("hud-provider"),
    zone: document.getElementById("hud-zone"),
    prompt: document.getElementById("hud-prompt"),
    status: document.getElementById("game-status"),
    dialog: document.getElementById("interaction-dialog"),
    dialogTitle: document.getElementById("dialog-title"),
    intakePanel: document.getElementById("intake-panel"),
    agentPanel: document.getElementById("agent-panel"),
    committeePanel: document.getElementById("committee-panel"),
    analysisForm: document.getElementById("game-analysis-form"),
    tickerInput: document.getElementById("game-ticker"),
    thesisInput: document.getElementById("game-thesis"),
    submitButton: document.getElementById("game-submit"),
    tickerError: document.getElementById("game-ticker-error"),
    scheduleForm: document.getElementById("schedule-analysis-form"),
    scheduleTicker: document.getElementById("schedule-ticker"),
    scheduleTime: document.getElementById("schedule-time"),
    scheduleThesis: document.getElementById("schedule-thesis"),
    scheduleSubmit: document.getElementById("schedule-submit"),
    scheduleError: document.getElementById("schedule-error"),
    scheduleFeedback: document.getElementById("schedule-feedback"),
    scheduleRefresh: document.getElementById("schedule-refresh"),
    scheduleEmpty: document.getElementById("schedule-empty"),
    scheduleList: document.getElementById("schedule-list"),
    discoveryScreenForm: document.getElementById("discovery-screen-form"),
    discoveryStrategy: document.getElementById("discovery-strategy"),
    discoveryScreenSubmit: document.getElementById("discovery-screen-submit"),
    discoveryFeedback: document.getElementById("discovery-feedback"),
    discoverySummary: document.getElementById("discovery-summary"),
    discoverySummaryStrategy: document.getElementById("discovery-summary-strategy"),
    discoverySummaryUniverse: document.getElementById("discovery-summary-universe"),
    discoverySummaryCount: document.getElementById("discovery-summary-count"),
    discoveryDisclaimer: document.getElementById("discovery-disclaimer"),
    discoveryExcluded: document.getElementById("discovery-excluded"),
    discoveryExcludedList: document.getElementById("discovery-excluded-list"),
    discoveryAnalyzeForm: document.getElementById("discovery-analyze-form"),
    discoveryCandidateList: document.getElementById("discovery-candidate-list"),
    discoveryEmpty: document.getElementById("discovery-empty"),
    discoverySelectionCount: document.getElementById("discovery-selection-count"),
    discoveryAnalyzeSubmit: document.getElementById("discovery-analyze-submit"),
    discoveryRunsEmpty: document.getElementById("discovery-runs-empty"),
    discoveryRunList: document.getElementById("discovery-run-list"),
    agentRole: document.getElementById("agent-detail-role"),
    agentStatus: document.getElementById("agent-detail-status"),
    agentSummary: document.getElementById("agent-detail-summary"),
    agentPoints: document.getElementById("agent-detail-points"),
    agentRisks: document.getElementById("agent-detail-risks"),
    taskForm: document.getElementById("agent-task-form"),
    taskRole: document.getElementById("agent-task-role"),
    taskTitle: document.getElementById("agent-task-title"),
    taskInstructions: document.getElementById("agent-task-instructions"),
    taskSubmit: document.getElementById("agent-task-submit"),
    taskFeedback: document.getElementById("agent-task-feedback"),
    taskEmpty: document.getElementById("agent-task-empty"),
    taskList: document.getElementById("agent-task-list"),
    taskCount: document.getElementById("agent-task-count"),
    committeeStartForm: document.getElementById("committee-start-form"),
    committeeTopic: document.getElementById("committee-topic"),
    committeeStart: document.getElementById("committee-start"),
    committeeFinish: document.getElementById("committee-finish"),
    committeeStop: document.getElementById("committee-stop"),
    committeeFeedback: document.getElementById("committee-feedback"),
    committeeStatus: document.getElementById("committee-session-status"),
    committeeTopicReadout: document.getElementById("committee-topic-readout"),
    committeeEmpty: document.getElementById("committee-empty"),
    committeeTimeline: document.getElementById("committee-timeline"),
    committeeClaims: document.getElementById("committee-claims"),
    committeeMinutes: document.getElementById("committee-minutes"),
    committeeCommandForm: document.getElementById("committee-command-form"),
    committeeCommandRole: document.getElementById("committee-command-role"),
    committeeCommandPrompt: document.getElementById("committee-command-prompt"),
    committeeCommandSubmit: document.getElementById("committee-command-submit"),
    decisionRecommendation: document.getElementById("game-decision-recommendation"),
    decisionSummary: document.getElementById("game-decision-summary"),
    decisionConfidence: document.getElementById("game-decision-confidence"),
    decisionPoints: document.getElementById("game-decision-points"),
    decisionRisks: document.getElementById("game-decision-risks"),
    reviewReason: document.getElementById("game-review-reason"),
    decisionArchiveFeedback: document.getElementById("decision-archive-feedback"),
    decisionArchiveRefresh: document.getElementById("decision-archive-refresh"),
    decisionArchiveEmpty: document.getElementById("decision-archive-empty"),
    decisionArchiveList: document.getElementById("decision-archive-list"),
  });

  const reducedMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const keys = new Set();
  const mobileDirections = new Set();
  const player = loadPlayer();
  const game = {
    running: true,
    reducedMotion: reducedMotionQuery.matches,
    lastFrame: 0,
    currentZone: "로비",
    nearestInteraction: null,
    provider: { name: "확인 중", status: "loading", detail: "" },
    run: null,
    currentRunId: null,
    eventSource: null,
    pollTimer: null,
    refreshTimer: null,
    panelRefreshTimer: null,
    committeePollTimer: null,
    discoveryPollTimer: null,
    activeAgentRole: null,
    tasks: [],
    tasksAvailable: null,
    schedules: [],
    schedulesAvailable: null,
    discovery: null,
    discoveryAvailable: null,
    discoveryRuns: [],
    committee: null,
    committeeId: null,
    committeeAvailable: null,
    decisions: [],
    decisionsAvailable: null,
    error: null,
  };
  const camera = {
    x: 0,
    y: 0,
    width: WORLD.width,
    height: WORLD.height,
    screenWidth: WORLD.width,
    screenHeight: WORLD.height,
    ratio: 1,
  };

  function loadPlayer() {
    const fallback = { x: 480, y: 770, direction: "up" };
    try {
      const saved = JSON.parse(window.localStorage.getItem("pixel-office-player") || "null");
      if (
        saved &&
        Number.isFinite(saved.x) &&
        Number.isFinite(saved.y) &&
        saved.x >= 30 &&
        saved.x <= WORLD.width - 30 &&
        saved.y >= 70 &&
        saved.y <= WORLD.height - 30
      ) {
        return { x: saved.x, y: saved.y, direction: saved.direction || "up", step: 0 };
      }
    } catch {
      // 손상된 위치 데이터는 로비 기본 위치로 대체한다.
    }
    return { ...fallback, step: 0 };
  }

  function savePlayer() {
    try {
      window.localStorage.setItem(
        "pixel-office-player",
        JSON.stringify({ x: Math.round(player.x), y: Math.round(player.y), direction: player.direction }),
      );
    } catch {
      // 저장소를 사용할 수 없어도 게임 실행은 계속한다.
    }
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
    return String(run?.run_id || run?.id || "");
  }

  function discoveryRunStatus(run) {
    const decision = String(
      run?.human_review?.decision || run?.review?.decision || run?.review_decision || "",
    ).toLowerCase();
    if (["approve", "approved", "accepted"].includes(decision)) return "approved";
    if (["reject", "rejected", "declined"].includes(decision)) return "rejected";
    if (["hold", "held", "defer", "deferred", "changes_requested"].includes(decision)) return "hold";
    const status = String(run?.status || "queued").toLowerCase();
    if (status === "completed") return "complete";
    if (["cancelled", "canceled", "error"].includes(status)) return "failed";
    return status;
  }

  function mergeDiscoveryRuns(preferredRuns, fallbackRuns = []) {
    const fallbacks = new Map(
      (Array.isArray(fallbackRuns) ? fallbackRuns : [])
        .map((run) => [discoveryRunId(run), run])
        .filter(([runId]) => runId),
    );
    const merged = [];
    const seen = new Set();
    for (const run of Array.isArray(preferredRuns) ? preferredRuns : []) {
      const runId = discoveryRunId(run);
      if (!runId || seen.has(runId)) continue;
      merged.push({ ...(fallbacks.get(runId) || {}), ...(run || {}), run_id: runId });
      seen.add(runId);
    }
    for (const run of Array.isArray(fallbackRuns) ? fallbackRuns : []) {
      const runId = discoveryRunId(run);
      if (!runId || seen.has(runId)) continue;
      merged.push({ ...(run || {}), run_id: runId });
      seen.add(runId);
    }
    return merged.slice(0, 12);
  }

  function saveDiscoveryRuns(runs) {
    const merged = mergeDiscoveryRuns(runs, loadStoredDiscoveryRuns());
    try {
      const compact = merged.map((run) => ({
        run_id: discoveryRunId(run),
        ticker: String(run?.ticker || run?.symbol || "").toUpperCase(),
        status: discoveryRunStatus(run),
        discovery_batch_id: String(run?.discovery_batch_id || ""),
      })).filter((run) => run.run_id);
      const serialized = JSON.stringify(compact);
      if (window.localStorage.getItem(DISCOVERY_RUNS_STORAGE_KEY) !== serialized) {
        window.localStorage.setItem(DISCOVERY_RUNS_STORAGE_KEY, serialized);
      }
    } catch {
      // 브라우저 저장소를 사용할 수 없어도 현재 화면의 폴링은 계속한다.
    }
    return merged;
  }

  function setText(element, value, fallback = "—") {
    if (element) element.textContent = value === null || value === undefined || value === "" ? fallback : String(value);
  }

  function announce(message, isError = false) {
    setText(elements.status, message, "");
    if (isError) game.error = message;
  }

  function setFeedback(element, message, tone = "neutral") {
    if (!element) return;
    setText(element, message, "");
    element.classList.toggle("is-error", tone === "error");
    element.classList.toggle("is-success", tone === "success");
  }

  function setFormDisabled(form, disabled) {
    form?.querySelectorAll("input, textarea, select, button").forEach((control) => {
      control.disabled = disabled;
    });
  }

  class ApiRequestError extends Error {
    constructor(message, status = 0, payload = null) {
      super(message);
      this.name = "ApiRequestError";
      this.status = status;
      this.payload = payload;
    }
  }

  function normalizeStatus(value) {
    const raw = String(value || "idle").toLowerCase();
    if (["completed", "complete", "done", "approved", "review", "hold", "rejected"].includes(raw)) return "done";
    if (["running", "analyzing", "working", "started"].includes(raw)) return "running";
    if (["failed", "error", "cancelled", "canceled"].includes(raw)) return "failed";
    if (["queued", "pending"].includes(raw)) return "queued";
    return "idle";
  }

  function runStatusLabel(status) {
    const raw = String(status || "idle").toLowerCase();
    return {
      queued: "대기열",
      running: "분석 중",
      review: "사람 검토",
      approved: "승인 완료",
      rejected: "기각 완료",
      hold: "보류",
      failed: "분석 실패",
    }[raw] || "대기";
  }

  function agentForRole(role) {
    return (game.run?.agents || []).find((agent) => String(agent.role) === role) || null;
  }

  function agentStatus(role) {
    return normalizeStatus(agentForRole(role)?.status);
  }

  function roomAt(x, y) {
    const room = ROOMS.find((item) => x >= item.x && x <= item.x + item.width && y >= item.y && y <= item.y + item.height);
    if (room) return room.label;
    if (x >= INTAKE.x && x <= INTAKE.x + INTAKE.width && y >= INTAKE.y && y <= INTAKE.y + INTAKE.height) {
      return INTAKE.label;
    }
    if (y > 650) return "메인 로비";
    return "중앙 복도";
  }

  function interactionTargets() {
    return [
      { id: "intake", kind: "intake", label: "분석 의뢰서 작성", x: INTAKE.desk.x, y: INTAKE.desk.y },
      ...ROOMS.map((room) => ({
        id: room.id,
        kind: room.committee ? "committee" : "agent",
        label: room.committee ? "위원회 초안 검토" : `${room.label} 보고서 확인`,
        role: room.role,
        x: room.npc.x,
        y: room.npc.y,
      })),
    ];
  }

  function nearestTarget() {
    let nearest = null;
    let bestDistance = Infinity;
    for (const target of interactionTargets()) {
      const distance = Math.hypot(player.x - target.x, player.y - target.y);
      if (distance < bestDistance) {
        nearest = target;
        bestDistance = distance;
      }
    }
    return bestDistance <= INTERACTION_DISTANCE ? { ...nearest, distance: bestDistance } : null;
  }

  function collides(x, y) {
    if (x < 34 || y < 88 || x > WORLD.width - 34 || y > WORLD.height - 34) return true;
    return FURNITURE.some(
      (rect) =>
        x + PLAYER_RADIUS > rect.x &&
        x - PLAYER_RADIUS < rect.x + rect.width &&
        y + PLAYER_RADIUS > rect.y &&
        y - PLAYER_RADIUS < rect.y + rect.height,
    );
  }

  function movementVector() {
    const left = keys.has("arrowleft") || keys.has("a") || mobileDirections.has("left");
    const right = keys.has("arrowright") || keys.has("d") || mobileDirections.has("right");
    const up = keys.has("arrowup") || keys.has("w") || mobileDirections.has("up");
    const down = keys.has("arrowdown") || keys.has("s") || mobileDirections.has("down");
    let x = Number(right) - Number(left);
    let y = Number(down) - Number(up);
    if (x && y) {
      x *= Math.SQRT1_2;
      y *= Math.SQRT1_2;
    }
    return { x, y };
  }

  function nudgePlayer(control, distance = 16) {
    if (elements.dialog?.open) return;
    const vectors = {
      arrowleft: { x: -1, y: 0, direction: "left" },
      a: { x: -1, y: 0, direction: "left" },
      left: { x: -1, y: 0, direction: "left" },
      arrowright: { x: 1, y: 0, direction: "right" },
      d: { x: 1, y: 0, direction: "right" },
      right: { x: 1, y: 0, direction: "right" },
      arrowup: { x: 0, y: -1, direction: "up" },
      w: { x: 0, y: -1, direction: "up" },
      up: { x: 0, y: -1, direction: "up" },
      arrowdown: { x: 0, y: 1, direction: "down" },
      s: { x: 0, y: 1, direction: "down" },
      down: { x: 0, y: 1, direction: "down" },
    };
    const movement = vectors[control];
    if (!movement) return;
    const nextX = player.x + movement.x * distance;
    const nextY = player.y + movement.y * distance;
    if (!collides(nextX, player.y)) player.x = nextX;
    if (!collides(player.x, nextY)) player.y = nextY;
    player.direction = movement.direction;
    player.step += distance;
    updateWorld();
  }

  function updatePlayer(deltaSeconds) {
    if (elements.dialog?.open) return;
    const movement = movementVector();
    if (!movement.x && !movement.y) return;
    const speed = PLAYER_SPEED * deltaSeconds;
    const nextX = player.x + movement.x * speed;
    const nextY = player.y + movement.y * speed;
    if (!collides(nextX, player.y)) player.x = nextX;
    if (!collides(player.x, nextY)) player.y = nextY;
    if (Math.abs(movement.x) > Math.abs(movement.y)) player.direction = movement.x > 0 ? "right" : "left";
    else player.direction = movement.y > 0 ? "down" : "up";
    player.step += speed;
  }

  function updateWorld() {
    const zone = roomAt(player.x, player.y);
    if (zone !== game.currentZone) {
      game.currentZone = zone;
      setText(elements.zone, zone);
      announce(`${zone}에 들어왔습니다.`);
    }
    game.nearestInteraction = nearestTarget();
    setText(
      elements.prompt,
      game.nearestInteraction
        ? `E 또는 확인 버튼으로 ${game.nearestInteraction.label}`
        : "WASD 또는 방향키로 에이전트와 접수 데스크를 찾아가세요.",
    );
  }

  function setupCanvas() {
    const rect = canvas.getBoundingClientRect();
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    camera.screenWidth = Math.max(1, rect.width);
    camera.screenHeight = Math.max(1, rect.height);
    camera.ratio = ratio;
    canvas.width = Math.round(camera.screenWidth * ratio);
    canvas.height = Math.round(camera.screenHeight * ratio);
    context.imageSmoothingEnabled = false;
  }

  function updateCamera() {
    const aspect = camera.screenWidth / camera.screenHeight;
    if (aspect >= 1) {
      camera.height = Math.min(700, WORLD.height);
      camera.width = camera.height * aspect;
      if (camera.width > WORLD.width) {
        camera.width = WORLD.width;
        camera.height = camera.width / aspect;
      }
    } else {
      camera.height = Math.min(620, WORLD.height);
      camera.width = camera.height * aspect;
    }
    camera.width = Math.min(camera.width, WORLD.width);
    camera.height = Math.min(camera.height, WORLD.height);
    camera.x = Math.max(0, Math.min(WORLD.width - camera.width, player.x - camera.width / 2));
    camera.y = Math.max(0, Math.min(WORLD.height - camera.height, player.y - camera.height / 2));
  }

  function prepareContext() {
    updateCamera();
    context.setTransform(1, 0, 0, 1, 0, 0);
    context.fillStyle = "#050806";
    context.fillRect(0, 0, canvas.width, canvas.height);
    const scale = camera.screenWidth / camera.width;
    const pixelScale = camera.ratio * scale;
    context.setTransform(
      pixelScale,
      0,
      0,
      pixelScale,
      -camera.x * pixelScale,
      -camera.y * pixelScale,
    );
    context.imageSmoothingEnabled = false;
  }

  function fillRect(x, y, width, height, color) {
    context.fillStyle = color;
    context.fillRect(Math.round(x), Math.round(y), Math.round(width), Math.round(height));
  }

  function strokeRect(x, y, width, height, color, lineWidth = 2) {
    context.strokeStyle = color;
    context.lineWidth = lineWidth;
    context.strokeRect(Math.round(x), Math.round(y), Math.round(width), Math.round(height));
  }

  function drawBackground() {
    fillRect(0, 0, WORLD.width, WORLD.height, "#090e12");
    for (let y = 90; y < WORLD.height; y += WORLD.tile) {
      for (let x = 0; x < WORLD.width; x += WORLD.tile) {
        const alternating = (x / WORLD.tile + y / WORLD.tile) % 2 === 0;
        fillRect(x, y, WORLD.tile, WORLD.tile, alternating ? "#121b20" : "#152127");
        if ((x / WORLD.tile + y / WORLD.tile) % 4 === 0) {
          fillRect(x + 4, y + 4, WORLD.tile - 8, 2, "rgba(98, 132, 142, 0.12)");
        }
      }
    }
    context.strokeStyle = "rgba(119, 160, 169, 0.1)";
    context.lineWidth = 1;
    for (let x = 0; x <= WORLD.width; x += WORLD.tile) {
      context.beginPath();
      context.moveTo(x, 90);
      context.lineTo(x, WORLD.height);
      context.stroke();
    }
    for (let y = 90; y <= WORLD.height; y += WORLD.tile) {
      context.beginPath();
      context.moveTo(0, y);
      context.lineTo(WORLD.width, y);
      context.stroke();
    }
    fillRect(0, 0, WORLD.width, 88, "#081016");
    fillRect(0, 84, WORLD.width, 4, "#f4b83d");
  }

  function drawRoomFloor(room) {
    const inset = 7;
    const top = room.y + 34;
    const bottom = room.y + room.height - inset;
    const plankHeight = 18;
    const base = room.committee ? "#313a3e" : "#29382f";
    const alternate = room.committee ? "#354147" : "#2d3d33";
    fillRect(room.x + inset, top, room.width - inset * 2, bottom - top, base);
    for (let y = top; y < bottom; y += plankHeight) {
      const row = Math.floor((y - top) / plankHeight);
      for (let x = room.x + inset - (row % 2 ? 34 : 0); x < room.x + room.width - inset; x += 68) {
        fillRect(x, y, 66, plankHeight - 2, row % 2 ? alternate : base);
        fillRect(x + 5, y + 4, 24, 2, "rgba(205, 220, 207, 0.055)");
      }
    }
  }

  function drawPixelPlant(x, y) {
    fillRect(x - 9, y + 4, 18, 17, "#7a4f31");
    fillRect(x - 12, y, 24, 6, "#9c6841");
    fillRect(x - 3, y - 20, 6, 22, "#366c47");
    fillRect(x - 15, y - 25, 13, 12, "#4f9b61");
    fillRect(x + 2, y - 31, 14, 13, "#62b271");
    fillRect(x - 8, y - 38, 14, 14, "#3f8755");
  }

  function drawShelf(x, y, color) {
    fillRect(x, y, 52, 80, "#1b241f");
    strokeRect(x, y, 52, 80, "#56655b", 2);
    for (let shelf = 0; shelf < 3; shelf += 1) {
      fillRect(x + 5, y + 9 + shelf * 23, 42, 3, "#5b4730");
      for (let book = 0; book < 5; book += 1) {
        const height = 9 + ((book + shelf) % 3) * 3;
        fillRect(x + 7 + book * 8, y + 9 + shelf * 23 - height, 5, height, book % 2 ? color : "#8c6f50");
      }
    }
  }

  function drawRoom(room) {
    fillRect(room.x + 7, room.y + 9, room.width, room.height, "rgba(0, 0, 0, 0.34)");
    fillRect(room.x, room.y, room.width, room.height, "#18221c");
    drawRoomFloor(room);
    strokeRect(room.x, room.y, room.width, room.height, "#090d0a", 11);
    strokeRect(room.x + 5, room.y + 5, room.width - 10, room.height - 10, room.color, 2);
    fillRect(room.x + 6, room.y + 6, room.width - 12, 29, "rgba(4, 8, 6, 0.9)");
    fillRect(room.x + 10, room.y + 35, room.width - 20, 5, room.color);
    fillRect(room.x + 18, room.y + 44, 90, 22, "#101712");
    strokeRect(room.x + 18, room.y + 44, 90, 22, "#4d5e53", 1);
    context.fillStyle = room.color;
    context.font = "700 13px monospace";
    context.fillText(room.code, room.x + 14, room.y + 25);
    context.fillStyle = "#eae7d9";
    context.font = "900 17px sans-serif";
    context.fillText(room.label, room.x + 25, room.y + 61);

    drawDesk(room.desk.x, room.desk.y, room.color, room.committee);
    drawPixelPlant(room.x + 34, room.y + room.height - 42);
    if (room.committee) {
      drawConferenceTable(room.x + 105, room.y + 215, room.color);
      drawShelf(room.x + room.width - 72, room.y + 88, room.color);
    } else {
      drawWhiteboard(room.x + room.width - 82, room.y + 62, room.color);
      drawShelf(room.x + room.width - 66, room.y + room.height - 92, room.color);
    }
  }

  function drawDesk(x, y, color, committee = false) {
    const width = committee ? 150 : 116;
    fillRect(x - width / 2, y - 20, width, 42, "#263129");
    fillRect(x - width / 2, y + 17, width, 8, "#111713");
    fillRect(x - width / 2 + 8, y + 25, 9, 23, "#38453b");
    fillRect(x + width / 2 - 17, y + 25, 9, 23, "#38453b");
    fillRect(x - 22, y - 51, 44, 31, "#050806");
    strokeRect(x - 22, y - 51, 44, 31, color, 3);
    fillRect(x - 5, y - 38, 10, 4, color);
    fillRect(x - 2, y - 20, 4, 13, "#59645c");
    fillRect(x - 31, y - 15, 17, 9, "#9a7650");
    fillRect(x + 18, y - 13, 14, 6, "#d7d2bf");
    fillRect(x - 16, y + 49, 32, 14, "#1b2420");
    fillRect(x - 13, y + 45, 26, 6, "#4c5a50");
  }

  function drawConferenceTable(x, y, color) {
    fillRect(x, y, 190, 52, "#2b352e");
    strokeRect(x, y, 190, 52, color, 2);
    for (let index = 0; index < 5; index += 1) {
      fillRect(x + 14 + index * 36, y - 17, 22, 13, "#465148");
      fillRect(x + 14 + index * 36, y + 56, 22, 13, "#465148");
    }
  }

  function drawWhiteboard(x, y, color) {
    fillRect(x, y, 56, 74, "#d7dbcf");
    strokeRect(x, y, 56, 74, "#536058", 3);
    fillRect(x + 8, y + 14, 31, 4, color);
    fillRect(x + 8, y + 28, 41, 3, "#55635a");
    fillRect(x + 8, y + 40, 25, 3, "#55635a");
  }

  function drawIntake() {
    fillRect(INTAKE.x, INTAKE.y, INTAKE.width, INTAKE.height, "rgba(23, 24, 15, 0.95)");
    strokeRect(INTAKE.x, INTAKE.y, INTAKE.width, INTAKE.height, INTAKE.color, 4);
    context.fillStyle = INTAKE.color;
    context.font = "700 15px monospace";
    context.fillText(INTAKE.code, INTAKE.x + 14, INTAKE.y + 23);
    context.fillStyle = "#f3eedf";
    context.font = "900 25px sans-serif";
    context.fillText(INTAKE.label, INTAKE.x + 14, INTAKE.y + 58);
    drawDesk(INTAKE.desk.x, INTAKE.desk.y, INTAKE.color, true);
    fillRect(INTAKE.x + 18, INTAKE.y + 89, 64, 43, "#111713");
    strokeRect(INTAKE.x + 18, INTAKE.y + 89, 64, 43, INTAKE.color, 2);
    context.fillStyle = INTAKE.color;
    context.font = "900 18px monospace";
    context.fillText("RUN", INTAKE.x + 31, INTAKE.y + 117);
  }

  function drawLounge() {
    fillRect(990, 680, 405, 165, "rgba(12, 20, 15, 0.95)");
    strokeRect(990, 680, 405, 165, "#5f7465", 3);
    context.fillStyle = "#8ba092";
    context.font = "700 14px monospace";
    context.fillText("OPERATIONS LOUNGE // STATUS WALL", 1006, 705);
    fillRect(1030, 724, 300, 74, "#111a14");
    strokeRect(1030, 724, 300, 74, "#304b39", 2);
    const completed = (game.run?.agents || []).filter((agent) => normalizeStatus(agent.status) === "done").length;
    context.fillStyle = "#65e58a";
    context.font = "900 36px monospace";
    context.fillText(`${completed}/6`, 1050, 772);
    context.fillStyle = "#9eaa9f";
    context.font = "700 13px monospace";
    context.fillText("AGENT REPORTS", 1150, 760);
    context.fillText("NO AUTO EXECUTION", 1150, 781);
  }

  function drawNpc(room, time) {
    const status = agentStatus(room.role);
    const color = STATUS_COLORS[status];
    const motion = game.reducedMotion ? 0 : Math.sin(time / 300 + room.x) * (status === "running" ? 7 : 2);
    const x = room.npc.x + (status === "running" ? motion : 0);
    const y = room.npc.y + (status === "running" ? Math.abs(motion) * 0.35 : 0);
    const highlighted = game.nearestInteraction?.id === room.id;

    if (highlighted) {
      context.strokeStyle = room.color;
      context.lineWidth = 3;
      context.beginPath();
      context.arc(x, y, 36, 0, Math.PI * 2);
      context.stroke();
    }

    fillRect(x - 14, y - 32, 28, 24, "#d7a274");
    fillRect(x - 17, y - 10, 34, 34, room.color);
    fillRect(x - 21, y - 5, 5, 23, "#d7a274");
    fillRect(x + 16, y - 5, 5, 23, "#d7a274");
    fillRect(x - 14, y + 24, 10, 19, "#1b221d");
    fillRect(x + 4, y + 24, 10, 19, "#1b221d");
    fillRect(x - 16, y - 39, 32, 10, room.role === "bear" ? "#c7c1d6" : "#18231e");
    fillRect(x - 9, y - 25, 4, 4, "#161a17");
    fillRect(x + 5, y - 25, 4, 4, "#161a17");
    fillRect(x - 17, y - 52, 34, 8, color);
    strokeRect(x - 20, y - 42, 40, 70, "#080b09", 2);

    context.textAlign = "center";
    context.fillStyle = "#edf0e8";
    context.font = "800 13px sans-serif";
    context.fillText(ROLE_LABELS[room.role], x, y + 62);
    context.fillStyle = color;
    context.font = "700 11px monospace";
    context.fillText(STATUS_LABELS[status], x, y + 78);
    context.textAlign = "left";
  }

  function drawPlayer(time) {
    const walking = movementVector().x || movementVector().y;
    const step = game.reducedMotion || !walking ? 0 : Math.sin(time / 95) * 3;
    const x = player.x;
    const y = player.y;
    context.fillStyle = "rgba(0, 0, 0, 0.4)";
    context.beginPath();
    context.ellipse(x, y + 23, 22, 8, 0, 0, Math.PI * 2);
    context.fill();
    fillRect(x - 13, y - 32, 26, 22, "#e1a875");
    fillRect(x - 16, y - 10, 32, 34, "#f5bd3f");
    fillRect(x - 13, y + 24, 10, 18 + step, "#28322b");
    fillRect(x + 3, y + 24, 10, 18 - step, "#28322b");
    fillRect(x - 15, y - 39, 30, 9, "#1b241e");
    fillRect(x - 8, y - 27, 3, 3, "#121612");
    fillRect(x + 6, y - 27, 3, 3, "#121612");
    strokeRect(x - 18, y - 42, 36, 70, "#060806", 3);
    context.textAlign = "center";
    context.fillStyle = "#f8d66f";
    context.font = "900 12px monospace";
    context.fillText("YOU", x, y + 61);
    context.textAlign = "left";
  }

  function drawInteractionMarker(time) {
    const target = game.nearestInteraction;
    if (!target) return;
    const pulse = game.reducedMotion ? 0 : Math.sin(time / 180) * 4;
    const y = target.y - 70 - pulse;
    fillRect(target.x - 18, y - 16, 36, 28, "#f5bd3f");
    strokeRect(target.x - 18, y - 16, 36, 28, "#090b09", 3);
    context.fillStyle = "#080a08";
    context.textAlign = "center";
    context.font = "900 18px monospace";
    context.fillText("E", target.x, y + 5);
    context.textAlign = "left";
  }

  function draw(time) {
    prepareContext();
    drawBackground();
    for (const room of ROOMS) drawRoom(room);
    drawIntake();
    drawLounge();
    context.fillStyle = "rgba(5, 8, 6, 0.82)";
    context.fillRect(420, 706, 520, 135);
    strokeRect(420, 706, 520, 135, "#314238", 2);
    context.fillStyle = "#8fa397";
    context.font = "700 13px monospace";
    context.fillText("CENTRAL OPERATIONS CORRIDOR", 438, 734);
    context.fillStyle = "#dde5da";
    context.font = "900 20px sans-serif";
    context.fillText(game.run ? `${game.run.ticker || "—"} · ${runStatusLabel(game.run.status)}` : "새 분석을 기다리는 중", 438, 771);
    context.fillStyle = "#91a398";
    context.font = "600 14px sans-serif";
    context.fillText("각 에이전트를 찾아가 보고서를 확인하고 위원회실에서 직접 결정하세요.", 438, 804);
    for (const room of ROOMS) drawNpc(room, time);
    drawInteractionMarker(time);
    drawPlayer(time);
  }

  function frame(timestamp) {
    if (!game.running) return;
    const delta = Math.min((timestamp - game.lastFrame) / 1000 || 0, 0.05);
    game.lastFrame = timestamp;
    updatePlayer(delta);
    updateWorld();
    draw(timestamp);
    window.requestAnimationFrame(frame);
  }

  function showPanel(panel) {
    for (const candidate of [elements.intakePanel, elements.agentPanel, elements.committeePanel]) {
      if (candidate) candidate.hidden = candidate !== panel;
    }
  }

  function openDialog(panel, title) {
    showPanel(panel);
    setText(elements.dialogTitle, title);
    if (elements.dialog && !elements.dialog.open) elements.dialog.showModal();
  }

  function closeDialog() {
    if (elements.dialog?.open) elements.dialog.close();
    stopCommitteePolling();
    canvas.focus({ preventScroll: true });
  }

  function replaceList(element, items, fallback) {
    if (!element) return;
    element.replaceChildren();
    const values = Array.isArray(items) && items.length ? items.slice(0, 8) : [fallback];
    for (const value of values) {
      const item = document.createElement("li");
      item.textContent = typeof value === "string" ? value : String(value?.claim || value?.summary || value || fallback);
      element.append(item);
    }
  }

  function schedulesFromPayload(payload) {
    if (Array.isArray(payload)) return payload;
    const root = payload?.data || payload || {};
    if (Array.isArray(root)) return root;
    return root.schedules || root.items || root.results || root.jobs || [];
  }

  function scheduleIdentifier(schedule) {
    return String(schedule?.schedule_id || schedule?.id || schedule?.uuid || "");
  }

  function scheduleStatusLabel(status) {
    const raw = String(status || "scheduled").toLowerCase();
    return {
      scheduled: "예약됨",
      queued: "실행 대기",
      pending: "실행 대기",
      claimed: "실행 준비",
      dispatched: "분석 중",
      running: "분석 중",
      completed: "분석 완료",
      complete: "분석 완료",
      done: "분석 완료",
      failed: "실패",
      cancelled: "취소됨",
      canceled: "취소됨",
    }[raw] || raw;
  }

  function readableKstTime(value, fallback = "시각 미정") {
    if (!value) return fallback;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString("ko-KR", {
      timeZone: "Asia/Seoul",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }

  function kstDateTimeLocal(timestamp) {
    const shifted = new Date(timestamp + 9 * 60 * 60 * 1000);
    return shifted.toISOString().slice(0, 16);
  }

  function configureScheduleTime() {
    if (!elements.scheduleTime) return;
    const now = Date.now();
    const quarterHour = 15 * 60 * 1000;
    const defaultTime = Math.ceil((now + 60 * 60 * 1000) / quarterHour) * quarterHour;
    elements.scheduleTime.min = kstDateTimeLocal(now + 60 * 1000);
    if (!elements.scheduleTime.value) elements.scheduleTime.value = kstDateTimeLocal(defaultTime);
  }

  function scheduledForIso(value) {
    const raw = String(value || "").trim();
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?$/.test(raw)) return null;
    const iso = `${raw.length === 16 ? `${raw}:00` : raw}+09:00`;
    const parsed = new Date(iso);
    if (Number.isNaN(parsed.getTime()) || parsed.getTime() <= Date.now()) return null;
    return iso;
  }

  function renderSchedules(schedules) {
    const values = Array.isArray(schedules) ? schedules : [];
    game.schedules = values;
    elements.scheduleList?.replaceChildren();
    if (elements.scheduleEmpty) elements.scheduleEmpty.hidden = values.length > 0;
    if (!values.length || !elements.scheduleList) return;

    for (const schedule of values) {
      const id = scheduleIdentifier(schedule);
      const status = String(schedule.status || "scheduled").toLowerCase();
      const scheduledFor = schedule.scheduled_for || schedule.run_at || schedule.execute_at || schedule.schedule_time;
      const item = document.createElement("li");
      item.className = "schedule-card";
      item.dataset.status = status;

      const heading = document.createElement("div");
      heading.className = "schedule-card__heading";
      const ticker = document.createElement("strong");
      ticker.textContent = String(schedule.ticker || schedule.symbol || "종목 미정").toUpperCase();
      const badge = document.createElement("span");
      badge.className = "schedule-card__status";
      badge.textContent = scheduleStatusLabel(status);
      heading.append(ticker, badge);

      const time = document.createElement("time");
      time.className = "schedule-card__time";
      if (scheduledFor) time.dateTime = String(scheduledFor);
      time.textContent = `${readableKstTime(scheduledFor)} KST`;

      const thesis = document.createElement("p");
      const scheduleError = String(schedule.error || "").trim();
      thesis.textContent = scheduleError
        ? `실패 원인 · ${scheduleError}`
        : String(schedule.thesis || schedule.hypothesis || "등록된 투자 가설이 없습니다.");
      thesis.classList.toggle("is-error", Boolean(scheduleError));

      const footer = document.createElement("div");
      footer.className = "schedule-card__footer";
      const meta = document.createElement("small");
      const runId = String(schedule.run_id || schedule.analysis_run_id || "");
      meta.textContent = `${id ? `ID ${id.slice(-8)}` : "ID 확인 중"}${runId ? ` · RUN ${runId.slice(-8)}` : ""}`;
      footer.append(meta);
      if (["scheduled", "queued", "pending"].includes(status) && id) {
        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.className = "danger-action";
        cancel.dataset.scheduleAction = "cancel";
        cancel.dataset.scheduleId = id;
        cancel.dataset.scheduleTicker = ticker.textContent;
        cancel.textContent = "예약 취소";
        footer.append(cancel);
      }

      item.append(heading, time, thesis, footer);
      elements.scheduleList.append(item);
    }
  }

  async function loadSchedules({ silent = false } = {}) {
    if (!silent) setFeedback(elements.scheduleFeedback, "예약 작업을 불러오는 중입니다.");
    try {
      const result = await requestFeatureJson(API.schedules, {}, 15_000);
      if (!result.available) {
        game.schedulesAvailable = false;
        renderSchedules([]);
        setFeedback(elements.scheduleFeedback, "예약 작업 API가 아직 준비되지 않았습니다.", "error");
        if (elements.scheduleEmpty) {
          setText(elements.scheduleEmpty.querySelector("strong"), "예약 기능을 연결할 수 없습니다.");
          setText(elements.scheduleEmpty.querySelector("p"), "즉시 분석은 계속 사용할 수 있습니다.");
        }
        setFormDisabled(elements.scheduleForm, true);
        return;
      }
      game.schedulesAvailable = true;
      const schedules = schedulesFromPayload(result.payload);
      if (elements.scheduleEmpty) {
        setText(elements.scheduleEmpty.querySelector("strong"), "등록된 예약 분석이 없습니다.");
        setText(elements.scheduleEmpty.querySelector("p"), "미래 KST 시각을 지정하면 이곳에서 예약 상태를 확인할 수 있습니다.");
      }
      renderSchedules(schedules);
      setFeedback(
        elements.scheduleFeedback,
        schedules.length
          ? `${schedules.length}건의 일회성 분석 예약을 확인했습니다. 자동 주문은 실행되지 않습니다.`
          : "등록된 예약이 없습니다. 예약 시각에는 분석만 시작됩니다.",
      );
      setFormDisabled(elements.scheduleForm, false);
      configureScheduleTime();
    } catch (error) {
      renderSchedules([]);
      if (elements.scheduleEmpty) {
        setText(elements.scheduleEmpty.querySelector("strong"), "예약 목록을 불러오지 못했습니다.");
        setText(elements.scheduleEmpty.querySelector("p"), "연결 상태를 확인한 뒤 새로고침하세요.");
      }
      setFeedback(elements.scheduleFeedback, `예약 작업을 불러오지 못했습니다. ${error.message}`, "error");
    }
  }

  async function submitSchedule(event) {
    event.preventDefault();
    const ticker = String(elements.scheduleTicker?.value || "").trim().toUpperCase();
    if (elements.scheduleTicker) elements.scheduleTicker.value = ticker;
    const tickerValid = /^[A-Z0-9][A-Z0-9.\-]{0,14}$/.test(ticker);
    const scheduledFor = scheduledForIso(elements.scheduleTime?.value);
    if (!tickerValid || !scheduledFor) {
      elements.scheduleTicker?.setAttribute("aria-invalid", String(!tickerValid));
      elements.scheduleTime?.setAttribute("aria-invalid", String(!scheduledFor));
      setText(
        elements.scheduleError,
        !tickerValid
          ? "영문·숫자·점·하이픈으로 종목 코드를 입력하세요."
          : "현재보다 미래인 KST 실행 시각을 입력하세요.",
        "",
      );
      (!tickerValid ? elements.scheduleTicker : elements.scheduleTime)?.focus();
      return;
    }
    elements.scheduleTicker?.setAttribute("aria-invalid", "false");
    elements.scheduleTime?.setAttribute("aria-invalid", "false");
    setText(elements.scheduleError, "", "");
    setFormDisabled(elements.scheduleForm, true);
    setFeedback(elements.scheduleFeedback, `${ticker} 일회성 분석 예약을 등록하는 중입니다.`);
    try {
      const thesis = String(elements.scheduleThesis?.value || "").trim();
      const result = await requestFeatureJson(API.schedules, {
        method: "POST",
        body: JSON.stringify({ ticker, thesis, scheduled_for: scheduledFor }),
      }, 20_000);
      if (!result.available) {
        game.schedulesAvailable = false;
        setFeedback(elements.scheduleFeedback, "예약 등록 API가 아직 준비되지 않았습니다.", "error");
        return;
      }
      if (elements.scheduleTicker) elements.scheduleTicker.value = "";
      if (elements.scheduleThesis) elements.scheduleThesis.value = "";
      if (elements.scheduleTime) elements.scheduleTime.value = "";
      configureScheduleTime();
      setFeedback(elements.scheduleFeedback, `${ticker} 분석 예약을 기록했습니다. 매매 주문은 생성하지 않습니다.`, "success");
      announce(`${ticker} 분석 예약이 등록됐습니다. KST 실행 시각에 분석팀만 호출됩니다.`);
      await loadSchedules({ silent: true });
    } catch (error) {
      setFeedback(elements.scheduleFeedback, `예약 등록 실패. ${error.message}`, "error");
    } finally {
      setFormDisabled(elements.scheduleForm, game.schedulesAvailable === false);
    }
  }

  async function handleScheduleAction(event) {
    const button = event.target.closest("[data-schedule-action]");
    if (!(button instanceof HTMLButtonElement) || button.dataset.scheduleAction !== "cancel") return;
    const scheduleId = String(button.dataset.scheduleId || "");
    const ticker = String(button.dataset.scheduleTicker || "해당 종목");
    if (!scheduleId || !window.confirm(`${ticker}의 예약 분석을 취소할까요?`)) return;
    button.disabled = true;
    setFeedback(elements.scheduleFeedback, `${ticker} 예약을 취소하는 중입니다.`);
    try {
      const result = await requestFeatureJson(API.cancelSchedule(scheduleId), {
        method: "POST",
        body: "{}",
      }, 15_000);
      if (!result.available) {
        setFeedback(elements.scheduleFeedback, "예약 취소 API가 아직 준비되지 않았습니다.", "error");
        return;
      }
      setFeedback(elements.scheduleFeedback, `${ticker} 예약을 취소했습니다.`, "success");
      announce(`${ticker} 예약 분석을 취소했습니다.`);
      await loadSchedules({ silent: true });
    } catch (error) {
      setFeedback(elements.scheduleFeedback, `예약 취소 실패. ${error.message}`, "error");
      button.disabled = false;
    }
  }

  function discoveryFromPayload(payload) {
    if (!payload) return null;
    const root = payload.data || payload;
    return root.discovery || root.screening || root.result || (root.candidates ? root : null);
  }

  function discoveryRunsFromPayload(payload) {
    if (Array.isArray(payload)) return payload;
    const root = payload?.data || payload || {};
    return root.runs || root.analyses || root.results || [];
  }

  function discoveryStrategyLabel(strategy) {
    return {
      balanced: "균형형",
      momentum: "모멘텀형",
      defensive: "방어형",
    }[String(strategy || "balanced").toLowerCase()] || String(strategy || "균형형");
  }

  function candidateTicker(candidate) {
    return String(candidate?.ticker || candidate?.symbol || "").trim().toUpperCase();
  }

  function candidateScore(value) {
    const score = Number(value);
    if (!Number.isFinite(score)) return "—";
    return Number.isInteger(score) ? String(score) : score.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  }

  function discoveryVerdictLabel(value) {
    return {
      review_first: "우선 검토",
      watch: "관찰 후보",
      exclude: "제외",
    }[String(value || "").toLowerCase()] || String(value || "후보");
  }

  function safeSourceUrl(value) {
    try {
      const url = new URL(String(value || ""), window.location.href);
      return ["http:", "https:"].includes(url.protocol) ? url.href : null;
    } catch {
      return null;
    }
  }

  function appendDiscoveryList(container, title, values, risk = false) {
    const group = document.createElement("div");
    group.className = `discovery-candidate__list${risk ? " is-risk" : ""}`;
    const heading = document.createElement("strong");
    heading.textContent = title;
    const list = document.createElement("ul");
    const items = Array.isArray(values) && values.length ? values.slice(0, 4) : ["등록된 내용이 없습니다."];
    for (const value of items) {
      const item = document.createElement("li");
      item.textContent = typeof value === "string"
        ? value
        : String(value?.reason || value?.summary || value?.message || value || "등록된 내용이 없습니다.");
      list.append(item);
    }
    group.append(heading, list);
    container.append(group);
  }

  function selectedDiscoveryTickers() {
    return Array.from(
      elements.discoveryCandidateList?.querySelectorAll('input[name="discovery-ticker"]:checked') || [],
      (input) => input.value,
    ).slice(0, 3);
  }

  function updateDiscoverySelection(changedInput = null) {
    let selected = selectedDiscoveryTickers();
    if (changedInput?.checked && selected.length >= 3) {
      const checked = Array.from(
        elements.discoveryCandidateList?.querySelectorAll('input[name="discovery-ticker"]:checked') || [],
      );
      if (checked.length > 3) {
        changedInput.checked = false;
        setFeedback(elements.discoveryFeedback, "심층 분석 후보는 최대 3개까지 선택할 수 있습니다.", "error");
        selected = selectedDiscoveryTickers();
      }
    }
    setText(elements.discoverySelectionCount, `${selected.length} / 3 SELECTED`);
    if (elements.discoveryAnalyzeSubmit) {
      elements.discoveryAnalyzeSubmit.disabled = selected.length === 0 || game.discoveryAvailable === false;
    }
  }

  function renderDiscoveryExcluded(excluded) {
    const values = Array.isArray(excluded) ? excluded : [];
    elements.discoveryExcludedList?.replaceChildren();
    if (elements.discoveryExcluded) elements.discoveryExcluded.hidden = values.length === 0;
    if (!values.length || !elements.discoveryExcludedList) return;
    for (const excludedItem of values.slice(0, 20)) {
      const item = document.createElement("li");
      const reasons = Array.isArray(excludedItem?.reasons)
        ? excludedItem.reasons.filter(Boolean).join(" · ")
        : excludedItem?.reason;
      item.textContent = typeof excludedItem === "string"
        ? excludedItem
        : `${candidateTicker(excludedItem) || "종목 미정"} · ${reasons || excludedItem.verdict || "선별 기준 미충족"}`;
      elements.discoveryExcludedList.append(item);
    }
  }

  function renderDiscoveryCandidates(candidates) {
    const values = Array.isArray(candidates) ? candidates.slice(0, 8) : [];
    elements.discoveryCandidateList?.replaceChildren();
    if (elements.discoveryEmpty) elements.discoveryEmpty.hidden = values.length > 0;
    if (!values.length || !elements.discoveryCandidateList) {
      updateDiscoverySelection();
      return;
    }

    values.forEach((candidate, index) => {
      const tickerValue = candidateTicker(candidate);
      const item = document.createElement("li");
      item.className = "discovery-candidate";

      const select = document.createElement("label");
      select.className = "discovery-candidate__select";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.name = "discovery-ticker";
      checkbox.value = tickerValue;
      checkbox.checked = index < 3 && Boolean(tickerValue);
      checkbox.disabled = !tickerValue;
      const identity = document.createElement("span");
      identity.className = "discovery-candidate__identity";
      const rank = document.createElement("small");
      rank.textContent = `RANK ${candidate.rank ?? index + 1}`;
      const ticker = document.createElement("strong");
      ticker.textContent = tickerValue || "종목 미정";
      identity.append(rank, ticker);
      select.append(checkbox, identity);

      const telemetry = document.createElement("div");
      telemetry.className = "discovery-candidate__telemetry";
      const score = document.createElement("span");
      const scoreLabel = document.createElement("small");
      scoreLabel.textContent = "SCORE";
      score.append(scoreLabel, document.createTextNode(candidateScore(candidate.score)));
      const verdict = document.createElement("span");
      const verdictLabel = document.createElement("small");
      verdictLabel.textContent = "VERDICT";
      verdict.append(verdictLabel, document.createTextNode(discoveryVerdictLabel(candidate.verdict)));
      telemetry.append(score, verdict);

      const evidence = document.createElement("div");
      evidence.className = "discovery-candidate__evidence";
      appendDiscoveryList(evidence, "선별 근거", candidate.reasons || candidate.key_points);
      appendDiscoveryList(evidence, "위험 신호", candidate.risks, true);

      const sourceUrl = safeSourceUrl(candidate.source_url || candidate.source);
      item.append(select, telemetry, evidence);
      if (sourceUrl) {
        const source = document.createElement("a");
        source.className = "discovery-candidate__source";
        source.href = sourceUrl;
        source.target = "_blank";
        source.rel = "noreferrer";
        source.textContent = "가격 데이터 출처 확인 ↗";
        item.append(source);
      }
      elements.discoveryCandidateList.append(item);
    });
    updateDiscoverySelection();
  }

  function renderDiscovery(discovery) {
    game.discovery = discovery;
    const candidates = Array.isArray(discovery?.candidates) ? discovery.candidates : [];
    if (elements.discoverySummary) elements.discoverySummary.hidden = !discovery;
    setText(elements.discoverySummaryStrategy, discoveryStrategyLabel(discovery?.strategy));
    setText(elements.discoverySummaryUniverse, discovery?.universe_size, "—");
    setText(elements.discoverySummaryCount, candidates.length, "0");
    const omittedCount = Number(discovery?.omitted_count || 0);
    const baseNotice = discovery?.disclaimer
      || discovery?.safety_notice
      || (discovery ? "가격 기반 1차 후보이며 매수 또는 수익을 보장하지 않습니다." : "");
    setText(
      elements.discoveryDisclaimer,
      omittedCount > 0
        ? `${baseNotice} 기준을 통과했지만 표시 한도 밖인 종목이 ${omittedCount}개 더 있습니다.`
        : baseNotice,
      "",
    );
    renderDiscoveryExcluded(discovery?.excluded);
    renderDiscoveryCandidates(candidates);
  }

  function renderDiscoveryRuns(runs, { persist = true } = {}) {
    const incoming = Array.isArray(runs) ? runs : [];
    const values = persist ? saveDiscoveryRuns(incoming) : incoming.slice(0, 12);
    game.discoveryRuns = values;
    elements.discoveryRunList?.replaceChildren();
    if (elements.discoveryRunsEmpty) elements.discoveryRunsEmpty.hidden = values.length > 0;
    if (!values.length || !elements.discoveryRunList) return;
    for (const run of values) {
      const runStatus = discoveryRunStatus(run);
      const item = document.createElement("li");
      item.className = "discovery-run-card";
      item.dataset.status = runStatus;
      const ticker = document.createElement("strong");
      ticker.textContent = String(run.ticker || run.symbol || "종목 미정").toUpperCase();
      const status = document.createElement("span");
      status.textContent = runStatusLabel(runStatus);
      const id = document.createElement("small");
      const runId = String(run.run_id || run.id || "");
      id.textContent = runId ? `RUN ${runId}` : "RUN ID 확인 중";
      item.append(ticker, status, id);
      elements.discoveryRunList.append(item);
    }
  }

  function discoveryRunFromPayload(payload) {
    const root = payload?.data || payload || {};
    return root.run || root.analysis || (root.run_id || root.id ? root : null);
  }

  function discoveryRunIsTerminal(run) {
    return new Set([
      "review",
      "approved",
      "rejected",
      "hold",
      "failed",
      "cancelled",
      "completed",
      "complete",
    ]).has(discoveryRunStatus(run));
  }

  function stopDiscoveryPolling() {
    if (game.discoveryPollTimer) window.clearTimeout(game.discoveryPollTimer);
    game.discoveryPollTimer = null;
  }

  function scheduleDiscoveryPolling(delay = 2_800) {
    stopDiscoveryPolling();
    if (!game.discoveryRuns.some((run) => !discoveryRunIsTerminal(run))) return;
    game.discoveryPollTimer = window.setTimeout(() => {
      void pollDiscoveryRuns();
    }, delay);
  }

  async function pollDiscoveryRuns(forceRunId = "") {
    stopDiscoveryPolling();
    const currentRuns = [...game.discoveryRuns];
    if (!currentRuns.length) return;
    const updatedRuns = await Promise.all(currentRuns.map(async (storedRun) => {
      const runId = discoveryRunId(storedRun);
      if (discoveryRunIsTerminal(storedRun) && runId !== forceRunId) return storedRun;
      if (!runId) return storedRun;
      try {
        const result = await requestFeatureJson(API.run(runId), {}, 15_000);
        const latest = result.available ? discoveryRunFromPayload(result.payload) : null;
        return latest
          ? {
              ...storedRun,
              ...latest,
              run_id: runId,
              ticker: latest.ticker || storedRun.ticker,
            }
          : storedRun;
      } catch (error) {
        return { ...storedRun, poll_error: error.message };
      }
    }));
    renderDiscoveryRuns(updatedRuns);
    if (updatedRuns.some((run) => !discoveryRunIsTerminal(run))) {
      scheduleDiscoveryPolling();
    } else {
      void loadDecisionArchive({ silent: true });
    }
  }

  function syncTrackedDiscoveryRun(runId, run) {
    if (!runId || !game.discoveryRuns.some((item) => discoveryRunId(item) === runId)) return;
    renderDiscoveryRuns(game.discoveryRuns.map((item) => (
      discoveryRunId(item) === runId
        ? { ...(item || {}), ...(run || {}), run_id: runId }
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
    renderDiscoveryRuns(mergeDiscoveryRuns(incoming, game.discoveryRuns), { persist: false });
    scheduleDiscoveryPolling(350);
  }

  async function submitDiscoveryScreen(event) {
    event.preventDefault();
    const strategy = String(elements.discoveryStrategy?.value || "balanced");
    setFormDisabled(elements.discoveryScreenForm, true);
    if (elements.discoveryAnalyzeSubmit) elements.discoveryAnalyzeSubmit.disabled = true;
    setFeedback(elements.discoveryFeedback, `${discoveryStrategyLabel(strategy)} 전략으로 가격 후보를 선별하는 중입니다.`);
    try {
      const result = await requestFeatureJson(API.discoveryScreen, {
        method: "POST",
        body: JSON.stringify({ strategy, limit: 8 }),
      }, 120_000);
      if (!result.available) {
        game.discoveryAvailable = false;
        renderDiscovery(null);
        setFeedback(elements.discoveryFeedback, "종목 발굴 API가 아직 준비되지 않았습니다. 즉시 분석과 예약 분석은 계속 사용할 수 있습니다.", "error");
        return;
      }
      game.discoveryAvailable = true;
      const discovery = discoveryFromPayload(result.payload);
      renderDiscovery(discovery);
      const count = Array.isArray(discovery?.candidates) ? discovery.candidates.length : 0;
      setFeedback(
        elements.discoveryFeedback,
        `${count}개 가격 후보를 선별했습니다. 상위 ${Math.min(3, count)}개를 기본 선택했으며 매수 보장은 아닙니다.`,
        "success",
      );
      announce("가격 기반 1차 후보를 선별했습니다. 자동 주문은 실행되지 않습니다.");
    } catch (error) {
      renderDiscovery(null);
      setFeedback(elements.discoveryFeedback, `종목 발굴 실패. ${error.message}`, "error");
    } finally {
      setFormDisabled(elements.discoveryScreenForm, false);
      updateDiscoverySelection();
    }
  }

  async function submitDiscoveryAnalysis(event) {
    event.preventDefault();
    const tickers = selectedDiscoveryTickers();
    if (!tickers.length || tickers.length > 3) {
      setFeedback(elements.discoveryFeedback, "심층 분석할 후보를 1개 이상 3개 이하로 선택하세요.", "error");
      return;
    }
    elements.discoveryCandidateList?.querySelectorAll("input").forEach((input) => { input.disabled = true; });
    if (elements.discoveryAnalyzeSubmit) elements.discoveryAnalyzeSubmit.disabled = true;
    setFeedback(elements.discoveryFeedback, `${tickers.join(", ")} 심층 분석을 여섯 에이전트에게 배정하는 중입니다.`);
    try {
      const result = await requestFeatureJson(API.discoveryAnalyze, {
        method: "POST",
        body: JSON.stringify({ tickers }),
      }, 45_000);
      if (!result.available) {
        game.discoveryAvailable = false;
        setFeedback(elements.discoveryFeedback, "발굴 후보 심층 분석 API가 아직 준비되지 않았습니다.", "error");
        return;
      }
      const rawRuns = discoveryRunsFromPayload(result.payload);
      const batchId = `batch-${discoveryRunId(rawRuns[0]) || Date.now()}`;
      const runs = rawRuns.map((run) => ({ ...(run || {}), discovery_batch_id: batchId }));
      renderDiscoveryRuns(runs);
      scheduleDiscoveryPolling(1_000);
      setFeedback(
        elements.discoveryFeedback,
        `${runs.length}건의 심층 분석을 시작했습니다. 완료 결정은 투자위원회 컨트롤룸의 과거 의사결정 카드에서 확인하세요.`,
        "success",
      );
      announce("선택 후보의 심층 분석을 시작했습니다. 실제 주문은 생성하지 않습니다.");
    } catch (error) {
      setFeedback(elements.discoveryFeedback, `후보 심층 분석 시작 실패. ${error.message}`, "error");
    } finally {
      elements.discoveryCandidateList?.querySelectorAll("input").forEach((input) => {
        input.disabled = !input.value;
      });
      updateDiscoverySelection();
    }
  }

  function handleDiscoverySelection(event) {
    const input = event.target.closest('input[name="discovery-ticker"]');
    if (!(input instanceof HTMLInputElement)) return;
    updateDiscoverySelection(input);
  }

  function taskItemsFromPayload(payload) {
    if (Array.isArray(payload)) return payload;
    const root = payload?.data || payload || {};
    if (Array.isArray(root)) return root;
    return root.tasks || root.items || root.results || [];
  }

  function taskStatusLabel(status) {
    const raw = String(status || "queued").toLowerCase();
    return {
      queued: "대기열",
      pending: "대기",
      running: "진행 중",
      in_progress: "진행 중",
      stalled: "중단됨",
      paused: "일시정지",
      done: "완료",
      completed: "완료",
      failed: "실패",
      cancelled: "취소",
      canceled: "취소",
    }[raw] || raw;
  }

  function taskIdentifier(task) {
    return String(task?.task_id || task?.id || "");
  }

  function readableTime(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  }

  function setTaskEmpty(title, detail) {
    if (!elements.taskEmpty) return;
    setText(elements.taskEmpty.querySelector("strong"), title);
    setText(elements.taskEmpty.querySelector("p"), detail);
  }

  function addTaskButton(container, label, action, taskId, danger = false) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `task-action${danger ? " task-action--danger" : ""}`;
    button.dataset.taskAction = action;
    button.dataset.taskId = taskId;
    button.textContent = label;
    button.disabled = !taskId;
    container.append(button);
  }

  function renderAgentTasks(tasks) {
    const values = Array.isArray(tasks) ? tasks : [];
    game.tasks = values;
    setText(elements.taskCount, `${values.length} TASK${values.length === 1 ? "" : "S"}`);
    if (elements.taskList) elements.taskList.replaceChildren();
    if (elements.taskEmpty) elements.taskEmpty.hidden = values.length > 0;
    if (!values.length || !elements.taskList) return;

    for (const task of values) {
      const id = taskIdentifier(task);
      const status = String(task.status || "queued").toLowerCase();
      const card = document.createElement("li");
      card.className = "task-card";
      card.dataset.status = status;

      const heading = document.createElement("div");
      heading.className = "task-card__heading";
      const title = document.createElement("strong");
      title.textContent = String(task.title || task.name || "제목 없는 분석 업무");
      const badge = document.createElement("span");
      badge.className = "task-card__status";
      badge.textContent = taskStatusLabel(status);
      heading.append(title, badge);
      card.append(heading);

      const instructions = document.createElement("p");
      instructions.textContent = String(task.instructions || task.description || task.brief || "세부 지시가 없습니다.");
      card.append(instructions);

      const report = task.latest_report || task.report || task.progress_report || task.progress || task.result;
      if (report) {
        const reportBlock = document.createElement("div");
        reportBlock.className = "task-card__report";
        reportBlock.textContent = String(
          typeof report === "string"
            ? report
            : report.summary || report.content || report.message || "중간보고가 도착했습니다.",
        );
        card.append(reportBlock);
      }

      const meta = document.createElement("div");
      meta.className = "task-card__meta";
      const time = readableTime(task.updated_at || task.updatedAt || task.created_at || task.createdAt);
      meta.textContent = `${id ? `ID ${id.slice(-8)}` : "ID 확인 중"}${time ? ` · ${time}` : ""}`;
      card.append(meta);

      const actions = document.createElement("div");
      actions.className = "task-card__actions";
      if (!["cancelled", "canceled"].includes(status)) addTaskButton(actions, "중간보고 요청", "report", id);
      if (["stalled", "paused", "failed"].includes(status)) addTaskButton(actions, "업무 재개", "resume", id);
      if (["queued", "pending"].includes(status)) {
        addTaskButton(actions, "업무 취소", "cancel", id, true);
      }
      if (actions.children.length) card.append(actions);
      elements.taskList.append(card);
    }
  }

  async function loadAgentTasks(role, { silent = false } = {}) {
    if (!game.currentRunId) {
      game.tasksAvailable = null;
      renderAgentTasks([]);
      setTaskEmpty("선택된 분석 실행이 없습니다.", "접수 데스크에서 종목 분석을 먼저 시작하세요.");
      setFeedback(elements.taskFeedback, "분석 실행이 없어 추가 업무를 배정할 수 없습니다.");
      setFormDisabled(elements.taskForm, true);
      return;
    }
    if (!silent) setFeedback(elements.taskFeedback, "역할별 업무를 불러오는 중입니다.");
    try {
      const result = await requestFeatureJson(API.tasks(game.currentRunId), {}, 15_000);
      if (!result.available) {
        game.tasksAvailable = false;
        renderAgentTasks([]);
        setTaskEmpty("업무 보드 API가 아직 준비되지 않았습니다.", "기존 에이전트 분석 보고는 계속 확인할 수 있습니다.");
        setFeedback(elements.taskFeedback, "업무 배정 기능을 연결할 수 없습니다.", "error");
        setFormDisabled(elements.taskForm, true);
        return;
      }
      game.tasksAvailable = true;
      const tasks = taskItemsFromPayload(result.payload).filter((task) => !task?.role || String(task.role) === role);
      renderAgentTasks(tasks);
      setTaskEmpty("추가 업무가 없습니다.", "위 양식으로 이 역할에 검증 업무를 맡겨보세요.");
      setFeedback(elements.taskFeedback, tasks.length ? `${tasks.length}개 업무를 불러왔습니다.` : "이 역할에 추가된 업무가 없습니다.");
      setFormDisabled(elements.taskForm, false);
    } catch (error) {
      renderAgentTasks([]);
      setTaskEmpty("업무 목록을 불러오지 못했습니다.", "잠시 후 다시 NPC를 선택해 주세요.");
      setFeedback(elements.taskFeedback, error.message, "error");
    }
  }

  function openAgent(role) {
    game.activeAgentRole = role;
    const agent = agentForRole(role);
    const result = agent?.result || agent?.data || {};
    const status = normalizeStatus(agent?.status);
    setText(elements.agentRole, ROLE_LABELS[role] || role);
    setText(elements.agentStatus, STATUS_LABELS[status]);
    if (elements.agentStatus) elements.agentStatus.dataset.status = status;
    setText(elements.agentSummary, agent?.summary || result.summary, "아직 제출된 분석 보고서가 없습니다.");
    replaceList(elements.agentPoints, result.key_points, "등록된 관찰이 없습니다.");
    replaceList(elements.agentRisks, result.risks, "등록된 위험이 없습니다.");
    if (elements.taskRole) elements.taskRole.value = role;
    openDialog(elements.agentPanel, `${ROLE_LABELS[role] || role} 워크스테이션`);
    void loadAgentTasks(role);
  }

  async function submitAgentTask(event) {
    event.preventDefault();
    const role = game.activeAgentRole || String(elements.taskRole?.value || "");
    const title = String(elements.taskTitle?.value || "").trim();
    const instructions = String(elements.taskInstructions?.value || "").trim();
    if (!game.currentRunId || !role) {
      setFeedback(elements.taskFeedback, "먼저 분석 실행과 담당 역할을 선택하세요.", "error");
      return;
    }
    if (!title || !instructions) {
      setFeedback(elements.taskFeedback, "업무 제목과 조사 지시를 모두 입력하세요.", "error");
      return;
    }
    setFormDisabled(elements.taskForm, true);
    setFeedback(elements.taskFeedback, `${ROLE_LABELS[role] || role}에게 업무를 배정하는 중입니다.`);
    try {
      const result = await requestFeatureJson(API.tasks(game.currentRunId), {
        method: "POST",
        body: JSON.stringify({ role, title, instructions }),
      }, 30_000);
      if (!result.available) {
        game.tasksAvailable = false;
        setFeedback(elements.taskFeedback, "업무 배정 API가 아직 준비되지 않았습니다.", "error");
        return;
      }
      elements.taskForm?.reset();
      if (elements.taskRole) elements.taskRole.value = role;
      setFeedback(elements.taskFeedback, "분석 업무를 배정했습니다. 사람이 중간보고를 확인할 수 있습니다.", "success");
      announce(`${ROLE_LABELS[role] || role}에게 추가 분석 업무를 배정했습니다.`);
      await loadAgentTasks(role, { silent: true });
    } catch (error) {
      setFeedback(elements.taskFeedback, `업무 배정 실패. ${error.message}`, "error");
    } finally {
      setFormDisabled(elements.taskForm, game.tasksAvailable === false || !game.currentRunId);
    }
  }

  async function handleTaskAction(event) {
    const button = event.target.closest?.("[data-task-action]");
    if (!button) return;
    const taskId = button.dataset.taskId;
    const action = button.dataset.taskAction;
    const endpoint = {
      report: API.taskReport,
      resume: API.taskResume,
      cancel: API.taskCancel,
    }[action];
    if (!taskId || !endpoint) return;
    button.disabled = true;
    const actionLabel = { report: "중간보고 요청", resume: "업무 재개", cancel: "업무 취소" }[action];
    setFeedback(elements.taskFeedback, `${actionLabel}을 처리하는 중입니다.`);
    try {
      const result = await requestFeatureJson(endpoint(taskId), { method: "POST", body: "{}" }, 30_000);
      if (!result.available) {
        setFeedback(elements.taskFeedback, `${actionLabel} API가 아직 준비되지 않았습니다.`, "error");
        return;
      }
      if (action === "report") {
        const report = result.payload?.report || result.payload?.data?.report || result.payload;
        const reportSummary = report?.result?.summary || report?.progress?.summary || report?.error;
        const reportStatus = taskStatusLabel(report?.status);
        setFeedback(
          elements.taskFeedback,
          reportSummary
            ? `저장된 최신 상태·${reportStatus}. ${reportSummary}`
            : `저장된 최신 상태·${reportStatus}. 아직 실질적인 중간 결과가 없습니다.`,
          "success",
        );
        announce("새 모델 호출 없이 실제 저장된 업무 상태를 확인했습니다.");
      } else {
        setFeedback(elements.taskFeedback, `${actionLabel}을 기록했습니다.`, "success");
        announce(`${actionLabel}을 사람의 지시로 전달했습니다.`);
      }
      await loadAgentTasks(game.activeAgentRole, { silent: true });
      await refreshRun();
    } catch (error) {
      setFeedback(elements.taskFeedback, `${actionLabel} 실패. ${error.message}`, "error");
    } finally {
      button.disabled = false;
    }
  }

  function reviewable() {
    return game.run?.status === "review" && !game.run?.human_review;
  }

  function renderDecisionDraft() {
    const decision = game.run?.decision || {};
    const confidence = Number(decision.confidence);
    setText(elements.decisionRecommendation, decision.recommendation, "결정 대기");
    setText(
      elements.decisionSummary,
      decision.summary,
      game.run?.status === "failed"
        ? game.run.error || "분석이 실패했습니다."
        : "여섯 에이전트의 분석이 완료되면 위원장의 결정 초안이 표시됩니다.",
    );
    setText(
      elements.decisionConfidence,
      Number.isFinite(confidence) ? `${Math.round(confidence <= 1 ? confidence * 100 : confidence)}%` : "—",
    );
    replaceList(elements.decisionPoints, decision.key_points, "등록된 근거가 없습니다.");
    replaceList(elements.decisionRisks, decision.risks, "등록된 리스크가 없습니다.");
    document.querySelectorAll("[data-review-decision]").forEach((button) => {
      button.disabled = !reviewable();
    });
    if (game.run?.human_review && elements.reviewReason) {
      elements.reviewReason.value = game.run.human_review.reason || "";
      elements.reviewReason.disabled = true;
    } else if (elements.reviewReason) {
      elements.reviewReason.disabled = !reviewable();
    }
  }

  function decisionsFromPayload(payload) {
    if (Array.isArray(payload)) return payload;
    const root = payload?.data || payload || {};
    if (Array.isArray(root)) return root;
    return root.decisions || root.items || root.results || root.history || [];
  }

  function decisionFromPayload(payload) {
    if (!payload) return null;
    const root = payload.data || payload;
    return root.decision || root.record || root.run || root;
  }

  function decisionIdentifier(record) {
    return String(record?.run_id || record?.analysis_run_id || record?.run?.run_id || record?.id || "");
  }

  function decisionStatusLabel(status) {
    const raw = String(status || "completed").toLowerCase();
    return {
      queued: "대기",
      running: "분석 중",
      review: "사람 검토 대기",
      completed: "분석 완료",
      complete: "분석 완료",
      approved: "사람 승인",
      deferred: "사람 보류",
      hold: "사람 보류",
      rejected: "사람 기각",
      failed: "분석 실패",
    }[raw] || raw;
  }

  function recommendationLabel(value) {
    const raw = String(value || "pending").toLowerCase();
    return {
      buy: "매수 검토",
      "conditional buy": "조건부 매수 검토",
      approve: "매수 검토",
      approved: "매수 검토",
      accumulate: "분할 접근",
      hold: "관망",
      "hold and watch": "관망",
      neutral: "중립",
      wait: "대기",
      sell: "매도 검토",
      reduce: "비중 축소",
      avoid: "접근 보류",
      reject: "접근 보류",
      rejected: "접근 보류",
      pending: "결정 대기",
    }[raw] || String(value || "결정 대기");
  }

  function confidenceLabel(value) {
    const confidence = Number(value);
    if (!Number.isFinite(confidence)) return "—";
    return `${Math.round(confidence <= 1 ? confidence * 100 : confidence)}%`;
  }

  function decisionView(record) {
    const decision = record?.decision || record?.result?.decision || record?.result || record || {};
    const review = record?.latest_human_review || record?.human_review || record?.review || decision?.human_review || {};
    const schedule = record?.scheduled_analysis || record?.schedule || record?.scheduled_task || record?.reservation || {};
    const scheduleTime = schedule.scheduled_for || record?.scheduled_for || record?.schedule_time;
    const reviewDecision = typeof review === "string"
      ? review
      : review.decision || review.result || review.status || record?.review_decision;
    const reviewReason = typeof review === "object" && review
      ? review.rationale || review.reason || review.comment || review.note
      : record?.review_reason;
    const error = record?.error || record?.run?.error || decision?.error;
    return {
      id: decisionIdentifier(record),
      ticker: String(record?.ticker || record?.symbol || record?.candidate?.ticker || record?.run?.ticker || "종목 미정").toUpperCase(),
      date: record?.decision_captured_at || record?.decided_at || record?.completed_at || record?.updated_at || record?.requested_at || record?.created_at || decision?.created_at,
      status: record?.effective_status || record?.status || record?.run_status || record?.run?.status || "completed",
      recommendation: decision?.recommendation || decision?.action || decision?.decision || record?.recommendation,
      confidence: decision?.confidence ?? decision?.confidence_score ?? record?.confidence,
      summary: decision?.summary
        || decision?.rationale
        || record?.summary
        || (error ? `실패 원인 · ${error}` : "저장된 요약이 없습니다."),
      error,
      reviewDecision,
      reviewReason,
      scheduleTime,
      scheduleStatus: schedule.status || record?.schedule_status,
      scheduleId: scheduleIdentifier(schedule) || String(record?.schedule_id || ""),
    };
  }

  function createDecisionArchiveCard(record) {
    const view = decisionView(record);
    const item = document.createElement("li");
    item.className = "decision-history-card";
    item.dataset.status = String(view.status || "completed").toLowerCase();
    if (view.id) item.dataset.runId = view.id;

    const heading = document.createElement("div");
    heading.className = "decision-history-card__heading";
    const identity = document.createElement("div");
    const ticker = document.createElement("strong");
    ticker.textContent = view.ticker;
    const time = document.createElement("time");
    if (view.date) time.dateTime = String(view.date);
    time.textContent = readableKstTime(view.date, "기록 시각 미정");
    identity.append(ticker, time);
    const recommendation = document.createElement("span");
    recommendation.className = "decision-history-card__recommendation";
    recommendation.textContent = recommendationLabel(view.recommendation);
    recommendation.dataset.recommendation = String(view.recommendation || "pending").toLowerCase();
    heading.append(identity, recommendation);

    const telemetry = document.createElement("dl");
    telemetry.className = "decision-history-card__telemetry";
    for (const [label, value] of [
      ["STATUS", decisionStatusLabel(view.status)],
      ["CONFIDENCE", confidenceLabel(view.confidence)],
      ["RUN", view.id ? view.id.slice(-8) : "미배정"],
    ]) {
      const cell = document.createElement("div");
      const term = document.createElement("dt");
      const description = document.createElement("dd");
      term.textContent = label;
      description.textContent = value;
      cell.append(term, description);
      telemetry.append(cell);
    }

    const summary = document.createElement("p");
    summary.className = "decision-history-card__summary";
    summary.textContent = String(view.summary);

    const provenance = document.createElement("div");
    provenance.className = "decision-history-card__provenance";
    const review = document.createElement("p");
    const reviewLabel = view.reviewDecision ? decisionStatusLabel(view.reviewDecision) : "사람 검토 미기록";
    review.innerHTML = "<strong>HUMAN REVIEW</strong>";
    review.append(document.createTextNode(`${reviewLabel}${view.reviewReason ? ` · ${view.reviewReason}` : ""}`));
    const schedule = document.createElement("p");
    schedule.innerHTML = "<strong>SCHEDULE</strong>";
    const scheduleText = view.scheduleTime
      ? `${readableKstTime(view.scheduleTime)} KST${view.scheduleStatus ? ` · ${scheduleStatusLabel(view.scheduleStatus)}` : ""}`
      : "예약 없이 즉시 실행";
    schedule.append(document.createTextNode(`${scheduleText}${view.scheduleId ? ` · ${view.scheduleId.slice(-8)}` : ""}`));
    provenance.append(review, schedule);

    item.append(heading, telemetry, summary, provenance);
    if (view.id) {
      const detailButton = document.createElement("button");
      detailButton.type = "button";
      detailButton.className = "decision-history-card__detail task-action";
      detailButton.dataset.decisionRunId = view.id;
      detailButton.textContent = "카드 최신 상태 새로고침";
      item.append(detailButton);
    }
    return item;
  }

  function renderDecisionArchive(decisions) {
    const values = Array.isArray(decisions) ? decisions : [];
    game.decisions = values;
    elements.decisionArchiveList?.replaceChildren();
    if (elements.decisionArchiveEmpty) elements.decisionArchiveEmpty.hidden = values.length > 0;
    if (!values.length || !elements.decisionArchiveList) return;
    for (const decision of values) elements.decisionArchiveList.append(createDecisionArchiveCard(decision));
  }

  async function loadDecisionArchive({ silent = false } = {}) {
    if (!silent) setFeedback(elements.decisionArchiveFeedback, "과거 의사결정 카드를 불러오는 중입니다.");
    try {
      const result = await requestFeatureJson(API.decisions, {}, 15_000);
      if (!result.available) {
        game.decisionsAvailable = false;
        renderDecisionArchive([]);
        setFeedback(elements.decisionArchiveFeedback, "의사결정 아카이브 API가 아직 준비되지 않았습니다.", "error");
        if (elements.decisionArchiveEmpty) {
          setText(elements.decisionArchiveEmpty.querySelector("strong"), "과거 카드 기능을 연결할 수 없습니다.");
          setText(elements.decisionArchiveEmpty.querySelector("p"), "현재 실행의 결정 초안과 사람 검토는 계속 사용할 수 있습니다.");
        }
        return;
      }
      game.decisionsAvailable = true;
      const decisions = decisionsFromPayload(result.payload);
      if (elements.decisionArchiveEmpty) {
        setText(elements.decisionArchiveEmpty.querySelector("strong"), "보관된 의사결정 카드가 없습니다.");
        setText(elements.decisionArchiveEmpty.querySelector("p"), "분석이 완료되면 종목별 결정과 사람 검토 이력이 여기에 쌓입니다.");
      }
      renderDecisionArchive(decisions);
      setFeedback(
        elements.decisionArchiveFeedback,
        decisions.length
          ? `최근 의사결정 카드 ${decisions.length}건을 불러왔습니다. 기록은 자동 주문 지시가 아닙니다.`
          : "아직 보관된 의사결정 카드가 없습니다.",
      );
    } catch (error) {
      renderDecisionArchive([]);
      if (elements.decisionArchiveEmpty) {
        setText(elements.decisionArchiveEmpty.querySelector("strong"), "의사결정 카드를 불러오지 못했습니다.");
        setText(elements.decisionArchiveEmpty.querySelector("p"), "연결 상태를 확인한 뒤 최신 기록을 다시 요청하세요.");
      }
      setFeedback(elements.decisionArchiveFeedback, `의사결정 카드를 불러오지 못했습니다. ${error.message}`, "error");
    }
  }

  async function loadDecisionDetail(event) {
    const button = event.target.closest("[data-decision-run-id]");
    if (!(button instanceof HTMLButtonElement)) return;
    const runId = String(button.dataset.decisionRunId || "");
    if (!runId) return;
    button.disabled = true;
    button.textContent = "최신 상태 확인 중";
    try {
      const result = await requestFeatureJson(API.decision(runId), {}, 15_000);
      if (!result.available) {
        setFeedback(elements.decisionArchiveFeedback, "의사결정 상세 API가 아직 준비되지 않았습니다.", "error");
        return;
      }
      const detail = decisionFromPayload(result.payload);
      const index = game.decisions.findIndex((record) => decisionIdentifier(record) === runId);
      if (detail && index >= 0) {
        const current = game.decisions[index] || {};
        game.decisions[index] = {
          ...current,
          ...detail,
          decision: { ...(current.decision || {}), ...(detail.decision || {}) },
        };
        renderDecisionArchive(game.decisions);
      }
      setFeedback(elements.decisionArchiveFeedback, `${runId.slice(-8)} 실행의 최신 저장 상태를 다시 불러왔습니다.`, "success");
    } catch (error) {
      setFeedback(elements.decisionArchiveFeedback, `의사결정 상세 확인 실패. ${error.message}`, "error");
    } finally {
      button.disabled = false;
      button.textContent = "카드 최신 상태 새로고침";
    }
  }

  function committeeFromPayload(payload) {
    if (!payload) return null;
    const root = payload.data || payload;
    return root.committee ?? root.session ?? (root.id || root.committee_id ? root : null);
  }

  function committeeIdentifier(committee) {
    return String(committee?.committee_id || committee?.id || committee?.session_id || "");
  }

  function committeeStatusLabel(status) {
    const raw = String(status || "idle").toLowerCase();
    return {
      idle: "회의 없음",
      queued: "소집 대기",
      running: "토론 진행 중",
      active: "토론 진행 중",
      started: "토론 진행 중",
      completed: "회의 완료",
      complete: "회의 완료",
      done: "회의 완료",
      stop_requested: "중단 처리 중",
      stopped: "사람이 중단",
      cancelled: "사람이 중단",
      failed: "회의 오류",
    }[raw] || raw;
  }

  function committeeIsActive(committee = game.committee) {
    return ["queued", "running", "active", "started", "stop_requested"].includes(
      String(committee?.status || "").toLowerCase(),
    );
  }

  function committeeEntries(committee) {
    return committee?.timeline || committee?.statements || committee?.turns || committee?.messages || [];
  }

  function setCommitteeEmpty(title, detail) {
    if (!elements.committeeEmpty) return;
    setText(elements.committeeEmpty.querySelector("strong"), title);
    setText(elements.committeeEmpty.querySelector("p"), detail);
  }

  function renderCommitteeTimeline(committee) {
    const entries = Array.isArray(committeeEntries(committee)) ? committeeEntries(committee) : [];
    elements.committeeTimeline?.replaceChildren();
    if (elements.committeeEmpty) elements.committeeEmpty.hidden = entries.length > 0;
    if (!entries.length || !elements.committeeTimeline) {
      setCommitteeEmpty(
        committee ? "첫 발언을 기다리는 중입니다." : "진행 중인 위원회가 없습니다.",
        committee ? "참가 역할이 주장과 근거를 준비하고 있습니다." : "참가자와 주제를 정해 사람 감독형 토론을 시작하세요.",
      );
      return;
    }
    for (const [index, entry] of entries.entries()) {
      const item = document.createElement("li");
      item.className = "committee-timeline-item";
      const meta = document.createElement("div");
      meta.className = "committee-timeline-item__meta";
      const speaker = document.createElement("strong");
      const role = String(entry.role || entry.speaker_role || entry.participant || entry.speaker || "위원회");
      speaker.textContent = ROLE_LABELS[role] || entry.speaker_name || role;
      const turn = document.createElement("span");
      turn.textContent = readableTime(entry.created_at || entry.timestamp) || `TURN ${String(index + 1).padStart(2, "0")}`;
      meta.append(speaker, turn);
      const speech = document.createElement("p");
      speech.textContent = String(entry.content || entry.statement || entry.message || entry.text || "발언 내용이 없습니다.");
      item.append(meta, speech);
      elements.committeeTimeline.append(item);
    }
  }

  function evidenceText(value) {
    if (typeof value === "string") return value;
    return String(value?.summary || value?.text || value?.source || value?.title || "근거 내용 확인 중");
  }

  function committeeClaims(committee) {
    const direct = committee?.claims || committee?.claim_ledger || committee?.evidence_ledger || committee?.claim_evidence;
    if (Array.isArray(direct)) return direct;
    const derived = [];
    for (const entry of committeeEntries(committee)) {
      if (Array.isArray(entry?.claims)) derived.push(...entry.claims);
      else if (entry?.claim) derived.push(entry);
    }
    return derived;
  }

  function renderCommitteeClaims(committee) {
    if (!elements.committeeClaims) return;
    elements.committeeClaims.replaceChildren();
    const claims = committeeClaims(committee);
    if (!claims.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state empty-state--compact";
      const text = document.createElement("strong");
      text.textContent = "정리된 주장과 근거가 없습니다.";
      empty.append(text);
      elements.committeeClaims.append(empty);
      return;
    }
    for (const claim of claims) {
      const card = document.createElement("article");
      card.className = "claim-card";
      const claimSide = document.createElement("div");
      const claimLabel = document.createElement("small");
      claimLabel.textContent = "CLAIM";
      const claimText = document.createElement("p");
      claimText.textContent = evidenceText(claim.claim || claim.statement || claim);
      claimSide.append(claimLabel, claimText);

      const evidenceSide = document.createElement("div");
      const evidenceLabel = document.createElement("small");
      evidenceLabel.textContent = "EVIDENCE";
      const evidenceValues = claim.evidence || claim.sources || claim.citations || [];
      if (Array.isArray(evidenceValues) && evidenceValues.length) {
        const list = document.createElement("ul");
        for (const evidence of evidenceValues) {
          const item = document.createElement("li");
          item.textContent = evidenceText(evidence);
          list.append(item);
        }
        evidenceSide.append(evidenceLabel, list);
      } else {
        const evidence = document.createElement("p");
        evidence.textContent = evidenceText(evidenceValues || claim.evidence_summary || "연결된 근거가 없습니다.");
        evidenceSide.append(evidenceLabel, evidence);
      }
      card.append(claimSide, evidenceSide);
      elements.committeeClaims.append(card);
    }
  }

  function appendMinutesSection(container, title, value) {
    if (value === null || value === undefined || value === "") return;
    const heading = document.createElement("h4");
    heading.textContent = title;
    container.append(heading);
    const values = Array.isArray(value) ? value : [value];
    if (values.length > 1) {
      const list = document.createElement("ul");
      for (const entry of values) {
        const item = document.createElement("li");
        item.textContent = evidenceText(entry);
        list.append(item);
      }
      container.append(list);
    } else {
      const paragraph = document.createElement("p");
      paragraph.textContent = evidenceText(values[0]);
      container.append(paragraph);
    }
  }

  function renderCommitteeMinutes(payload) {
    if (!elements.committeeMinutes) return;
    elements.committeeMinutes.replaceChildren();
    const minutes = payload?.minutes ?? payload?.data?.minutes ?? payload;
    if (!minutes) {
      const empty = document.createElement("p");
      empty.textContent = "회의록이 아직 작성되지 않았습니다.";
      elements.committeeMinutes.append(empty);
      return;
    }
    if (typeof minutes === "string") {
      const paragraph = document.createElement("p");
      paragraph.textContent = minutes;
      elements.committeeMinutes.append(paragraph);
      return;
    }
    appendMinutesSection(elements.committeeMinutes, "요약", minutes.summary || minutes.overview);
    appendMinutesSection(elements.committeeMinutes, "위원장 요약", minutes.chairman_summary);
    appendMinutesSection(elements.committeeMinutes, "강세 논리", minutes.bull_case);
    appendMinutesSection(elements.committeeMinutes, "약세 논리", minutes.bear_case);
    appendMinutesSection(elements.committeeMinutes, "합의점", minutes.agreements || minutes.key_points || minutes.decisions);
    appendMinutesSection(
      elements.committeeMinutes,
      "핵심 주장",
      Array.isArray(minutes.claim_ledger)
        ? minutes.claim_ledger.filter((entry) => entry?.kind === "claim").map((entry) => entry.text)
        : null,
    );
    appendMinutesSection(elements.committeeMinutes, "미해결 쟁점", minutes.open_questions || minutes.unresolved || minutes.disagreements);
    appendMinutesSection(elements.committeeMinutes, "데이터 공백", minutes.data_gaps);
    appendMinutesSection(elements.committeeMinutes, "실패·누락", minutes.failures);
    appendMinutesSection(elements.committeeMinutes, "후속 검증", minutes.action_items || minutes.follow_ups);
    if (minutes.human_approval_required) {
      appendMinutesSection(elements.committeeMinutes, "최종 게이트", "이 회의록은 분석 초안이며 실제 주문은 사람이 별도로 판단합니다.");
    }
    if (!elements.committeeMinutes.children.length) {
      appendMinutesSection(elements.committeeMinutes, "회의록", evidenceText(minutes));
    }
  }

  function setCommitteeControls(active) {
    if (elements.committeeStart) elements.committeeStart.disabled = active || !game.currentRunId || game.committeeAvailable === false;
    if (elements.committeeFinish) elements.committeeFinish.disabled = !active || !game.committeeId;
    if (elements.committeeStop) elements.committeeStop.disabled = !active || !game.committeeId;
    elements.committeeCommandForm?.querySelectorAll("input, select, button").forEach((control) => {
      control.disabled = !active || !game.committeeId;
    });
  }

  function applyCommittee(committee) {
    game.committee = committee;
    game.committeeId = committeeIdentifier(committee) || null;
    const status = String(committee?.status || "idle").toLowerCase();
    setText(elements.committeeStatus, committeeStatusLabel(status));
    if (elements.committeeStatus) elements.committeeStatus.dataset.status = status;
    setText(elements.committeeTopicReadout, committee?.topic || committee?.subject, "주제 미정");
    renderCommitteeTimeline(committee);
    renderCommitteeClaims(committee);
    setCommitteeControls(committeeIsActive(committee));
    if (committeeIsActive(committee)) scheduleCommitteePoll();
    else stopCommitteePolling();
  }

  async function loadCommitteeMinutes(committeeId) {
    if (!committeeId) {
      renderCommitteeMinutes(null);
      return;
    }
    try {
      const result = await requestFeatureJson(API.committeeMinutes(committeeId), {}, 15_000);
      renderCommitteeMinutes(result.available ? result.payload : null);
    } catch (error) {
      renderCommitteeMinutes(null);
      setFeedback(elements.committeeFeedback, `회의록을 불러오지 못했습니다. ${error.message}`, "error");
    }
  }

  async function loadCommittee({ silent = false } = {}) {
    if (!game.currentRunId) {
      game.committeeAvailable = null;
      applyCommittee(null);
      setFeedback(elements.committeeFeedback, "분석 실행이 없어 위원회를 소집할 수 없습니다.");
      setFormDisabled(elements.committeeStartForm, true);
      return;
    }
    if (!silent) setFeedback(elements.committeeFeedback, "위원회 상태를 불러오는 중입니다.");
    try {
      const result = await requestFeatureJson(API.runCommittee(game.currentRunId), {}, 15_000);
      if (!result.available) {
        game.committeeAvailable = false;
        applyCommittee(null);
        setCommitteeEmpty("위원회 API가 아직 준비되지 않았습니다.", "기존 결정 초안과 사람 검토 기능은 계속 사용할 수 있습니다.");
        setFeedback(elements.committeeFeedback, "회의 제어 기능을 연결할 수 없습니다.", "error");
        setFormDisabled(elements.committeeStartForm, true);
        return;
      }
      game.committeeAvailable = true;
      let committee = committeeFromPayload(result.payload);
      const committeeId = committeeIdentifier(committee);
      if (committeeId) {
        const detail = await requestFeatureJson(API.committee(committeeId), {}, 15_000);
        if (detail.available) committee = { ...committee, ...(committeeFromPayload(detail.payload) || {}) };
      }
      applyCommittee(committee);
      setFormDisabled(elements.committeeStartForm, committeeIsActive(committee));
      setCommitteeControls(committeeIsActive(committee));
      setFeedback(
        elements.committeeFeedback,
        committee ? `${committeeStatusLabel(committee.status)} 상태입니다.` : "아직 소집된 위원회가 없습니다.",
      );
      await loadCommitteeMinutes(committeeIdentifier(committee));
    } catch (error) {
      setFeedback(elements.committeeFeedback, `위원회 상태 확인 실패. ${error.message}`, "error");
    }
  }

  function openCommittee() {
    game.activeAgentRole = null;
    renderDecisionDraft();
    if (elements.committeeTopic && !elements.committeeTopic.value && game.run?.ticker) {
      elements.committeeTopic.value = `${game.run.ticker}의 현재 투자 가설과 핵심 하방 위험을 근거 중심으로 검토한다.`;
    }
    openDialog(elements.committeePanel, "투자위원회 컨트롤룸");
    void Promise.all([loadCommittee(), loadDecisionArchive()]);
  }

  async function submitCommitteeStart(event) {
    event.preventDefault();
    const topic = String(elements.committeeTopic?.value || "").trim();
    const participants = Array.from(
      elements.committeeStartForm?.querySelectorAll('input[name="participants"]:checked') || [],
      (input) => input.value,
    );
    if (!game.currentRunId) {
      setFeedback(elements.committeeFeedback, "먼저 분석 실행을 선택하세요.", "error");
      return;
    }
    if (!topic) {
      setFeedback(elements.committeeFeedback, "토론 주제를 입력하세요.", "error");
      elements.committeeTopic?.focus();
      return;
    }
    if (participants.length < 2) {
      setFeedback(elements.committeeFeedback, "서로 다른 관점을 위해 참가 역할을 두 명 이상 선택하세요.", "error");
      return;
    }
    setFormDisabled(elements.committeeStartForm, true);
    setFeedback(elements.committeeFeedback, "위원회를 소집하고 있습니다.");
    try {
      const result = await requestFeatureJson(API.startCommittee(game.currentRunId), {
        method: "POST",
        body: JSON.stringify({ topic, participants }),
      }, 45_000);
      if (!result.available) {
        game.committeeAvailable = false;
        setFeedback(elements.committeeFeedback, "위원회 시작 API가 아직 준비되지 않았습니다.", "error");
        return;
      }
      game.committeeAvailable = true;
      const committee = committeeFromPayload(result.payload);
      if (committee) applyCommittee(committee);
      setFeedback(elements.committeeFeedback, "사람 감독형 투자위원회를 시작했습니다.", "success");
      announce("투자위원회 토론을 시작했습니다. 자동 주문은 실행되지 않습니다.");
      await loadCommittee({ silent: true });
    } catch (error) {
      setFeedback(elements.committeeFeedback, `위원회 시작 실패. ${error.message}`, "error");
    } finally {
      setFormDisabled(elements.committeeStartForm, committeeIsActive());
      setCommitteeControls(committeeIsActive());
    }
  }

  async function sendCommitteeCommand(command, role = null, prompt = "") {
    if (!game.committeeId) {
      setFeedback(elements.committeeFeedback, "진행 중인 위원회가 없습니다.", "error");
      return;
    }
    if (elements.committeeStart) elements.committeeStart.disabled = true;
    if (elements.committeeFinish) elements.committeeFinish.disabled = true;
    if (elements.committeeStop) elements.committeeStop.disabled = true;
    elements.committeeCommandForm?.querySelectorAll("input, select, button").forEach((control) => {
      control.disabled = true;
    });
    const label = command === "stop"
      ? "회의 중단"
      : command === "finish"
        ? "회의록 확정"
        : `${ROLE_LABELS[role] || role} 추가 발언`;
    setFeedback(elements.committeeFeedback, `${label} 요청을 전달하는 중입니다.`);
    try {
      const result = await requestFeatureJson(API.committeeCommands(game.committeeId), {
        method: "POST",
        body: JSON.stringify({ command, ...(role ? { role } : {}), ...(prompt ? { prompt } : {}) }),
      }, 30_000);
      if (!result.available) {
        setFeedback(elements.committeeFeedback, "위원회 명령 API가 아직 준비되지 않았습니다.", "error");
        return;
      }
      const committee = committeeFromPayload(result.payload);
      if (committee) applyCommittee(committee);
      if (command === "request_speech" && elements.committeeCommandPrompt) elements.committeeCommandPrompt.value = "";
      setFeedback(elements.committeeFeedback, `${label} 요청을 기록했습니다.`, "success");
      announce(`${label}을 사람의 지시로 전달했습니다.`);
      await loadCommittee({ silent: true });
    } catch (error) {
      setFeedback(elements.committeeFeedback, `${label} 실패. ${error.message}`, "error");
    } finally {
      setCommitteeControls(committeeIsActive());
    }
  }

  function submitCommitteeCommand(event) {
    event.preventDefault();
    const role = String(elements.committeeCommandRole?.value || "");
    const prompt = String(elements.committeeCommandPrompt?.value || "").trim();
    if (!role) return;
    void sendCommitteeCommand("request_speech", role, prompt);
  }

  function stopCommittee() {
    void sendCommitteeCommand("stop");
  }

  function finishCommittee() {
    void sendCommitteeCommand("finish");
  }

  function stopCommitteePolling() {
    if (game.committeePollTimer) window.clearTimeout(game.committeePollTimer);
    game.committeePollTimer = null;
  }

  function scheduleCommitteePoll(delay = 2_400) {
    stopCommitteePolling();
    if (!committeeIsActive() || !elements.dialog?.open || elements.committeePanel?.hidden) return;
    game.committeePollTimer = window.setTimeout(async () => {
      await loadCommittee({ silent: true });
      if (committeeIsActive()) scheduleCommitteePoll();
    }, delay);
  }

  function interact(target = game.nearestInteraction) {
    if (!target) {
      announce("상호작용할 대상에 더 가까이 이동하세요.");
      return;
    }
    if (target.kind === "intake") {
      openDialog(elements.intakePanel, "후보 접수 터미널");
      configureScheduleTime();
      void loadSchedules();
      elements.tickerInput?.focus();
    } else if (target.kind === "committee") {
      openCommittee();
    } else {
      openAgent(target.role);
    }
  }

  function pointerToWorld(event) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: camera.x + ((event.clientX - rect.left) / rect.width) * camera.width,
      y: camera.y + ((event.clientY - rect.top) / rect.height) * camera.height,
    };
  }

  function handleCanvasPointer(event) {
    canvas.focus({ preventScroll: true });
    const point = pointerToWorld(event);
    const target = interactionTargets().find((item) => Math.hypot(point.x - item.x, point.y - item.y) <= 62);
    if (target) interact(target);
  }

  async function requestJson(url, options = {}, timeoutMs = 20_000) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, {
        headers: { Accept: "application/json", "Content-Type": "application/json", ...(options.headers || {}) },
        ...options,
        signal: controller.signal,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = payload.detail;
        const message = Array.isArray(detail)
          ? detail.map((item) => item.msg || JSON.stringify(item)).join(" · ")
          : detail || payload.error || `${response.status} ${response.statusText}`;
        throw new ApiRequestError(message, response.status, payload);
      }
      return payload;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("요청 시간이 초과됐습니다.");
      throw error;
    } finally {
      window.clearTimeout(timer);
    }
  }

  async function requestFeatureJson(url, options = {}, timeoutMs = 20_000) {
    try {
      return { available: true, missing: false, payload: await requestJson(url, options, timeoutMs) };
    } catch (error) {
      if (error instanceof ApiRequestError && [404, 405, 501].includes(error.status)) {
        return {
          available: false,
          missing: error.status === 404,
          payload: null,
          error,
        };
      }
      throw error;
    }
  }

  function applyRun(payload) {
    const run = payload?.run || payload?.data?.run || payload?.data || payload;
    if (!run || typeof run !== "object") return;
    const previousRunId = game.currentRunId;
    const nextRunId = String(run.run_id || run.id || previousRunId || "") || null;
    if (previousRunId && nextRunId && previousRunId !== nextRunId) {
      game.tasks = [];
      game.committee = null;
      game.committeeId = null;
      game.tasksAvailable = null;
      game.committeeAvailable = null;
      stopCommitteePolling();
    }
    game.run = run;
    game.currentRunId = nextRunId;
    const completed = (run.agents || []).filter((agent) => normalizeStatus(agent.status) === "done").length;
    setText(elements.ticker, run.ticker);
    setText(elements.progress, `${Math.min(completed, 6)} / 6`);
    setText(elements.runStatus, runStatusLabel(run.status));
    if (elements.runStatus) elements.runStatus.className = `hud-value is-${normalizeStatus(run.status)}`;
    if (["queued", "running"].includes(run.status)) schedulePoll();
    else stopPolling();
  }

  function applyProvider(provider) {
    if (!provider || typeof provider !== "object") return;
    game.provider = provider;
    setText(elements.provider, provider.name || provider.status, "오프라인");
    if (provider.status === "offline") announce(provider.detail || "분석 Provider가 오프라인입니다.", true);
  }

  async function loadInitialState() {
    try {
      const payload = await requestJson(API.state, {}, 15_000);
      applyProvider(payload.provider || payload.data?.provider);
      const run = payload.latest_run || payload.active_run || payload.current_run || payload.run;
      if (run) applyRun(run);
      else {
        setText(elements.runStatus, "대기");
        setText(elements.ticker, "—");
        setText(elements.progress, "0 / 6");
      }
    } catch (error) {
      announce(`초기 상태를 불러오지 못했습니다. ${error.message}`, true);
      setText(elements.provider, "연결 오류");
    }
  }

  async function refreshRun() {
    if (!game.currentRunId) return;
    try {
      const payload = await requestJson(API.run(game.currentRunId), {}, 15_000);
      applyRun(payload);
      if (elements.dialog?.open && !elements.committeePanel?.hidden) renderDecisionDraft();
      schedulePanelRefresh();
    } catch (error) {
      announce(`실행 상태를 갱신하지 못했습니다. ${error.message}`, true);
    }
  }

  function stopPolling() {
    if (game.pollTimer) window.clearTimeout(game.pollTimer);
    game.pollTimer = null;
  }

  function schedulePoll(delay = 2_800) {
    stopPolling();
    game.pollTimer = window.setTimeout(async () => {
      await refreshRun();
      if (game.run && ["queued", "running"].includes(game.run.status)) schedulePoll();
    }, delay);
  }

  function scheduleRefresh(delay = 160) {
    if (game.refreshTimer) window.clearTimeout(game.refreshTimer);
    game.refreshTimer = window.setTimeout(refreshRun, delay);
  }

  async function refreshActivePanel() {
    if (!elements.dialog?.open) return;
    if (!elements.intakePanel?.hidden) {
      await loadSchedules({ silent: true });
    } else if (!elements.agentPanel?.hidden && game.activeAgentRole) {
      await loadAgentTasks(game.activeAgentRole, { silent: true });
    } else if (!elements.committeePanel?.hidden) {
      await Promise.all([loadCommittee({ silent: true }), loadDecisionArchive({ silent: true })]);
    }
  }

  function schedulePanelRefresh(delay = 260) {
    if (game.panelRefreshTimer) window.clearTimeout(game.panelRefreshTimer);
    game.panelRefreshTimer = window.setTimeout(refreshActivePanel, delay);
  }

  function connectEvents() {
    game.eventSource?.close();
    const source = new EventSource(API.events);
    game.eventSource = source;
    source.onopen = () => announce("실시간 사무실 링크가 연결됐습니다.");
    source.onmessage = () => scheduleRefresh();
    ["state", "run", "agent", "provider", "analysis", "review", "task", "work_item", "schedule", "decision", "committee", "minutes", "fault"].forEach((type) => {
      source.addEventListener(type, (event) => {
        try {
          const payload = JSON.parse(event.data || "{}");
          if (payload.provider) applyProvider(payload.provider);
          const incomingRunId = String(payload.run_id || payload.run?.run_id || "");
          if (
            type === "review"
            && game.discoveryRuns.some((run) => discoveryRunId(run) === incomingRunId)
          ) {
            void pollDiscoveryRuns(incomingRunId);
          }
          if (payload.run_id && !game.currentRunId) game.currentRunId = String(payload.run_id);
          scheduleRefresh();
          schedulePanelRefresh();
        } catch {
          scheduleRefresh();
          schedulePanelRefresh();
        }
      });
    });
    source.onerror = () => announce("실시간 링크 재연결 중입니다.", true);
  }

  function validateTicker() {
    const ticker = String(elements.tickerInput?.value || "").trim().toUpperCase();
    if (elements.tickerInput) elements.tickerInput.value = ticker;
    const valid = /^[A-Z0-9][A-Z0-9.\-]{0,14}$/.test(ticker);
    setText(elements.tickerError, valid ? "" : "영문·숫자·점·하이픈으로 종목 코드를 입력하세요.", "");
    elements.tickerInput?.setAttribute("aria-invalid", valid ? "false" : "true");
    return valid ? ticker : null;
  }

  async function submitAnalysis(event) {
    event.preventDefault();
    const ticker = validateTicker();
    if (!ticker || !elements.submitButton) return;
    const thesis = String(elements.thesisInput?.value || "").trim();
    elements.submitButton.disabled = true;
    announce(`${ticker} 분석을 투자팀에 배정합니다.`);
    try {
      const payload = await requestJson(API.analyze, {
        method: "POST",
        body: JSON.stringify(thesis ? { ticker, thesis } : { ticker }),
      }, 30_000);
      applyRun(payload);
      closeDialog();
      announce(`${ticker} 분석이 시작됐습니다. 각 연구실을 확인하세요.`);
      schedulePoll(800);
    } catch (error) {
      setText(elements.tickerError, error.message, "");
      announce(`분석 요청 실패. ${error.message}`, true);
    } finally {
      elements.submitButton.disabled = false;
    }
  }

  async function submitReview(decision) {
    if (!game.currentRunId || !reviewable()) return;
    const reviewedRunId = game.currentRunId;
    const reason = String(elements.reviewReason?.value || "").trim();
    if (reason.length < 4) {
      announce("검토 사유를 4자 이상 입력하세요.", true);
      elements.reviewReason?.focus();
      return;
    }
    const apiDecision = { approve: "approved", hold: "deferred", reject: "rejected" }[decision];
    if (!apiDecision) return;
    document.querySelectorAll("[data-review-decision]").forEach((button) => { button.disabled = true; });
    try {
      const payload = await requestJson(API.review(game.currentRunId), {
        method: "POST",
        body: JSON.stringify({ decision: apiDecision, reason }),
      });
      applyRun(payload);
      syncTrackedDiscoveryRun(reviewedRunId, game.run);
      openCommittee();
      announce(`사람의 ${apiDecision} 결정이 저널에 기록됐습니다.`);
    } catch (error) {
      announce(`검토 기록 실패. ${error.message}`, true);
      document.querySelectorAll("[data-review-decision]").forEach((button) => { button.disabled = !reviewable(); });
    }
  }

  function bindKeyboard() {
    window.addEventListener("keydown", (event) => {
      const key = event.key.toLowerCase();
      const target = event.target;
      const editing = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement;
      if (!editing && ["arrowleft", "arrowright", "arrowup", "arrowdown", "w", "a", "s", "d"].includes(key)) {
        event.preventDefault();
        if (!event.repeat) nudgePlayer(key);
        keys.add(key);
      }
      if (!editing && ["e", "enter"].includes(key) && !event.repeat) {
        event.preventDefault();
        interact();
      }
      if (key === "escape" && elements.dialog?.open) {
        event.preventDefault();
        closeDialog();
      }
    });
    window.addEventListener("keyup", (event) => keys.delete(event.key.toLowerCase()));
    window.addEventListener("blur", () => keys.clear());
  }

  function bindMobileControls() {
    document.querySelectorAll("[data-control]").forEach((button) => {
      const control = button.dataset.control;
      if (control === "interact") {
        button.addEventListener("click", () => interact());
        return;
      }
      const start = (event) => {
        event.preventDefault();
        nudgePlayer(control);
        mobileDirections.add(control);
        canvas.focus({ preventScroll: true });
      };
      const stop = () => mobileDirections.delete(control);
      button.addEventListener("pointerdown", start);
      button.addEventListener("pointerup", stop);
      button.addEventListener("pointercancel", stop);
      button.addEventListener("pointerleave", stop);
    });
  }

  function bindUi() {
    canvas.addEventListener("pointerdown", handleCanvasPointer);
    elements.analysisForm?.addEventListener("submit", submitAnalysis);
    elements.scheduleForm?.addEventListener("submit", submitSchedule);
    elements.scheduleList?.addEventListener("click", handleScheduleAction);
    elements.scheduleRefresh?.addEventListener("click", () => loadSchedules());
    elements.discoveryScreenForm?.addEventListener("submit", submitDiscoveryScreen);
    elements.discoveryAnalyzeForm?.addEventListener("submit", submitDiscoveryAnalysis);
    elements.discoveryCandidateList?.addEventListener("change", handleDiscoverySelection);
    elements.taskForm?.addEventListener("submit", submitAgentTask);
    elements.taskList?.addEventListener("click", handleTaskAction);
    elements.committeeStartForm?.addEventListener("submit", submitCommitteeStart);
    elements.committeeCommandForm?.addEventListener("submit", submitCommitteeCommand);
    elements.committeeFinish?.addEventListener("click", finishCommittee);
    elements.committeeStop?.addEventListener("click", stopCommittee);
    elements.decisionArchiveList?.addEventListener("click", loadDecisionDetail);
    elements.decisionArchiveRefresh?.addEventListener("click", () => loadDecisionArchive());
    elements.tickerInput?.addEventListener("input", () => {
      if (elements.tickerInput) elements.tickerInput.value = elements.tickerInput.value.toUpperCase();
      if (elements.tickerInput?.getAttribute("aria-invalid") === "true") validateTicker();
    });
    elements.scheduleTicker?.addEventListener("input", () => {
      if (elements.scheduleTicker) elements.scheduleTicker.value = elements.scheduleTicker.value.toUpperCase();
      elements.scheduleTicker?.setAttribute("aria-invalid", "false");
      setText(elements.scheduleError, "", "");
    });
    elements.scheduleTime?.addEventListener("input", () => {
      elements.scheduleTime?.setAttribute("aria-invalid", "false");
      setText(elements.scheduleError, "", "");
    });
    document.querySelectorAll("[data-dialog-close]").forEach((button) => button.addEventListener("click", closeDialog));
    document.querySelectorAll("[data-review-decision]").forEach((button) => {
      button.addEventListener("click", () => submitReview(button.dataset.reviewDecision));
    });
    elements.dialog?.addEventListener("click", (event) => {
      if (event.target === elements.dialog) closeDialog();
    });
    elements.dialog?.addEventListener("cancel", (event) => {
      event.preventDefault();
      closeDialog();
    });
    window.addEventListener("resize", setupCanvas);
    window.addEventListener("storage", syncDiscoveryRunsFromStorage);
    window.addEventListener("beforeunload", () => {
      savePlayer();
      game.eventSource?.close();
      stopPolling();
      stopCommitteePolling();
      stopDiscoveryPolling();
      if (game.panelRefreshTimer) window.clearTimeout(game.panelRefreshTimer);
    });
    document.addEventListener("visibilitychange", () => {
      game.running = !document.hidden;
      if (game.running) {
        game.lastFrame = 0;
        window.requestAnimationFrame(frame);
        refreshRun();
        refreshActivePanel();
        scheduleDiscoveryPolling(500);
      } else {
        savePlayer();
        stopCommitteePolling();
        stopDiscoveryPolling();
      }
    });
    reducedMotionQuery.addEventListener("change", (event) => { game.reducedMotion = event.matches; });
  }

  function debugState() {
    return Object.freeze({
      player: Object.freeze({ x: Math.round(player.x), y: Math.round(player.y), direction: player.direction }),
      camera: Object.freeze({
        x: Math.round(camera.x),
        y: Math.round(camera.y),
        width: Math.round(camera.width),
        height: Math.round(camera.height),
      }),
      zone: game.currentZone,
      nearestInteraction: game.nearestInteraction?.id || null,
      providerStatus: game.provider?.status || null,
      runId: game.currentRunId,
      runStatus: game.run?.status || null,
      ticker: game.run?.ticker || null,
      taskCount: game.tasks.length,
      scheduleCount: game.schedules.length,
      discoveryCandidateCount: game.discovery?.candidates?.length || 0,
      discoveryRunCount: game.discoveryRuns.length,
      committeeId: game.committeeId,
      committeeStatus: game.committee?.status || null,
      decisionArchiveCount: game.decisions.length,
      agents: Object.freeze(
        ROOMS.map((room) => Object.freeze({ role: room.role, status: agentStatus(room.role) })),
      ),
      error: game.error,
    });
  }

  Object.defineProperty(window, "__OFFICE_DEBUG__", {
    configurable: false,
    enumerable: false,
    writable: false,
    value: Object.freeze({
      getState: debugState,
      rooms: Object.freeze(ROOMS.map((room) => Object.freeze({ id: room.id, label: room.label, role: room.role }))),
      zones: Object.freeze([
        Object.freeze({ id: INTAKE.id, label: INTAKE.label, kind: "intake" }),
        ...ROOMS.map((room) => Object.freeze({ id: room.id, label: room.label, kind: room.committee ? "committee" : "agent" })),
      ]),
    }),
  });

  setupCanvas();
  bindKeyboard();
  bindMobileControls();
  bindUi();
  configureScheduleTime();
  setFormDisabled(elements.taskForm, true);
  setCommitteeControls(false);
  renderDiscoveryRuns(loadStoredDiscoveryRuns());
  scheduleDiscoveryPolling(500);
  updateWorld();
  loadInitialState();
  connectEvents();
  canvas.focus({ preventScroll: true });
  window.requestAnimationFrame(frame);
})();
