// 차트 분석팀의 서버 계산 보고서를 안전하고 일관된 화면 구성으로 표시한다.
import {
  asObject,
  clearElement,
  createElement,
} from "./site-common.js?v=5";

function chartText(value, fallback = "—") {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) {
    return value.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
  }
  if (typeof value === "boolean") return value ? "예" : "아니요";
  return fallback;
}

function chartList(value) {
  if (Array.isArray(value)) {
    return value.map((item) => {
      if (["string", "number"].includes(typeof item)) return chartText(item, "");
      const entry = asObject(item);
      return chartText(entry.summary || entry.detail || entry.reason || entry.label || entry.name, "");
    }).filter(Boolean);
  }
  if (typeof value === "string" && value.trim()) return [value.trim()];
  return [];
}

function chartStatus(status) {
  const key = String(status || "unknown").toLowerCase();
  const labels = {
    ready: "분석 준비",
    complete: "분석 완료",
    completed: "분석 완료",
    partial: "부분 분석",
    degraded: "자료 주의",
    unavailable: "자료 부족",
    blocked: "분석 차단",
    failed: "분석 실패",
    constructive: "건설적",
    mixed: "혼합 신호",
    defensive: "방어적",
    insufficient_data: "자료 부족",
  };
  return { key, label: labels[key] || chartText(status, "상태 미정") };
}

function chartScore(value) {
  const score = Number(value);
  if (!Number.isFinite(score)) return "—";
  return `${score.toFixed(1)} / 100`;
}

function chartConfidence(value) {
  const confidence = Number(value);
  if (!Number.isFinite(confidence)) return "—";
  return `${(confidence * 100).toFixed(0)}%`;
}

function chartObservations(chart) {
  const daily = Number(chart.observations);
  const weekly = Number(chart.weekly_observations);
  const values = [];
  if (Number.isFinite(daily)) values.push(`일봉 ${daily}개`);
  if (Number.isFinite(weekly)) values.push(`완료 주봉 ${weekly}개`);
  return values.join(" · ") || "—";
}

function normalizeLensEntries(chart) {
  const source = chart.lens_verdicts || chart.lenses || chart.lens_results;
  if (Array.isArray(source)) {
    return source.map((item, index) => ({ key: String(index + 1), ...asObject(item) }));
  }
  return Object.entries(asObject(source)).map(([key, value]) => {
    if (typeof value === "string") return { key, verdict: value };
    return { key, ...asObject(value) };
  });
}

function normalizeLevelEntries(chart) {
  const entries = [];
  Object.entries(asObject(chart.levels)).forEach(([kind, value]) => {
    const values = Array.isArray(value) ? value : [value];
    values.forEach((item) => {
      entries.push(
        typeof item === "object" && item !== null
          ? { kind, ...asObject(item) }
          : { kind, value: item },
      );
    });
  });
  [
    ["support", chart.support_levels],
    ["resistance", chart.resistance_levels],
    ["trigger", chart.trigger_level],
    ["invalidation", chart.invalidation_levels || chart.invalidation_level],
  ].forEach(([kind, value]) => {
    if (value === undefined || value === null) return;
    const values = Array.isArray(value) ? value : [value];
    values.forEach((item) => entries.push(
      typeof item === "object" && item !== null
        ? { kind, ...asObject(item) }
        : { kind, value: item },
    ));
  });
  return entries;
}

function setupSummary(chart) {
  if (typeof chart.setup === "string") return chart.setup;
  const setup = asObject(chart.setup);
  return chartText(
    setup.label
      || setup.type
      || setup.name
      || chart.setup_mode
      || chart.setup_type
      || chart.primary_setup,
    "관찰형",
  );
}

function chartSetupLabel(value) {
  return {
    breakout: "돌파형",
    pullback: "눌림목형",
    separate_signals: "돌파·눌림목 분리",
    none: "유효 설정 없음",
    insufficient_data: "자료 부족",
  }[String(value || "").toLowerCase()] || chartText(value, "관찰형");
}

function chartVerdictLabel(value) {
  return {
    bullish: "상승",
    neutral: "중립",
    bearish: "하락",
    insufficient_data: "자료 부족",
  }[String(value || "").toLowerCase()] || chartText(value, "중립");
}

function chartAlignmentLabel(value) {
  if (typeof value === "string") return chartText(value, "미정");
  const alignment = asObject(value);
  const states = [
    ["일봉", alignment.daily_trend],
    ["주봉", alignment.weekly_trend],
    ["가격·거래량", alignment.price_volume_state],
  ].filter(([, state]) => typeof state === "string" && state.trim());
  const counts = [
    ["상승", alignment.bullish_lenses],
    ["중립", alignment.neutral_lenses],
    ["하락", alignment.bearish_lenses],
    ["부족", alignment.insufficient_lenses],
  ].filter(([, count]) => Number.isFinite(Number(count)));
  const stateSummary = states.map(([label, state]) => `${label} ${chartVerdictLabel(state)}`).join(" · ");
  const countSummary = counts.map(([label, count]) => `${label} ${count}`).join(" · ");
  if (stateSummary || countSummary) return [stateSummary, countSummary].filter(Boolean).join(" / ");
  return chartText(alignment.summary || alignment.state, "미정");
}

function appendChartListSection(parent, title, values, tone = "neutral") {
  const items = chartList(values);
  if (!items.length) return;
  const section = createElement("section", "chart-desk__signal-group");
  section.dataset.tone = tone;
  section.append(createElement("h5", "", title));
  const list = createElement("ul", "chart-desk__signal-list");
  items.slice(0, 8).forEach((item) => list.append(createElement("li", "", item)));
  section.append(list);
  parent.append(section);
}

function appendLensMetrics(card, lens) {
  const metrics = Array.isArray(lens.metrics) ? lens.metrics : [];
  if (!metrics.length) return;
  const list = createElement("dl", "chart-desk__lens-metrics");
  metrics.slice(0, 8).forEach((rawMetric) => {
    const metric = asObject(rawMetric);
    const item = createElement("div");
    item.append(
      createElement("dt", "", chartText(metric.name, "지표")),
      createElement("dd", "", `${chartText(metric.value)}${metric.unit ? ` ${metric.unit}` : ""}`),
    );
    list.append(item);
  });
  card.append(list);
}

export function renderChartDesk(target, rawChart, { title = "차트 분석 데스크", compact = false } = {}) {
  if (!target) return false;
  const chart = asObject(rawChart);
  const hasChart = Object.keys(chart).length > 0;
  clearElement(target);
  target.hidden = !hasChart;
  if (!hasChart) return false;

  target.classList.add("chart-desk");
  target.classList.toggle("chart-desk--compact", compact);
  target.setAttribute("role", "region");
  if (!target.hasAttribute("aria-label") && !target.hasAttribute("aria-labelledby")) {
    target.setAttribute("aria-label", title);
  }
  const status = chartStatus(chart.status || chart.state);
  target.dataset.status = status.key;

  const header = createElement("header", "chart-desk__header");
  const heading = createElement("div");
  heading.append(createElement("span", "chart-desk__eyebrow", "CHART DESK // TECHNICAL"));
  heading.append(createElement("h4", "", title));
  if (chart.methodology_version) {
    heading.append(createElement("small", "chart-desk__version", chart.methodology_version));
  }
  const statusBadge = createElement("span", "chart-desk__status", status.label);
  statusBadge.dataset.status = status.key;
  header.append(heading, statusBadge);

  const metrics = createElement("dl", "chart-desk__metrics");
  [
    ["가격 기준일", chartText(chart.as_of_date)],
    ["분석 표본", chartObservations(chart)],
    ["점수", chartScore(chart.score ?? chart.composite_score)],
    ["신뢰도", chartConfidence(chart.confidence)],
    ["렌즈 정렬", chartAlignmentLabel(chart.alignment || chart.lens_alignment || chart.sorting)],
    ["우선 설정", chartSetupLabel(setupSummary(chart))],
  ].forEach(([label, value]) => {
    const item = createElement("div");
    item.append(createElement("dt", "", label), createElement("dd", "", value));
    metrics.append(item);
  });
  target.append(header, metrics);

  const lenses = normalizeLensEntries(chart);
  if (lenses.length) {
    const section = createElement("section", "chart-desk__section");
    section.append(createElement("h5", "", "렌즈별 독립 판정"));
    const grid = createElement("div", "chart-desk__lens-grid");
    lenses.forEach((lens) => {
      const card = createElement("article", "chart-desk__lens");
      const lensHead = createElement("div", "chart-desk__lens-head");
      lensHead.append(
        createElement("strong", "", chartText(lens.title || lens.label || lens.name || lens.key, "렌즈")),
        createElement("span", "", chartVerdictLabel(lens.verdict || lens.state || lens.status || lens.signal)),
      );
      card.append(lensHead);
      card.append(createElement("p", "", chartText(lens.summary || lens.detail || lens.reason, "근거 설명이 없습니다.")));
      const telemetry = [
        Number.isFinite(Number(lens.score)) ? chartScore(lens.score) : "",
        Number.isFinite(Number(lens.confidence)) ? `신뢰도 ${chartConfidence(lens.confidence)}` : "",
      ].filter(Boolean).join(" · ");
      if (telemetry) card.append(createElement("small", "", telemetry));
      appendLensMetrics(card, lens);
      if (lens.adaptation_notice) {
        card.append(createElement("p", "chart-desk__adaptation", `적응 한계. ${lens.adaptation_notice}`));
      }
      grid.append(card);
    });
    section.append(grid);
    target.append(section);
  }

  const levels = normalizeLevelEntries(chart);
  if (levels.length) {
    const section = createElement("section", "chart-desk__section");
    section.append(createElement("h5", "", "가격 레벨"));
    const list = createElement("ul", "chart-desk__levels");
    levels.slice(0, 12).forEach((level) => {
      const item = createElement("li");
      item.append(
        createElement("span", "", chartText(level.label || level.kind, "레벨")),
        createElement("strong", "mono", chartText(level.price ?? level.value, "—")),
      );
      const sources = chartList(level.source_lenses).join(", ");
      const note = [
        chartText(level.note || level.reason || level.strength || level.timeframe, ""),
        sources ? `근거 ${sources}` : "",
      ].filter(Boolean).join(" · ");
      if (note) item.append(createElement("small", "", note));
      list.append(item);
    });
    section.append(list);
    target.append(section);
  }

  const signalGrid = createElement("div", "chart-desk__signals");
  appendChartListSection(signalGrid, "확인", chart.confirmations || chart.confirmed_signals, "confirm");
  appendChartListSection(signalGrid, "모순", chart.contradictions || chart.conflicts, "conflict");
  appendChartListSection(signalGrid, "데이터 공백", chart.data_gaps || chart.gaps, "gap");
  if (signalGrid.children.length) target.append(signalGrid);
  return true;
}
