// 전역 작업 피드백의 상태 전환과 버튼 복구를 실제 자바스크립트로 검증한다.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

class FakeClassList {
  constructor() {
    this.values = new Set();
  }

  add(...values) {
    values.forEach((value) => this.values.add(value));
  }

  remove(...values) {
    values.forEach((value) => this.values.delete(value));
  }

  contains(value) {
    return this.values.has(value);
  }
}

class FakeElement {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.attributes = new Map();
    this.children = [];
    this.classList = new FakeClassList();
    this.className = "";
    this.dataset = {};
    this.disabled = false;
    this.hidden = false;
    this.textContent = "";
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  addEventListener() {}

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = [...children];
  }

  querySelector(selector) {
    if (selector === "[data-button-label]") {
      return this.children.find((child) => child?.dataset?.buttonLabel !== undefined) || null;
    }
    if (selector === "span") {
      return this.children.find((child) => child?.tagName === "SPAN") || null;
    }
    return null;
  }
}

class FakeButton extends FakeElement {
  constructor() {
    super("button");
  }
}

globalThis.HTMLElement = FakeElement;
globalThis.HTMLButtonElement = FakeButton;

const storedValues = new Map();
globalThis.window = {
  sessionStorage: {
    getItem: (key) => storedValues.get(key) ?? null,
    setItem: (key, value) => storedValues.set(key, value),
  },
  setInterval: () => 1,
  clearInterval: () => {},
  setTimeout,
  clearTimeout,
};

const selectors = new Map();
const register = (selector, element = new FakeElement()) => {
  selectors.set(selector, element);
  return element;
};

const monitor = register("#site-operation-monitor");
register("#site-operation-title");
register("#site-operation-detail");
register("#site-operation-event");
register("#site-operation-status");
register("#site-operation-elapsed", new FakeElement("time"));
const toggle = register("#site-operation-toggle", new FakeButton());
toggle.setAttribute("aria-expanded", "false");
const history = register("#site-operation-history");
history.hidden = true;
const list = register("#site-operation-list", new FakeElement("ol"));
register("#site-operation-count");
register("#site-live-region");

globalThis.document = {
  querySelector: (selector) => selectors.get(selector) || null,
  createElement: (tagName) => tagName === "button" ? new FakeButton() : new FakeElement(tagName),
};

const source = await readFile(new URL("../src/investment_office/static/site-common.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const feedback = await import(moduleUrl);

const failedOutcome = feedback.classifyDiscoveryOutcome({
  universe_size: 30,
  evaluated_count: 0,
  candidates: [],
  excluded: [{ eod: null, reasons: ["가격 공급자 인증이 필요합니다."] }],
});
assert.equal(failedOutcome.state, "failed");
assert.match(failedOutcome.message, /실제 평가는 0건/);

const partialOutcome = feedback.classifyDiscoveryOutcome({
  universe_size: 3,
  evaluated_count: 1,
  candidates: [{ ticker: "OK" }],
  excluded: [
    { eod: null, reasons: ["가격 조회 실패"] },
    { eod: { observations: 20 }, reasons: ["거래 이력 부족"] },
  ],
});
assert.equal(partialOutcome.state, "warning");
assert.match(partialOutcome.message, /2개는 평가할 자료가 부족/);
assert.match(partialOutcome.message, /가격 조회 실패는 1개/);

const successfulOutcome = feedback.classifyDiscoveryOutcome({
  universe_size: 2,
  evaluated_count: 2,
  candidates: [],
  excluded: [],
});
assert.equal(successfulOutcome.state, "success");
assert.match(successfulOutcome.message, /기준을 충족한 후보는 없습니다/);

assert.equal(
  feedback.formatApiErrorMessage({ detail: [{ loc: ["body", "ticker"], msg: "Field required" }] }, 422),
  "종목 코드: 필수 입력값입니다.",
);
assert.equal(
  feedback.formatApiErrorMessage("Internal Server Error", 500),
  "서버 내부 오류가 발생했습니다. 서버 로그를 확인하세요.",
);

const operation = feedback.startSiteOperation({
  title: "후보 스캔",
  detail: "30종목을 조회하고 있습니다.",
});
assert.equal(monitor.dataset.state, "running");
assert.equal(monitor.getAttribute("aria-busy"), "true");
assert.equal(selectors.get("#site-operation-title").textContent, "후보 스캔");
operation.succeed("후보 스캔을 완료했습니다.");
assert.equal(monitor.dataset.state, "success");
assert.equal(monitor.getAttribute("aria-busy"), "false");
assert.equal(selectors.get("#site-operation-status").textContent, "완료");
assert.equal(list.children.length, 1);

const recoveredCount = feedback.recoverActiveScheduledOperations({
  schedules: [{ analysis_run_id: "scheduled-run-1", status: "dispatched", ticker: "AAPL" }],
});
assert.equal(recoveredCount, 1);
assert.equal(monitor.dataset.state, "running");
assert.equal(selectors.get("#site-operation-title").textContent, "AAPL 예약 분석 실행");
assert.match(selectors.get("#site-operation-detail").textContent, /진행 상태 추적/);
assert.equal(feedback.recoverActiveScheduledOperations({
  schedules: [{ analysis_run_id: "scheduled-run-1", status: "dispatched", ticker: "AAPL" }],
}), 0);

const button = new FakeButton();
const buttonLabel = new FakeElement("span");
buttonLabel.textContent = "실행";
button.append(buttonLabel);
feedback.setButtonBusy(button, true, "처리 중");
assert.equal(button.disabled, true);
assert.equal(button.getAttribute("aria-busy"), "true");
assert.equal(buttonLabel.textContent, "처리 중");
feedback.setButtonBusy(button, false);
assert.equal(button.disabled, false);
assert.equal(button.getAttribute("aria-busy"), null);
assert.equal(buttonLabel.textContent, "실행");

console.log("전역 작업 피드백 자바스크립트 실행 검증 통과");
