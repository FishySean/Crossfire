const el = (id) => document.getElementById(id);
const SVG_NS = "http://www.w3.org/2000/svg";

const STRINGS = {
  en: {
    tagline: "verification results viewer",
    runLabel: "History",
    questionLabel: "Question",
    runButton: "Run",
    runningButton: "Running…",
    modeCached: "Cached",
    modeLive: "Live",
    stageConnecting: "Connecting…",
    stageFetching: (done, total) => `Fetching sources ${done}/${total}`,
    stageExtracting: (done, total) => `Extracting claims ${done}/${total}`,
    stageComparing: (done, total) => `Comparing ${done}/${total}`,
    stageJudging: "Weighing the sources…",
    stageDone: "Run complete",
    pairProgress: (done, total) => `comparing ${done}/${total}`,
    pendingSource: "waiting",
    fetchedChars: (n) => `${n.toLocaleString()} chars`,
    thinking: "Reading the evidence…",
    stallWarning: "No events for 15s — the live run may be stuck.",
    switchToCached: "Switch to cached",
    streamFailed: "The live stream dropped. Switch to cached mode for the demo.",
    stepError: (step, detail) => `${step} — ${detail}`,
    noQuestions: "No questions found in questions/demo.yaml.",
    question: "Question",
    noQuestion: "(no question recorded)",
    sources: "Sources",
    sourceCount: (n) => `${n} sources`,
    conflicts: "Conflicts",
    conflictCount: (n) => (n === 1 ? "1 conflict" : `${n} conflicts`),
    verdict: "Verdict",
    claim: "Claim",
    evidence: "Evidence",
    fetchFailed: "Fetch failed",
    noClaim: "This source makes no claim about the question",
    published: (date) => `Published ${date}`,
    unknown: "unknown",
    sourceConfidence: (pct) => `Source confidence ${pct}%`,
    conflictWith: (id) => `conflicts with ${id}`,
    noNature: "(difference not described)",
    noConflicts: "No contradictions found — no source contradicts another",
    partialConflicts: (n) =>
      `No contradictions found, but ${n} pairwise comparison(s) failed, so the check is incomplete`,
    noVerdict: "(this run produced no verdict)",
    reasoning: "Reasoning",
    recordedConflicts: "Disagreements recorded in the verdict",
    trusted: "Trusted sources",
    noTrusted: "No trusted sources recorded",
    confidence: "Confidence",
    startedAt: (v) => `Started ${v}`,
    elapsed: (v) => `Took ${v}s`,
    fetched: (v) => `Fetched ${v}`,
    fetchFailedCount: (v) => `Failed ${v}`,
    failureHead: (n) => `${n} call(s) failed in this run — the results may be incomplete.`,
    parseFailure: (stage, target) => `${stage} — ${target} — model response was not valid JSON`,
    stageExtract: "extract",
    stagePair: "pair",
    stageJudge: "judge",
    emptyRuns: "No JSON result files found under out/runs/.",
    loadFailed: (name, msg) => `Failed to load ${name}: ${msg}`,
    listFailed: (msg) => `Failed to load the run list: ${msg}`,
  },
  zh: {
    tagline: "查证结果查看器",
    runLabel: "历史结果",
    questionLabel: "问题",
    runButton: "开始查证",
    runningButton: "运行中…",
    modeCached: "回放",
    modeLive: "实时",
    stageConnecting: "连接中…",
    stageFetching: (done, total) => `抓取来源 ${done}/${total}`,
    stageExtracting: (done, total) => `提取主张 ${done}/${total}`,
    stageComparing: (done, total) => `比对中 ${done}/${total}`,
    stageJudging: "正在权衡各来源…",
    stageDone: "本次运行完成",
    pairProgress: (done, total) => `比对中 ${done}/${total}`,
    pendingSource: "等待中",
    fetchedChars: (n) => `${n.toLocaleString()} 字符`,
    thinking: "正在阅读证据…",
    stallWarning: "已有 15 秒没有收到任何事件，实时运行可能卡住了。",
    switchToCached: "切换到回放",
    streamFailed: "实时事件流中断了，演示请切到回放模式。",
    stepError: (step, detail) => `${step} — ${detail}`,
    noQuestions: "questions/demo.yaml 里没有找到任何问题。",
    question: "问题",
    noQuestion: "（无问题原文）",
    sources: "来源",
    sourceCount: (n) => `${n} 个来源`,
    conflicts: "冲突",
    conflictCount: (n) => `${n} 处矛盾`,
    verdict: "结论",
    claim: "主张",
    evidence: "证据原文",
    fetchFailed: "抓取失败",
    noClaim: "该来源未就此问题给出主张",
    published: (date) => `发布日期 ${date}`,
    unknown: "unknown",
    sourceConfidence: (pct) => `来源置信度 ${pct}%`,
    conflictWith: (id) => `矛盾于 ${id}`,
    noNature: "（未说明差异所在）",
    noConflicts: "未发现矛盾 — 各来源之间没有互相抵触的主张",
    partialConflicts: (n) => `未发现矛盾，但有 ${n} 次两两比对失败，本次检查并不完整`,
    noVerdict: "（本次运行没有给出结论）",
    reasoning: "判断理由",
    recordedConflicts: "结论中记录的分歧",
    trusted: "采信来源",
    noTrusted: "未记录采信来源",
    confidence: "置信度",
    startedAt: (v) => `开始于 ${v}`,
    elapsed: (v) => `耗时 ${v}s`,
    fetched: (v) => `抓取成功 ${v}`,
    fetchFailedCount: (v) => `抓取失败 ${v}`,
    failureHead: (n) => `本次运行有 ${n} 次调用失败，结果可能不完整。`,
    parseFailure: (stage, target) => `${stage} — ${target} — 模型返回不是合法 JSON`,
    stageExtract: "提取",
    stagePair: "比对",
    stageJudge: "裁决",
    emptyRuns: "out/runs/ 下没有找到任何 JSON 结果文件。",
    loadFailed: (name, msg) => `读取 ${name} 失败：${msg}`,
    listFailed: (msg) => `加载运行列表失败：${msg}`,
  },
};

let lang = localStorage.getItem("crossfire-lang") === "zh" ? "zh" : "en";
let currentRun = null;
let currentError = null;
let requestId = 0;

const t = (key, ...args) => {
  const value = STRINGS[lang][key];
  return typeof value === "function" ? value(...args) : value;
};

function applyStaticStrings() {
  document.documentElement.lang = lang === "zh" ? "zh" : "en";
  el("tagline").textContent = t("tagline");
  el("run-label").textContent = t("runLabel");
  el("question-label").textContent = t("questionLabel");
  el("run-button").textContent = live.active ? t("runningButton") : t("runButton");
  for (const button of document.querySelectorAll("#mode-toggle button")) {
    button.textContent = button.dataset.mode === "live" ? t("modeLive") : t("modeCached");
  }
  if (live.stage) el("progress-stage").textContent = t(live.stage.key, ...live.stage.args);
  if (!el("stall-banner").classList.contains("hidden")) {
    el("stall-text").textContent = t("stallWarning");
    el("stall-switch").textContent = t("switchToCached");
  }
  el("question-eyebrow").textContent = t("question");
  el("sources-title").textContent = t("sources");
  el("conflicts-title").textContent = t("conflicts");
  el("judgment-title").textContent = t("verdict");
  for (const button of document.querySelectorAll("#lang-toggle button")) {
    button.classList.toggle("active", button.dataset.lang === lang);
  }
}

function setLang(next) {
  if (next === lang) return;
  lang = next;
  localStorage.setItem("crossfire-lang", lang);
  applyStaticStrings();
  if (currentError) showError(currentError.key, ...currentError.args);
  if (currentRun) render(currentRun);
}

function domainOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url || "unknown";
  }
}

function tierClass(tier) {
  const t = (tier || "").toLowerCase();
  return ["primary", "news", "aggregator"].includes(t) ? t : "unknown";
}

function text(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined && value !== null) node.textContent = value;
  return node;
}

function labeled(label, node) {
  const box = document.createElement("div");
  box.appendChild(text("div", "field-label", label));
  box.appendChild(node);
  return box;
}

async function loadRuns() {
  const runs = await fetchJSON("/api/runs");
  const select = el("run-select");
  select.innerHTML = "";
  if (!runs.length) {
    showError("emptyRuns");
    el("content").classList.add("hidden");
    return;
  }
  for (const run of runs) {
    const option = document.createElement("option");
    option.value = run.name;
    option.textContent = run.name;
    select.appendChild(option);
  }
  select.onchange = () => loadRun(select.value);
  await loadRun(runs[0].name);
}

async function fetchJSON(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function loadRun(name) {
  const id = ++requestId;
  stopLive();
  el("progress-strip").classList.add("hidden");
  el("pair-progress").classList.add("hidden");
  try {
    const run = await fetchJSON(`/api/runs/${encodeURIComponent(name)}`);
    if (id !== requestId) return;
    currentRun = run;
    hideError();
    render(run);
  } catch (e) {
    if (id !== requestId) return;
    currentRun = null;
    renderFailures({});
    showError("loadFailed", name, e.message);
    el("content").classList.add("hidden");
  }
}

function showError(key, ...args) {
  currentError = { key, args };
  const banner = el("error-banner");
  banner.textContent = t(key, ...args);
  banner.classList.remove("hidden");
}

function hideError() {
  currentError = null;
  el("error-banner").classList.add("hidden");
}

function render(run) {
  el("content").classList.remove("hidden");
  renderFailures(run);
  renderQuestion(run);
  const cards = renderSources(run);
  renderConflicts(run, cards);
  renderJudgment(run);
}

function parseFailures(run) {
  const failures = [];
  for (const claim of run.claims || []) {
    if (claim.parse_error) failures.push({ stage: t("stageExtract"), url: claim.url, parse: true });
  }
  for (const pair of run.pairs || []) {
    if (pair.parse_error) {
      failures.push({ stage: t("stagePair"), url: `${domainOf(pair.a)} / ${domainOf(pair.b)}`, parse: true });
    }
  }
  if (run.judgment && run.judgment.parse_error) {
    failures.push({ stage: t("stageJudge"), url: run.question_id || "", parse: true });
  }
  return failures;
}

function renderFailures(run) {
  const banner = el("failure-banner");
  const declared = Array.isArray(run.failures) ? run.failures : run.failures ? [run.failures] : [];
  const failures = [...declared, ...parseFailures(run)];
  if (!failures.length) {
    banner.classList.add("hidden");
    banner.innerHTML = "";
    return;
  }
  banner.innerHTML = "";
  const head = text("div", null);
  head.appendChild(text("strong", null, t("failureHead", failures.length)));
  banner.appendChild(head);
  const list = document.createElement("ul");
  for (const failure of failures) {
    if (failure && failure.parse) {
      list.appendChild(text("li", null, t("parseFailure", failure.stage, failure.url)));
      continue;
    }
    const parts =
      typeof failure === "string"
        ? [failure]
        : [failure.stage, failure.url, failure.error || failure.message].filter(Boolean);
    list.appendChild(text("li", null, parts.join(" — ") || JSON.stringify(failure)));
  }
  banner.appendChild(list);
  banner.classList.remove("hidden");
}

function renderQuestion(run) {
  el("question").textContent = run.question || t("noQuestion");
  const meta = el("run-meta");
  meta.innerHTML = "";
  const bits = [];
  if (run.question_id) bits.push(`ID ${run.question_id}`);
  if (run.started_at) bits.push(t("startedAt", run.started_at));
  if (run.elapsed_seconds !== undefined) bits.push(t("elapsed", run.elapsed_seconds));
  if (run.pages_fetched !== undefined) bits.push(t("fetched", run.pages_fetched));
  if (run.pages_failed) bits.push(t("fetchFailedCount", run.pages_failed));
  for (const bit of bits) meta.appendChild(text("span", null, bit));
}

function sourceRows(run) {
  const claims = run.claims || [];
  const pages = run.pages || [];
  const configured = run.sources || [];
  const urls = [];
  for (const list of [configured, claims, pages]) {
    for (const item of list) {
      if (item && item.url && !urls.includes(item.url)) urls.push(item.url);
    }
  }
  return urls.map((url) => {
    const claim = claims.find((c) => c.url === url) || {};
    const page = pages.find((p) => p.url === url) || {};
    const configuredSource = configured.find((s) => s.url === url) || {};
    return {
      url,
      tier: claim.tier || configuredSource.tier || null,
      title: page.title || null,
      claim: claim.claim || null,
      evidence: claim.evidence || null,
      sourceType: claim.source_type || null,
      publishedDate: claim.published_date || null,
      confidence: claim.confidence,
      fetchError: page.ok === false ? page.error : null,
    };
  });
}

function renderSources(run) {
  const container = el("sources");
  container.innerHTML = "";
  const rows = sourceRows(run);
  el("source-count").textContent = t("sourceCount", rows.length);

  const cards = new Map();
  rows.forEach((row, index) => {
    const card = text("div", "card");
    card.dataset.url = row.url;

    const head = text("div", "card-head");
    const domain = text("div", "domain");
    const link = document.createElement("a");
    link.href = row.url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = domainOf(row.url);
    domain.appendChild(link);
    head.appendChild(domain);
    head.appendChild(text("span", "card-index", `S${index + 1}`));
    card.appendChild(head);

    const tags = text("div", "tags");
    const tier = tierClass(row.tier);
    tags.appendChild(text("span", `tag ${tier}`, row.tier || "unknown"));
    if (row.sourceType) tags.appendChild(text("span", "tag plain", row.sourceType));
    card.appendChild(tags);

    const claimNode = text("div", row.claim ? "claim" : "claim empty", row.claim || t("noClaim"));
    card.appendChild(labeled(t("claim"), claimNode));

    if (row.evidence) {
      card.appendChild(labeled(t("evidence"), text("blockquote", "evidence", row.evidence)));
    }
    if (row.fetchError) {
      card.appendChild(labeled(t("fetchFailed"), text("div", "claim empty", row.fetchError)));
    }

    const foot = text("div", "card-foot");
    const dateNode = text(
      "span",
      row.publishedDate ? null : "unknown-date",
      t("published", row.publishedDate || t("unknown")),
    );
    foot.appendChild(dateNode);
    if (typeof row.confidence === "number") {
      foot.appendChild(text("span", null, t("sourceConfidence", Math.round(row.confidence * 100))));
    }
    card.appendChild(foot);

    container.appendChild(card);
    cards.set(row.url, { card, index });
  });
  return cards;
}

function renderConflicts(run, cards) {
  const container = el("conflicts");
  container.innerHTML = "";
  const pairs = (run.pairs || []).filter((p) => p.relation === "contradict");
  const unresolved = (run.pairs || []).filter((p) => !p.relation).length;
  el("conflict-count").textContent = t("conflictCount", pairs.length);

  for (const { card } of cards.values()) card.classList.remove("conflicted");

  if (!pairs.length) {
    const state = unresolved
      ? text("div", "empty-state partial", t("partialConflicts", unresolved))
      : text("div", "empty-state", t("noConflicts"));
    container.appendChild(state);
    drawLinks([], cards);
    return;
  }

  const claims = run.claims || [];
  pairs.forEach((pair, i) => {
    const item = text("div", "conflict");
    const aInfo = cards.get(pair.a);
    const bInfo = cards.get(pair.b);
    if (aInfo) aInfo.card.classList.add("conflicted");
    if (bInfo) bInfo.card.classList.add("conflicted");

    const head = text("div", "conflict-pair");
    head.appendChild(text("span", null, `C${i + 1}`));
    head.appendChild(text("span", null, labelFor(pair.a, aInfo)));
    head.appendChild(text("span", "vs", "VS"));
    head.appendChild(text("span", null, labelFor(pair.b, bInfo)));
    item.appendChild(head);

    item.appendChild(text("div", "conflict-nature", pair.nature || t("noNature")));

    const claimA = claims.find((c) => c.url === pair.a);
    const claimB = claims.find((c) => c.url === pair.b);
    if (claimA || claimB) {
      const grid = text("div", "conflict-claims");
      grid.appendChild(text("div", null, `${domainOf(pair.a)}: ${(claimA && claimA.claim) || "—"}`));
      grid.appendChild(text("div", null, `${domainOf(pair.b)}: ${(claimB && claimB.claim) || "—"}`));
      item.appendChild(grid);
    }

    item.onmouseenter = () => spotlight([pair.a, pair.b], cards);
    item.onmouseleave = () => spotlight(null, cards);
    container.appendChild(item);

    markConflictPartner(aInfo, bInfo);
    markConflictPartner(bInfo, aInfo);
  });

  drawLinks(pairs, cards);
}

function markConflictPartner(target, partner) {
  if (!target || !partner) return;
  const tags = target.card.querySelector(".tags");
  const label = t("conflictWith", `S${partner.index + 1}`);
  if (!tags || [...tags.children].some((node) => node.textContent === label)) return;
  tags.appendChild(text("span", "tag conflict-flag", label));
}

function labelFor(url, info) {
  return info ? `S${info.index + 1} ${domainOf(url)}` : domainOf(url);
}

function spotlight(urls, cards) {
  for (const [url, { card }] of cards) {
    card.classList.toggle("dimmed", Boolean(urls) && !urls.includes(url));
  }
}

function drawLinks(pairs, cards) {
  const svg = el("conflict-links");
  svg.innerHTML = "";
  const wrap = svg.parentElement.getBoundingClientRect();
  for (const pair of pairs) {
    const a = cards.get(pair.a);
    const b = cards.get(pair.b);
    if (!a || !b) continue;
    const ra = a.card.getBoundingClientRect();
    const rb = b.card.getBoundingClientRect();
    const sameRow = Math.abs(ra.top - rb.top) < 4;
    const [left, right] = ra.left <= rb.left ? [ra, rb] : [rb, ra];
    const [upper, lower] = ra.top <= rb.top ? [ra, rb] : [rb, ra];

    let x1;
    let y1;
    let x2;
    let y2;
    let c1x;
    let c1y;
    let c2x;
    let c2y;
    if (sameRow) {
      x1 = left.right - wrap.left;
      y1 = left.top + left.height / 2 - wrap.top;
      x2 = right.left - wrap.left;
      y2 = right.top + right.height / 2 - wrap.top;
      const bow = Math.min(30, (x2 - x1) / 2 + 6);
      [c1x, c1y, c2x, c2y] = [x1 + bow, y1, x2 - bow, y2];
    } else {
      x1 = upper.left + upper.width / 2 - wrap.left;
      y1 = upper.bottom - wrap.top;
      x2 = lower.left + lower.width / 2 - wrap.left;
      y2 = lower.top - wrap.top;
      const drop = Math.max(10, (y2 - y1) / 2);
      [c1x, c1y, c2x, c2y] = [x1, y1 + drop, x2, y2 - drop];
    }

    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", `M ${x1} ${y1} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${x2} ${y2}`);
    svg.appendChild(path);
    for (const [cx, cy] of [
      [x1, y1],
      [x2, y2],
    ]) {
      const dot = document.createElementNS(SVG_NS, "circle");
      dot.setAttribute("cx", String(cx));
      dot.setAttribute("cy", String(cy));
      dot.setAttribute("r", "3");
      svg.appendChild(dot);
    }
  }
}

function renderJudgment(run) {
  const container = el("judgment");
  container.innerHTML = "";
  const judgment = run.judgment || {};

  const main = text("div", null);
  main.appendChild(text("div", "answer", judgment.answer || t("noVerdict")));
  if (judgment.reasoning) {
    main.appendChild(labeled(t("reasoning"), text("div", "reasoning", judgment.reasoning)));
  }
  if (Array.isArray(judgment.conflicts) && judgment.conflicts.length) {
    const list = document.createElement("ul");
    list.className = "judge-conflicts";
    for (const conflict of judgment.conflicts) list.appendChild(text("li", null, conflict));
    main.appendChild(labeled(t("recordedConflicts"), list));
  }
  const trusted = text("div", "trusted");
  const sources = Array.isArray(judgment.trusted_sources) ? judgment.trusted_sources : [];
  if (sources.length) {
    sources.forEach((url, i) => {
      const row = text("div", "trusted-row");
      row.appendChild(text("span", "trusted-rank", `#${i + 1}`));
      const link = document.createElement("a");
      link.href = url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = url;
      row.appendChild(link);
      trusted.appendChild(row);
    });
  } else {
    trusted.appendChild(text("div", "claim empty", t("noTrusted")));
  }
  main.appendChild(labeled(t("trusted"), trusted));
  container.appendChild(main);
  container.appendChild(confidenceRing(judgment.confidence));
}

function confidenceRing(confidence) {
  const wrap = text("div", "ring-wrap");
  const value = typeof confidence === "number" ? Math.max(0, Math.min(1, confidence)) : null;
  const radius = 58;
  const circumference = 2 * Math.PI * radius;
  const color = value === null ? "#8c98ad" : value >= 0.75 ? "#4ade80" : value >= 0.45 ? "#ffb347" : "#ff5c6c";

  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "ring");
  svg.setAttribute("viewBox", "0 0 150 150");

  const track = document.createElementNS(SVG_NS, "circle");
  track.setAttribute("class", "ring-track");
  track.setAttribute("cx", "75");
  track.setAttribute("cy", "75");
  track.setAttribute("r", String(radius));
  svg.appendChild(track);

  const arc = document.createElementNS(SVG_NS, "circle");
  arc.setAttribute("class", "ring-value");
  arc.setAttribute("cx", "75");
  arc.setAttribute("cy", "75");
  arc.setAttribute("r", String(radius));
  arc.setAttribute("stroke", color);
  arc.setAttribute("stroke-dasharray", String(circumference));
  arc.setAttribute("stroke-dashoffset", String(circumference * (1 - (value ?? 0))));
  svg.appendChild(arc);

  const label = document.createElementNS(SVG_NS, "text");
  label.setAttribute("class", "pct");
  label.setAttribute("x", "75");
  label.setAttribute("y", "84");
  label.setAttribute("text-anchor", "middle");
  label.textContent = value === null ? "—" : `${Math.round(value * 100)}%`;
  svg.appendChild(label);

  wrap.appendChild(svg);
  wrap.appendChild(text("div", "ring-label", t("confidence")));
  return wrap;
}

// ---------------------------------------------------------------- live run --

const STALL_TIMEOUT_MS = 15000;
const FLASH_MS = 220;
const FAKE_SCENARIO = new URLSearchParams(location.search).get("fake");
const FAKE_SPEED = new URLSearchParams(location.search).get("speed") || "1";

let mode = "cached";

const live = {
  active: false,
  stream: null,
  slots: [],
  cards: new Map(),
  pairs: new Map(),
  totalSources: 0,
  totalPairs: 0,
  fetched: 0,
  claimed: 0,
  judged: false,
  question: "",
  errors: [],
  stage: null,
  startedAt: 0,
  timer: null,
  stall: null,
};

function setMode(next) {
  mode = next === "live" ? "live" : "cached";
  for (const button of document.querySelectorAll("#mode-toggle button")) {
    button.classList.toggle("active", button.dataset.mode === mode);
  }
}

function setStage(key, ...args) {
  live.stage = { key, args };
  el("progress-stage").textContent = t(key, ...args);
}

function updateProgress() {
  const total = live.totalSources * 2 + live.totalPairs + 1;
  const done = live.fetched + live.claimed + live.pairs.size + (live.judged ? 1 : 0);
  const pct = total ? Math.min(100, Math.round((done / total) * 100)) : 0;
  el("progress-fill").style.width = `${pct}%`;
}

function startTimer() {
  live.startedAt = performance.now();
  const tick = () => {
    el("progress-timer").textContent = `${((performance.now() - live.startedAt) / 1000).toFixed(1)}s`;
  };
  tick();
  live.timer = setInterval(tick, 100);
}

function stopTimer() {
  if (live.timer) clearInterval(live.timer);
  live.timer = null;
}

function armStall() {
  clearStall();
  if (mode !== "live") return;
  live.stall = setTimeout(() => {
    el("stall-text").textContent = t("stallWarning");
    el("stall-switch").textContent = t("switchToCached");
    el("stall-banner").classList.remove("hidden");
  }, STALL_TIMEOUT_MS);
}

function clearStall() {
  if (live.stall) clearTimeout(live.stall);
  live.stall = null;
  el("stall-banner").classList.add("hidden");
}

function stopLive() {
  if (live.stream) live.stream.close();
  live.stream = null;
  live.active = false;
  stopTimer();
  clearStall();
  el("run-button").textContent = t("runButton");
  el("run-button").classList.remove("running");
}

function resetLive() {
  stopLive();
  live.slots = [];
  live.cards = new Map();
  live.pairs = new Map();
  live.totalSources = 0;
  live.totalPairs = 0;
  live.fetched = 0;
  live.claimed = 0;
  live.judged = false;
  live.question = "";
  live.errors = [];
  live.stage = null;
  currentRun = null;
  hideError();
  el("failure-banner").classList.add("hidden");
  el("failure-banner").innerHTML = "";
  el("sources").innerHTML = "";
  el("conflicts").innerHTML = "";
  el("judgment").innerHTML = "";
  el("conflict-links").innerHTML = "";
  el("run-meta").innerHTML = "";
  el("question").textContent = "";
  el("source-count").textContent = "";
  el("conflict-count").textContent = "";
  el("pair-progress").classList.add("hidden");
  el("progress-fill").style.width = "0%";
  el("progress-timer").textContent = "0.0s";
}

function streamUrl(questionId) {
  if (FAKE_SCENARIO) {
    return `/api/fake-run/${encodeURIComponent(FAKE_SCENARIO)}?speed=${encodeURIComponent(FAKE_SPEED)}`;
  }
  return `/api/run/${encodeURIComponent(questionId)}?mode=${mode}`;
}

function startRun() {
  const questionId = el("question-select").value;
  if (!questionId && !FAKE_SCENARIO) return;
  resetLive();
  live.active = true;
  el("content").classList.remove("hidden");
  el("progress-strip").classList.remove("hidden");
  el("run-button").textContent = t("runningButton");
  el("run-button").classList.add("running");
  setStage("stageConnecting");
  startTimer();
  armStall();

  const stream = new EventSource(streamUrl(questionId));
  live.stream = stream;
  stream.onmessage = (message) => {
    armStall();
    let event;
    try {
      event = JSON.parse(message.data);
    } catch {
      return;
    }
    handleEvent(event);
  };
  stream.onerror = () => {
    if (!live.active) return;
    stopLive();
    showError("streamFailed");
  };
}

function handleEvent(event) {
  switch (event.type) {
    case "start":
      onStart(event);
      break;
    case "fetch_done":
      onFetchDone(event);
      break;
    case "claim_done":
      onClaimDone(event);
      break;
    case "pair_start":
      onPairStart(event);
      break;
    case "pair_done":
      onPairDone(event);
      break;
    case "judge_start":
      onJudgeStart();
      break;
    case "done":
      onDone(event);
      break;
    case "error":
      onStepError(event);
      break;
    default:
      break;
  }
}

function onStart(event) {
  live.question = event.question || "";
  live.totalSources = event.total_sources || 0;
  live.totalPairs = (live.totalSources * (live.totalSources - 1)) / 2;
  el("question").textContent = live.question || t("noQuestion");
  el("source-count").textContent = t("sourceCount", live.totalSources);
  el("conflict-count").textContent = t("conflictCount", 0);
  buildSkeletons(live.totalSources);
  setStage("stageFetching", 0, live.totalSources);
  updateProgress();
}

function buildSkeletons(count) {
  const container = el("sources");
  container.innerHTML = "";
  live.slots = [];
  for (let index = 0; index < count; index += 1) {
    const card = text("div", "card card-skeleton");
    card.dataset.index = String(index);

    const head = text("div", "card-head");
    head.appendChild(text("div", "domain", "—"));
    head.appendChild(text("span", "card-index", `S${index + 1}`));
    card.appendChild(head);

    const tags = text("div", "tags");
    tags.appendChild(text("span", "tag unknown", t("pendingSource")));
    card.appendChild(tags);

    const body = text("div", "skeleton-body");
    for (const width of ["92%", "78%", "60%"]) {
      const bar = text("div", "skeleton-bar");
      bar.style.width = width;
      body.appendChild(bar);
    }
    card.appendChild(body);
    container.appendChild(card);
    live.slots.push({ card, index, url: null, tier: null, claim: null, ok: null, chars: 0 });
  }
}

function slotAt(index) {
  return live.slots[index] || null;
}

function flash(card) {
  card.classList.add("flash");
  setTimeout(() => card.classList.remove("flash"), FLASH_MS);
}

function onFetchDone(event) {
  const slot = slotAt(event.index);
  if (!slot) return;
  slot.url = event.url;
  slot.ok = event.ok !== false;
  slot.chars = event.chars || 0;
  slot.card.dataset.url = event.url;
  live.cards.set(event.url, { card: slot.card, index: slot.index });

  const domain = slot.card.querySelector(".domain");
  domain.textContent = "";
  const link = document.createElement("a");
  link.href = event.url;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = domainOf(event.url);
  domain.appendChild(link);

  const tags = slot.card.querySelector(".tags");
  tags.innerHTML = "";
  tags.appendChild(
    text("span", slot.ok ? "tag plain" : "tag conflict-flag", slot.ok ? t("fetchedChars", slot.chars) : t("fetchFailed")),
  );

  slot.card.classList.remove("card-skeleton");
  slot.card.classList.add("card-fetched");
  if (!slot.ok) slot.card.classList.add("card-failed");
  flash(slot.card);

  live.fetched += 1;
  setStage("stageFetching", live.fetched, live.totalSources);
  updateProgress();
}

function onClaimDone(event) {
  const slot = slotAt(event.index);
  if (!slot) return;
  slot.claim = event.claim || null;
  slot.tier = event.tier || null;
  if (!slot.url) {
    slot.url = event.url;
    slot.card.dataset.url = event.url;
    live.cards.set(event.url, { card: slot.card, index: slot.index });
  }

  const tags = slot.card.querySelector(".tags");
  tags.innerHTML = "";
  tags.appendChild(text("span", `tag ${tierClass(slot.tier)}`, slot.tier || "unknown"));
  if (slot.ok === false) tags.appendChild(text("span", "tag conflict-flag", t("fetchFailed")));

  const body = slot.card.querySelector(".skeleton-body");
  if (body) body.remove();
  const existing = slot.card.querySelector(".claim-block");
  if (existing) existing.remove();
  const block = labeled(t("claim"), text("div", slot.claim ? "claim" : "claim empty", slot.claim || t("noClaim")));
  block.className = "claim-block";
  slot.card.appendChild(block);

  slot.card.classList.remove("card-skeleton");
  slot.card.classList.add("card-done");
  flash(slot.card);

  live.claimed += 1;
  setStage("stageExtracting", live.claimed, live.totalSources);
  updateProgress();
}

function onPairStart(event) {
  live.totalPairs = event.total_pairs || 0;
  el("pair-progress").classList.remove("hidden");
  el("pair-progress").textContent = t("pairProgress", 0, live.totalPairs);
  setStage("stageComparing", 0, live.totalPairs);
  renderLiveConflicts();
  updateProgress();
}

function onPairDone(event) {
  // index is authoritative: events arrive out of order.
  live.pairs.set(event.index, {
    index: event.index,
    a: event.a_url,
    b: event.b_url,
    relation: event.relation,
    nature: event.nature,
  });
  if (event.total) live.totalPairs = event.total;
  el("pair-progress").textContent = t("pairProgress", live.pairs.size, live.totalPairs);
  setStage("stageComparing", live.pairs.size, live.totalPairs);
  renderLiveConflicts();
  updateProgress();
}

function orderedPairs() {
  return [...live.pairs.values()].sort((a, b) => a.index - b.index);
}

function renderLiveConflicts() {
  const contradictions = orderedPairs().filter((pair) => pair.relation === "contradict");
  el("conflict-count").textContent = t("conflictCount", contradictions.length);
  renderConflicts({ pairs: orderedPairs(), claims: claimRows() }, live.cards);
}

function claimRows() {
  return live.slots.filter((slot) => slot.url).map((slot) => ({ url: slot.url, claim: slot.claim, tier: slot.tier }));
}

function onJudgeStart() {
  setStage("stageJudging");
  const container = el("judgment");
  container.innerHTML = "";
  container.appendChild(text("div", "thinking", t("thinking")));
}

function onDone(event) {
  live.judged = true;
  updateProgress();
  setStage("stageDone");
  stopLive();
  currentRun = {
    question: live.question,
    elapsed_seconds: event.elapsed,
    run_file: event.run_file,
    sources: live.slots.filter((s) => s.url).map((s) => ({ url: s.url, tier: s.tier })),
    pages: live.slots.filter((s) => s.url).map((s) => ({ url: s.url, ok: s.ok !== false })),
    claims: claimRows(),
    pairs: orderedPairs(),
    judgment: event.judgment || null,
    failures: live.errors.map((e) => ({ stage: e.step, error: e.detail })),
  };
  render(currentRun);
  el("pair-progress").classList.add("hidden");
}

function onStepError(event) {
  live.errors.push({ step: event.step, detail: event.detail });
  renderFailures({ failures: live.errors.map((e) => ({ stage: e.step, error: e.detail })) });
}

function switchToCached() {
  setMode("cached");
  clearStall();
  if (live.active) {
    stopLive();
    startRun();
  }
}

async function loadQuestions() {
  const questions = await fetchJSON("/api/questions");
  const select = el("question-select");
  select.innerHTML = "";
  if (!questions.length) {
    showError("noQuestions");
    return;
  }
  for (const question of questions) {
    const option = document.createElement("option");
    option.value = question.id;
    option.textContent = question.question || question.id;
    select.appendChild(option);
  }
}

window.addEventListener("resize", () => {
  if (!currentRun) return;
  const cards = new Map();
  document.querySelectorAll(".card").forEach((card, index) => cards.set(card.dataset.url, { card, index }));
  drawLinks((currentRun.pairs || []).filter((p) => p.relation === "contradict"), cards);
});

for (const button of document.querySelectorAll("#lang-toggle button")) {
  button.onclick = () => setLang(button.dataset.lang);
}
for (const button of document.querySelectorAll("#mode-toggle button")) {
  button.onclick = () => setMode(button.dataset.mode);
}
el("run-button").onclick = startRun;
el("stall-switch").onclick = switchToCached;

// Demo escape hatch: Ctrl+Alt+C drops back to cached mode mid-run.
window.addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.altKey && event.code === "KeyC") {
    event.preventDefault();
    switchToCached();
  }
});

setMode("cached");
applyStaticStrings();
loadQuestions().catch(() => {});
loadRuns().catch((e) => showError("listFailed", e.message));
