// 시장 관제 페이지에서 공통 거시지표와 시장 국면, 공급원 준비 상태를 표시한다.
import {
  API,
  asArray,
  asObject,
  clearElement,
  createElement,
  formatDateTime,
  initSiteShell,
  requestJson,
  setText,
} from "./site-common.js?v=1";

const elements = {
  generatedAt: document.querySelector("#markets-generated-at"),
  overallStatus: document.querySelector("#markets-overall-status"),
  refresh: document.querySelector("#markets-refresh"),
  feedback: document.querySelector("#markets-feedback"),
  commonStatus: document.querySelector("#common-macro-status"),
  commonList: document.querySelector("#common-macro-list"),
  commonSummary: document.querySelector("#common-macro-summary"),
  commonWarnings: document.querySelector("#common-macro-warnings"),
  sourcesReady: document.querySelector("#sources-ready"),
  sourcesBlocked: document.querySelector("#sources-blocked"),
  sourcesTotal: document.querySelector("#sources-total"),
  sourceBody: document.querySelector("#source-table-body"),
  sourceFilters: Array.from(document.querySelectorAll("[data-source-filter]")),
  live: document.querySelector("#site-live-region"),
};

const state = {
  sources: [],
  sourceFilter: "all",
  loading: false,
};

const REGIME_AXES = Object.freeze([
  ["rates", "금리", "RATES"],
  ["currency", "환율", "CURRENCY"],
  ["volatility", "변동성", "VOLATILITY"],
  ["commodities", "원자재", "COMMODITIES"],
  ["liquidity", "유동성", "LIQUIDITY"],
]);

const REGIME_LABELS = Object.freeze({
  favorable: "우호",
  neutral: "중립",
  adverse: "비우호",
  unknown: "미확인",
});

const SECTION_LABELS = Object.freeze({
  complete: "완료",
  partial: "부분 수집",
  unavailable: "수집 불가",
  blocked: "차단",
  degraded: "저하",
});

const DOMAIN_LABELS = Object.freeze({
  price: "가격",
  macro: "거시",
  financials: "재무",
  disclosure: "공시",
  news: "뉴스",
});

const TRUST_LABELS = Object.freeze({ high: "높음", medium: "보통", low: "낮음" });

const FRESHNESS_LABELS = Object.freeze({
  real_time_or_delayed: "실시간·지연",
  near_real_time: "준실시간",
  intraday: "장중",
  end_of_day: "장마감",
  next_business_day: "익영업일",
  release_schedule: "발표 일정",
  twice_daily: "일 2회",
});

function firstDefined(...values) {
  return values.find((value) => value !== undefined && value !== null && value !== "");
}

function arrayOfText(value) {
  return asArray(value).map((item) => String(item || "").trim()).filter(Boolean);
}

function setFeedback(message, tone = "neutral") {
  setText(elements.feedback, message, "");
  if (elements.feedback) elements.feedback.dataset.tone = tone;
  setText(elements.live, message, "");
}

function formatReading(value) {
  if (typeof value === "boolean") return value ? "예" : "아니요";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value ?? "—");
  const absolute = Math.abs(number);
  const options = absolute >= 10_000
    ? { maximumFractionDigits: 0 }
    : absolute >= 100
      ? { maximumFractionDigits: 1 }
      : { maximumFractionDigits: 2 };
  return new Intl.NumberFormat("ko-KR", options).format(number);
}

function unitLabel(unit, currency) {
  const labels = {
    percent: "%",
    percentage_point: "%p",
    index_point: "pt",
    usd_per_barrel: "USD/bbl",
    usd_per_bitcoin: "USD/BTC",
    krw_per_usd: "KRW/USD",
    million_usd: "백만 USD",
    billion_usd: "십억 USD",
    index_1982_1984_100: "1982–84=100",
    index_2017_100: "2017=100",
    index_2020_100: "2020=100",
  };
  return labels[unit] || currency || String(unit || "");
}

function renderMacro(common) {
  const facts = asArray(common.facts);
  const isChange = (fact) => /:change_\d+d$/.test(String(fact?.fact_id || ""));
  const currentFacts = facts.filter((fact) => !isChange(fact));
  const changes = new Map(
    facts
      .filter(isChange)
      .map((fact) => [String(fact.metric || "").replace(/ (?:\d+일|\d+개월) 변화$/, ""), fact]),
  );

  clearElement(elements.commonList);
  if (!currentFacts.length) {
    elements.commonList?.append(createElement("li", "macro-cell macro-cell--loading", "표시할 공통 거시 사실이 없습니다."));
  } else {
    currentFacts.forEach((fact) => {
      const item = createElement("li", "macro-cell");
      item.append(createElement("strong", "macro-cell__label", fact.metric || fact.fact_id || "지표"));
      const reading = createElement("div", "macro-cell__reading");
      reading.append(createElement("span", "macro-cell__value", formatReading(fact.value)));
      reading.append(createElement("span", "macro-cell__unit", unitLabel(fact.unit, fact.currency)));
      item.append(reading);
      const change = changes.get(String(fact.metric || ""));
      if (change) {
        const changeNumber = Number(change.value);
        const direction = Number.isFinite(changeNumber) && changeNumber > 0
          ? "up"
          : Number.isFinite(changeNumber) && changeNumber < 0
            ? "down"
            : "flat";
        const prefix = changeNumber > 0 ? "+" : "";
        const directionMark = direction === "up" ? "↑" : direction === "down" ? "↓" : "→";
        const horizon = String(change.metric || "변화").match(/((?:\d+일|\d+개월) 변화)$/)?.[1] || "변화";
        const changeText = `${horizon} ${directionMark} ${prefix}${formatReading(change.value)} ${unitLabel(change.unit, change.currency)}`.trim();
        const changeElement = createElement("p", "macro-cell__change", changeText);
        changeElement.dataset.direction = direction;
        item.append(changeElement);
      } else {
        item.append(createElement("p", "macro-cell__change", "변화 자료 미수집"));
      }
      if (fact.observed_at) item.title = `관측 시각 ${formatDateTime(fact.observed_at)}`;
      elements.commonList?.append(item);
    });
  }

  const status = String(common.status || "unknown").toLowerCase();
  setText(elements.commonStatus, SECTION_LABELS[status] || status || "미확인");
  const sections = asArray(common.sections);
  const completed = sections.filter((section) => section?.status === "complete").length;
  setText(
    elements.commonSummary,
    sections.length
      ? `거시 구역 ${sections.length}개 중 ${completed}개가 완성됐습니다. 지표 수집 시각과 시장별 판정 시각은 다를 수 있습니다.`
      : "금리, 달러, 원화 환율, 변동성, 원유와 위험 선호를 함께 확인합니다.",
  );

  const warnings = [
    ...arrayOfText(common.warnings),
    ...sections.flatMap((section) => [
      ...arrayOfText(section?.data_gaps),
      ...arrayOfText(section?.blocking_reasons),
    ]),
  ];
  clearElement(elements.commonWarnings);
  [...new Set(warnings)].slice(0, 6).forEach((warning) => {
    elements.commonWarnings?.append(createElement("li", "", warning));
  });
}

function renderRegime(marketId, regime) {
  const container = document.querySelector(`#market-${marketId}-regime`);
  clearElement(container);
  REGIME_AXES.forEach(([key, label, code]) => {
    const stateValue = String(regime?.[key] || "unknown").toLowerCase();
    const item = createElement("li", "regime-axis");
    item.dataset.state = Object.hasOwn(REGIME_LABELS, stateValue) ? stateValue : "unknown";
    item.append(createElement("strong", "", label));
    item.append(createElement("small", "", `${code} / ${REGIME_LABELS[stateValue] || "미확인"}`));
    container?.append(item);
  });
}

function renderQuality(marketId, quality, warnings) {
  const rail = document.querySelector(`#market-${marketId}-quality`);
  const badge = document.querySelector(`#market-${marketId}-quality-badge`);
  const eligible = quality?.analysis_eligible === true;
  const hasReport = typeof quality?.analysis_eligible === "boolean";
  const qualityState = !hasReport ? "unknown" : eligible ? "ready" : "blocked";
  if (rail) rail.dataset.state = qualityState;
  if (badge) badge.dataset.state = qualityState;
  setText(badge, !hasReport ? "판정 대기" : eligible ? "분석 자료 충족" : "분석 자료 차단");

  const title = rail?.querySelector("strong");
  setText(
    title,
    !hasReport
      ? "자료 품질 보고서가 없습니다."
      : eligible
        ? "필수 자료가 분석 기준을 충족했습니다."
        : "필수 자료 공백으로 매수 판단을 차단합니다.",
  );
  const list = rail?.querySelector("ul");
  clearElement(list);
  const issues = [
    ...arrayOfText(quality?.blocking_reasons),
    ...arrayOfText(quality?.warnings),
    ...arrayOfText(warnings),
  ];
  if (!issues.length) issues.push(eligible ? "신선도와 필수 구역 검증을 통과했습니다." : "세부 차단 사유가 아직 제공되지 않았습니다.");
  [...new Set(issues)].slice(0, 5).forEach((issue) => list?.append(createElement("li", "", issue)));
}

function renderMarket(marketId, market) {
  const confidence = Number(market.confidence);
  const multiplier = Number(market.position_cap_multiplier);
  setText(
    document.querySelector(`#market-${marketId}-confidence`),
    Number.isFinite(confidence) ? `${Math.round((confidence <= 1 ? confidence * 100 : confidence))}%` : "—",
  );
  setText(
    document.querySelector(`#market-${marketId}-cap`),
    Number.isFinite(multiplier) ? `${multiplier.toFixed(2)}×` : "—",
  );
  renderRegime(marketId, asObject(market.regime));
  renderQuality(marketId, asObject(market.data_quality), market.warnings);
}

function renderOverview(payload) {
  const common = asObject(payload.common);
  const markets = asObject(payload.markets);
  renderMacro(common);
  renderMarket("us", asObject(markets.us));
  renderMarket("kr", asObject(markets.kr));

  const generatedAt = firstDefined(payload.generated_at, common.generated_at);
  setText(elements.generatedAt, generatedAt ? formatDateTime(generatedAt) : "생성 시각 없음");
  if (elements.generatedAt) elements.generatedAt.dateTime = String(generatedAt || "");

  const reports = [asObject(markets.us?.data_quality), asObject(markets.kr?.data_quality)];
  const eligibleCount = reports.filter((quality) => quality.analysis_eligible === true).length;
  const knownCount = reports.filter((quality) => typeof quality.analysis_eligible === "boolean").length;
  const overallLabel = knownCount < 2
    ? "일부 판정 미수집"
    : eligibleCount === 2
      ? "양 시장 자료 충족"
      : eligibleCount === 0
        ? "양 시장 판단 차단"
        : "일부 시장 판단 차단";
  setText(elements.overallStatus, overallLabel);
  if (elements.overallStatus) elements.overallStatus.dataset.tone = eligibleCount === 2 ? "complete" : knownCount ? "failed" : "idle";
}

function sourceMatchesFilter(item) {
  if (state.sourceFilter === "all") return true;
  return arrayOfText(item?.policy?.markets).includes(state.sourceFilter);
}

function safeHomepage(value) {
  try {
    const url = new URL(String(value || ""));
    return url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function appendTags(container, values, labels = {}) {
  arrayOfText(values).forEach((value) => {
    container.append(createElement("span", "source-tag", labels[value] || value));
  });
}

function renderSources() {
  const ready = state.sources.filter((item) => item?.status?.analysis_ready === true).length;
  setText(elements.sourcesReady, ready);
  setText(elements.sourcesBlocked, state.sources.length - ready);
  setText(elements.sourcesTotal, state.sources.length);
  clearElement(elements.sourceBody);

  const visible = state.sources.filter(sourceMatchesFilter);
  if (!visible.length) {
    const row = document.createElement("tr");
    const cell = createElement("td", "source-table__empty", "선택한 시장에 등록된 공급원이 없습니다.");
    cell.colSpan = 5;
    row.append(cell);
    elements.sourceBody?.append(row);
    return;
  }

  visible.forEach((item) => {
    const policy = asObject(item.policy);
    const status = asObject(item.status);
    const row = document.createElement("tr");
    const sourceCell = document.createElement("td");
    const sourceName = createElement("div", "source-name");
    sourceName.append(createElement("strong", "", policy.name || policy.id || "공급원"));
    const homepage = safeHomepage(policy.homepage_url);
    if (homepage) {
      const link = createElement("a", "", "공식 페이지 ↗");
      link.href = homepage;
      link.target = "_blank";
      link.rel = "noreferrer";
      sourceName.append(link);
    }
    sourceCell.append(sourceName);

    const scopeCell = document.createElement("td");
    const scopes = createElement("div", "source-tags");
    appendTags(scopes, policy.markets, { us: "미국", kr: "한국" });
    appendTags(scopes, policy.domains, DOMAIN_LABELS);
    scopeCell.append(scopes);

    const trustCell = document.createElement("td");
    const trustTags = createElement("div", "source-tags");
    appendTags(trustTags, [policy.trust_level], TRUST_LABELS);
    appendTags(trustTags, [policy.freshness], FRESHNESS_LABELS);
    trustCell.append(trustTags);

    const readyCell = document.createElement("td");
    const readyMark = createElement("span", "source-ready", status.analysis_ready === true ? "준비 완료" : "준비 필요");
    readyMark.dataset.ready = String(status.analysis_ready === true);
    readyCell.append(readyMark);

    const issueCell = createElement("td", "source-issues");
    const issues = [
      ...arrayOfText(status.errors),
      ...arrayOfText(status.warnings),
      ...arrayOfText(status.missing_key_env_vars).map((key) => `환경 변수 ${key} 필요`),
    ];
    issueCell.textContent = issues[0] || policy.freshness_note || "추가 확인 사항 없음";
    if (issues.length > 1) issueCell.title = issues.join("\n");
    row.append(sourceCell, scopeCell, trustCell, readyCell, issueCell);
    elements.sourceBody?.append(row);
  });
}

function renderSourcePayload(payload) {
  state.sources = asArray(payload.sources);
  renderSources();
}

async function loadMarkets() {
  if (state.loading) return;
  state.loading = true;
  if (elements.refresh) elements.refresh.disabled = true;
  setFeedback("공통 거시지표와 공급원 정책을 다시 조립하고 있습니다.");
  const [overviewResult, sourceResult] = await Promise.allSettled([
    requestJson(API.marketOverview),
    requestJson(API.dataSources),
  ]);
  const errors = [];
  if (overviewResult.status === "fulfilled") renderOverview(asObject(overviewResult.value));
  else errors.push(`시장 국면 조회 실패. ${overviewResult.reason?.message || "알 수 없는 오류"}`);
  if (sourceResult.status === "fulfilled") renderSourcePayload(asObject(sourceResult.value));
  else errors.push(`공급원 상태 조회 실패. ${sourceResult.reason?.message || "알 수 없는 오류"}`);

  if (errors.length) setFeedback(errors.join(" "), "error");
  else setFeedback("시장 국면과 데이터 공급원 상태를 최신 기준으로 표시했습니다.", "success");
  state.loading = false;
  if (elements.refresh) elements.refresh.disabled = false;
}

elements.refresh?.addEventListener("click", loadMarkets);
elements.sourceFilters.forEach((button) => {
  button.addEventListener("click", () => {
    state.sourceFilter = button.dataset.sourceFilter || "all";
    elements.sourceFilters.forEach((candidate) => {
      const active = candidate === button;
      candidate.classList.toggle("is-active", active);
      candidate.setAttribute("aria-pressed", String(active));
    });
    renderSources();
  });
});

await initSiteShell();
await loadMarkets();
