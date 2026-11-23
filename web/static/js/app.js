import { SVG_NS, domainOf, el, labeled, prefersReducedMotion, text, tierClass } from "./dom.js";
import {
  bindBottomLang,
  bindHeroLang,
  bindVerdictLang,
  renderBottomPanels,
  renderHeroSubtitle,
  renderMetrics as renderSummaryMetrics,
  renderNliNote,
  renderVerdictPane,
} from "./dashboard.js";
import { renderGroupedEvidence, renderGroupsProcessing, setEvidenceView } from "./groups.js";

const RELATION_CONTRADICT = "contradict";
// Both claims are true but measure different things, so the numbers are not
// comparable — drawn apart from real contradictions.
const RELATION_SCOPE = "same_question_different_scope";
// Past this many links the graph braids into an unreadable bundle, so scope
// links go quiet and only surface for the card or pair being pointed at.
const LINK_CROWD_LIMIT = 8;

const STRINGS = {
  en: {
    tagline: "Multi-source. Multi-perspective. Fact-based.",
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
    stallWarning: "No events for 30s — the live run may be stuck.",
    switchToCached: "Switch to cached",
    streamFailed: "The live stream dropped. Switch to cached mode for the demo.",
    stepError: (step, detail) => `${step} — ${detail}`,
    noQuestions: "No questions found in questions/demo.yaml.",
    question: "Question",
    noQuestion: "(no question recorded)",
    sources: "Sources",
    sourceCount: (n) => `${n} sources`,
    conflicts: "Conflicts",
    relationCount: (n, m) =>
      `${n} ${n === 1 ? "contradiction" : "contradictions"} / ${m} scope ${m === 1 ? "difference" : "differences"}`,
    contradictGroup: "Contradictions",
    scopeGroup: "Different scope",
    legendContradict: "Contradiction — the two claims cannot both be true",
    legendScope: "Different scope — both claims are true, but they measure different things and cannot be compared directly",
    legendCrowded: "Too many links to read at once — point at a source or a pair to trace its scope links",
    scopeWith: (id) => `different scope from ${id}`,
    verdict: "Verdict",
    claim: "Claim",
    evidence: "Evidence",
    fetchFailed: "Fetch failed",
    noClaim: "This source makes no claim about the question",
    published: (date) => `Published ${date}`,
    contentDated: (date) => `Content as of ${date}`,
    unknown: "unknown",
    dateUnknown: "date unknown",
    sourceConfidence: (pct) => `Source confidence ${pct}%`,
    scoresCalibrationShort: "model estimate, uncalibrated",
    scoresCalibrationHover:
      "This number is the model’s own estimate, not real accuracy. The model can be wrong and still assign a very high probability.",
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
    pairerClaude: "Claude",
    pairerNli: "Local NLI",
    pairerUnavailable: (reason) => `Unavailable: ${reason}`,
    pairerLabel: "Pairer",
    pairerUnknown: "Not recorded",
    extractFailed: "Extract failed",
    contentUnusable: (reason) => `Content unusable: ${reason}`,
    formatWarningConflicts:
      "Warning: conflicts is not an array in this run’s verdict — format may be corrupted.",
    formatWarningTrusted:
      "Warning: trusted_sources is not an array in this run’s verdict — format may be corrupted.",
    failureHeadBreakdown: (fetch, usability, model) => {
      const n = fetch + usability + model;
      return `${n} failure${n === 1 ? "" : "s"} (fetch ${fetch} · unusable ${usability} · model ${model})`;
    },
    scoresHint: "Class probabilities",
    scoresCalibration:
      "Model estimate, uncalibrated — a high score does not mean the label is correct.",
    metricSources: "Sources",
    metricComparisons: "Comparisons",
    metricContradictions: "Contradictions",
    metricScope: "Scope differences",
    questionEyebrow: "Fact-check analysis",
    askTitle: "Ask a question",
    askLead: "Crossfire will search the web, fetch pages, compare claims, and give a verdict. Each new question costs money.",
    askButton: "Ask",
    askAsking: "Asking…",
    askPlaceholder: "e.g. What is the current stable Node.js LTS version?",
    askExamplesLabel: "Good examples",
    askExample1: "What is the current stable version of Python?",
    askExample2: "Who is the current Secretary-General of the United Nations?",
    askExample3: "What is the latest LTS release of Ubuntu?",
    askUnsuitable: "Unsuitable: disputed political claims, open-ended opinions, or questions with no checkable answer.",
    askDialogTitle: "Confirm before spending",
    askDialogEstimate: (low, high, lowN, highN, max) =>
      `Estimated cost about $${low.toFixed(2)} (${lowN} sources) – $${high.toFixed(2)} (${highN} sources) (cap $${max.toFixed(2)}).`,
    askDialogPairer: (name, free) => `Pairer: ${name}${free ? " (local, free)" : ""}.`,
    askConfirm: "Confirm & run",
    askCancel: "Cancel",
    askOverBudget: (usd, max) => `Estimate $${usd.toFixed(2)} exceeds the $${max.toFixed(2)} cap — not started.`,
    sourceFindTitle: "Finding sources",
    sourceFindCount: (n) => `${n} candidates`,
    sourceFindCandidate: "candidate",
    sourceFindFiltered: "filtered",
    sourceFindReady: "ready",
    stageSearching: "Searching for sources…",
    stageSourcesReady: (n) => `Sources ready (${n})`,
    askStoppedFew: (detail) => `Stopped early — not enough usable sources. ${detail}`,
    askStoppedCost: (detail) => `Stopped — cost limit. ${detail}`,
    askStoppedOther: (detail) => `Stopped. ${detail}`,
    metricFaulty: "Wrong / outdated",
    metricScopeSources: "Scope sources",
    legendTrusted: "Consistent",
    legendFaulty: "Wrong / outdated",
    legendScopeSources: "Scope differences",
    noScopeSources: "No scope-difference sources in the summary.",
    noComposition: "No source composition recorded.",
    nliRawNote: (n, m) =>
      `Local model raw calls: ${n} contradiction pair(s), of which ${m} had confidence < 0.5; final call is in the verdict.`,
    evidenceTitle: "Evidence",
    viewDetailCta: "View Detailed Analysis →",
    askCta: "Ask a Question",
    demoHeading: "Demo run",
    detailTitle: "Full analysis",
    contradictionTitle: "Contradictions",
    scopeTitle: "Scope differences",
    compositionTitle: "Sources overview",
    historyFilterPlaceholder: "Search past investigations…",
    menuLabel: "Menu",
    viewGroups: "Groups",
    viewTable: "Table",
    groupTrusted: "Trusted",
    groupFaulty: "Wrong / outdated",
    groupScope: "Scope differences",
    groupNeutral: "Neutral",
    groupFailed: "Failed",
    groupProcessing: "In progress",
    groupEmpty: "(none)",
    groupNoPairs: "No pairwise comparisons involving this source.",
    expandAnswer: "Show full answer",
    collapseAnswer: "Show less",
  },
  zh: {
    tagline: "多来源 · 多视角 · 讲证据",
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
    stallWarning: "已有 30 秒没有收到任何事件，实时运行可能卡住了。",
    switchToCached: "切换到回放",
    streamFailed: "实时事件流中断了，演示请切到回放模式。",
    stepError: (step, detail) => `${step} — ${detail}`,
    noQuestions: "questions/demo.yaml 里没有找到任何问题。",
    question: "问题",
    noQuestion: "（无问题原文）",
    sources: "来源",
    sourceCount: (n) => `${n} 个来源`,
    conflicts: "冲突",
    relationCount: (n, m) => `${n} 个矛盾 / ${m} 个口径差异`,
    contradictGroup: "真矛盾",
    scopeGroup: "口径不同",
    legendContradict: "矛盾 —— 两个说法不可能同时为真",
    legendScope: "口径不同 —— 两个说法各自为真，但统计口径不同，不能直接比较",
    legendCrowded: "连线太多看不清 —— 把鼠标移到某个来源或某条差异上，单独看它的连线",
    scopeWith: (id) => `口径不同于 ${id}`,
    verdict: "结论",
    claim: "主张",
    evidence: "证据原文",
    fetchFailed: "抓取失败",
    noClaim: "该来源未就此问题给出主张",
    published: (date) => `发布于 ${date}`,
    contentDated: (date) => `内容所述时间 ${date}`,
    unknown: "unknown",
    dateUnknown: "日期未知",
    sourceConfidence: (pct) => `来源置信度 ${pct}%`,
    scoresCalibrationShort: "模型自估，未经校准",
    scoresCalibrationHover:
      "这个数字是模型自己的估计，不等于实际准确率；模型判错时也可能给出很高的概率。",
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
    pairerClaude: "Claude",
    pairerNli: "本地模型（NLI）",
    pairerUnavailable: (reason) => `不可用：${reason}`,
    pairerLabel: "比对器",
    pairerUnknown: "未记录",
    extractFailed: "提取失败",
    contentUnusable: (reason) => `内容不可用：${reason}`,
    formatWarningConflicts: "警告：本次结果的 conflicts 不是数组，格式可能损坏。",
    formatWarningTrusted: "警告：trusted_sources 不是数组，格式可能损坏。",
    failureHeadBreakdown: (fetch, usability, model) => {
      const n = fetch + usability + model;
      return `本次运行有 ${n} 处失败（抓取 ${fetch} · 不可用 ${usability} · 模型 ${model}）`;
    },
    scoresHint: "类别概率",
    scoresCalibration: "模型自估，未经校准——数值高不等于判断正确。",
    metricSources: "来源",
    metricComparisons: "比对",
    metricContradictions: "矛盾",
    metricScope: "口径差异",
    questionEyebrow: "查证分析",
    askTitle: "自己提问",
    askLead: "系统会上网找来源、抓取页面、比对主张并下结论。每问一个新问题都要花钱。",
    askButton: "提问",
    askAsking: "提问中…",
    askPlaceholder: "例如：当前稳定版 Python 是哪个？",
    askExamplesLabel: "好问题示例",
    askExample1: "当前稳定版 Python 是哪个？",
    askExample2: "现任联合国秘书长是谁？",
    askExample3: "Ubuntu 最新的 LTS 版本是哪个？",
    askUnsuitable: "不适合：公认有争议的话题、纯观点题、没有可核对答案的问题。",
    askDialogTitle: "确认后再花钱",
    askDialogEstimate: (low, high, lowN, highN, max) =>
      `预计约 $${low.toFixed(2)}（${lowN} 个来源）～ $${high.toFixed(2)}（${highN} 个来源）（上限 $${max.toFixed(2)}）。`,
    askDialogPairer: (name, free) => `比对器：${name}${free ? "（本地免费）" : ""}。`,
    askConfirm: "确认开跑",
    askCancel: "取消",
    askOverBudget: (usd, max) => `预计 $${usd.toFixed(2)} 超过上限 $${max.toFixed(2)}，没有开始。`,
    sourceFindTitle: "正在找来源",
    sourceFindCount: (n) => `${n} 个候选`,
    sourceFindCandidate: "候选",
    sourceFindFiltered: "已过滤",
    sourceFindReady: "已确定",
    stageSearching: "正在上网找来源…",
    stageSourcesReady: (n) => `来源已确定（${n}）`,
    askStoppedFew: (detail) => `提前停止——可用来源不够。${detail}`,
    askStoppedCost: (detail) => `已停止——费用超限。${detail}`,
    askStoppedOther: (detail) => `已停止。${detail}`,
    metricFaulty: "有误来源",
    metricScopeSources: "口径来源",
    legendTrusted: "一致",
    legendFaulty: "有误 / 过时",
    legendScopeSources: "口径差异",
    noScopeSources: "摘要里没有口径差异来源。",
    noComposition: "没有来源构成数据。",
    nliRawNote: (n, m) =>
      `本地模型原始判定：${n} 对矛盾，其中 ${m} 对置信度 < 0.5；最终判断见结论。`,
    evidenceTitle: "证据关系",
    viewDetailCta: "查看完整分析 →",
    askCta: "自己提问",
    demoHeading: "演示重跑",
    detailTitle: "完整分析",
    contradictionTitle: "矛盾",
    scopeTitle: "口径差异",
    compositionTitle: "来源构成",
    historyFilterPlaceholder: "搜索历史查证…",
    menuLabel: "菜单",
    viewGroups: "分组",
    viewTable: "表格",
    groupTrusted: "采信",
    groupFaulty: "有误 / 过时",
    groupScope: "口径不同",
    groupNeutral: "中立",
    groupFailed: "失败",
    groupProcessing: "处理中",
    groupEmpty: "（无）",
    groupNoPairs: "该来源没有参与比对记录。",
    expandAnswer: "展开全文",
    collapseAnswer: "收起",
  },
};

const ASK_EXAMPLES = ["askExample1", "askExample2", "askExample3"];

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
  el("question-eyebrow").textContent = t("questionEyebrow");
  const calib = el("scores-calibration");
  calib.textContent = t("scoresCalibrationShort");
  calib.title = t("scoresCalibrationHover");
  el("run-button").textContent = live.active ? t("runningButton") : t("runButton");
  el("ask-title").textContent = t("askTitle");
  el("ask-lead").textContent = t("askLead");
  el("ask-button").textContent = live.active && live.asking ? t("askAsking") : t("askButton");
  el("ask-input").placeholder = t("askPlaceholder");
  el("ask-unsuitable").textContent = t("askUnsuitable");
  el("ask-dialog-title").textContent = t("askDialogTitle");
  el("ask-confirm").textContent = t("askConfirm");
  el("ask-cancel").textContent = t("askCancel");
  el("source-find-title").textContent = t("sourceFindTitle");
  renderAskExamples();
  for (const button of document.querySelectorAll("#mode-toggle button")) {
    button.textContent = button.dataset.mode === "live" ? t("modeLive") : t("modeCached");
  }
  for (const button of document.querySelectorAll("#pairer-toggle button")) {
    button.textContent = button.dataset.pairer === "nli" ? t("pairerNli") : t("pairerClaude");
    if (button.disabled) {
      const opt = pairerOptions.find((o) => o.id === button.dataset.pairer);
      if (opt?.reason) button.title = t("pairerUnavailable", opt.reason);
    }
  }
  if (live.stage) el("progress-stage").textContent = t(live.stage.key, ...live.stage.args);
  if (!el("stall-banner").classList.contains("hidden")) {
    el("stall-text").textContent = t("stallWarning");
    el("stall-switch").textContent = t("switchToCached");
  }
  el("question-eyebrow").textContent = t("questionEyebrow");
  el("sources-title").textContent = t("sources");
  el("conflicts-title").textContent = t("conflicts");
  el("judgment-title").textContent = t("verdict");
  const evidenceTitle = el("evidence-title");
  if (evidenceTitle) evidenceTitle.textContent = t("evidenceTitle");
  const vg = el("view-groups-label");
  if (vg) vg.textContent = t("viewGroups");
  const vt = el("view-table-label");
  if (vt) vt.textContent = t("viewTable");
  const cta = el("view-detail-cta");
  if (cta) cta.textContent = t("viewDetailCta");
  const askCta = el("ask-cta-label");
  if (askCta) askCta.textContent = t("askCta");
  const demo = el("demo-heading");
  if (demo) demo.textContent = t("demoHeading");
  const detailTitle = el("detail-title");
  if (detailTitle) detailTitle.textContent = t("detailTitle");
  const detailJudgment = el("detail-judgment-title");
  if (detailJudgment) detailJudgment.textContent = t("verdict");
  const c1 = el("contradiction-title");
  if (c1) c1.textContent = t("contradictionTitle");
  const c2 = el("scope-title");
  if (c2) c2.textContent = t("scopeTitle");
  const c3 = el("composition-title");
  if (c3) c3.textContent = t("compositionTitle");
  const hist = el("history-filter");
  if (hist) hist.placeholder = t("historyFilterPlaceholder");
  const menu = el("sidebar-toggle");
  if (menu) menu.textContent = t("menuLabel");
  for (const button of document.querySelectorAll("#lang-toggle button, #lang-toggle-top button")) {
    button.classList.toggle("active", button.dataset.lang === lang);
  }
  if (currentRun) {
    bindVerdictLang(lang);
    bindBottomLang(lang);
    bindHeroLang(lang);
    renderHeroSubtitle(currentRun, t);
    renderVerdictPane(currentRun, t, { renderSafeMarkdown, confidenceRing });
    renderBottomPanels(currentRun, t);
    renderNliNote(currentRun, t);
  }
}

function renderAskExamples() {
  const box = el("ask-examples");
  box.innerHTML = "";
  for (const key of ASK_EXAMPLES) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ask-example";
    button.textContent = t(key);
    button.onclick = () => {
      el("ask-input").value = t(key);
      el("ask-input").focus();
    };
    box.appendChild(button);
  }
}

function setLang(next) {
  if (next === lang) return;
  lang = next;
  localStorage.setItem("crossfire-lang", lang);
  applyStaticStrings();
  if (currentError) showError(currentError.key, ...currentError.args);
  if (currentRun) render(currentRun);
  repaintLive();
}





async function refreshRunList({ selectName = null, loadSelected = true } = {}) {
  const runs = await fetchJSON("/api/runs");
  const select = el("run-select");
  const previous = selectName || select.value;
  select.innerHTML = "";
  if (!runs.length) {
    showError("emptyRuns");
    if (loadSelected) el("content").classList.add("hidden");
    return [];
  }
  for (const run of runs) {
    const option = document.createElement("option");
    option.value = run.name;
    option.textContent = `${run.name} · ${run.pairer || t("pairerUnknown")}`;
    select.appendChild(option);
  }
  select.onchange = () => loadRun(select.value);
  const chosen =
    previous && [...select.options].some((opt) => opt.value === previous) ? previous : runs[0].name;
  select.value = chosen;
  if (loadSelected) await loadRun(chosen);
  return runs;
}

async function loadRuns() {
  await refreshRunList({ loadSelected: true });
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
  bindVerdictLang(lang);
  bindBottomLang(lang);
  bindHeroLang(lang);
  renderFailures(run);
  renderQuestion(run);
  renderHeroSubtitle(run, t);
  renderMetrics(run);
  const cards = renderSources(run);
  renderConflicts(run, cards);
  renderJudgment(run);
  renderVerdictPane(run, t, { renderSafeMarkdown, confidenceRing });
  renderBottomPanels(run, t);
  renderNliNote(run, t);
  renderGroupedEvidence(run, t);
  setEvidenceView(document.querySelector('#view-toggle button.active')?.dataset.view || "groups");
}

function partnerUrls(run, url) {
  const out = [];
  for (const pair of run.pairs || []) {
    if (pair.a === url) out.push(pair.b);
    if (pair.b === url) out.push(pair.a);
  }
  return out;
}

function renderMetrics(run) {
  renderSummaryMetrics(run, t);
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

function failureBucket(step, parse) {
  if (parse) return "model";
  const s = (step || "").toLowerCase();
  if (s === "fetch") return "fetch";
  if (s === "usability") return "usability";
  if (["extract", "pair", "judge", "pipeline"].includes(s)) return "model";
  return "model";
}

function normalizeFailure(failure) {
  if (!failure) return null;
  if (failure.parse) return { parse: true, stage: failure.stage, url: failure.url };
  if (typeof failure === "string") return { step: "", detail: failure, raw: null };
  if (failure.step != null && failure.detail != null) {
    return { step: failure.step, detail: failure.detail, raw: failure.raw ?? null };
  }
  const step = failure.stage || failure.step || "";
  const detail = [failure.url, failure.error || failure.message].filter(Boolean).join(" — ");
  return { step, detail: detail || step || JSON.stringify(failure), raw: failure.raw ?? null };
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
  const counts = { fetch: 0, usability: 0, model: 0 };
  for (const failure of failures) {
    const norm = normalizeFailure(failure);
    if (!norm) continue;
    const bucket = failureBucket(norm.step, Boolean(norm.parse));
    counts[bucket] += 1;
  }
  banner.innerHTML = "";
  const head = text("div", null);
  head.appendChild(
    text("strong", null, t("failureHeadBreakdown", counts.fetch, counts.usability, counts.model)),
  );
  banner.appendChild(head);
  const list = document.createElement("ul");
  for (const failure of failures) {
    const norm = normalizeFailure(failure);
    if (!norm) continue;
    if (norm.parse) {
      list.appendChild(text("li", null, t("parseFailure", norm.stage, norm.url)));
      continue;
    }
    const li = document.createElement("li");
    li.appendChild(text("span", null, t("stepError", norm.step, norm.detail)));
    if (norm.raw) {
      const details = document.createElement("details");
      details.appendChild(text("summary", null, "raw"));
      const pre = document.createElement("pre");
      pre.textContent = norm.raw;
      details.appendChild(pre);
      li.appendChild(details);
    }
    list.appendChild(li);
  }
  banner.appendChild(list);
  banner.classList.remove("hidden");
}

function pairerLabelFromRun(run) {
  const provenance = run.provenance;
  if (!provenance || typeof provenance !== "object") return t("pairerUnknown");
  const pair = provenance.pair;
  if (!pair || typeof pair !== "object") return t("pairerUnknown");
  if (pair.implementation === "nli") {
    const model = String(pair.model || "nli");
    const short =
      model.includes("/") || model.startsWith(".") ? model.split(/[/\\]/).filter(Boolean).pop() : model;
    const rev = pair.revision;
    if (typeof rev === "string" && rev) return `NLI · ${short} @ ${rev.slice(0, 7)}`;
    return `NLI · ${short}`;
  }
  const model = pair.model;
  if (typeof model === "string" && /claude/i.test(model)) return t("pairerClaude");
  if (pair.implementation === "claude") return t("pairerClaude");
  return t("pairerUnknown");
}

function provisionalProvenance() {
  if (pairer === "nli") {
    const opt = pairerOptions.find((o) => o.id === "nli") || {};
    return {
      pair: {
        implementation: "nli",
        model: opt.model || "nli",
        revision: opt.revision || null,
      },
    };
  }
  return { pair: { implementation: "claude", model: "claude" } };
}

function questionText(run) {
  const q = run.question;
  if (typeof q === "string") return q;
  if (q && typeof q === "object" && typeof q.text === "string") return q.text;
  return "";
}

function renderSafeMarkdown(target, raw) {
  // 先转义再恢复安全子集，见 web/static/safe_markdown.js（单元测试覆盖 XSS）。
  target.innerHTML = CrossfireSafeMarkdown.safeMarkdownHtml(raw);
}

function renderQuestion(run) {
  el("question").textContent = questionText(run) || t("noQuestion");
  const meta = el("run-meta");
  meta.innerHTML = "";
  const bits = [];
  if (run.question_id) bits.push(`ID ${run.question_id}`);
  if (run.started_at) bits.push(t("startedAt", run.started_at));
  if (run.elapsed_seconds !== undefined) bits.push(t("elapsed", run.elapsed_seconds));
  if (run.pages_fetched !== undefined) bits.push(t("fetched", run.pages_fetched));
  if (run.pages_failed) bits.push(t("fetchFailedCount", run.pages_failed));
  for (const bit of bits) meta.appendChild(text("span", null, bit));
  meta.appendChild(
    text("span", "pairer-meta", `${t("pairerLabel")} ${pairerLabelFromRun(run)}`),
  );
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
    const unusableReason = page.usable === false ? page.unusable_reason || null : null;
    return {
      url,
      tier: claim.tier || configuredSource.tier || null,
      title: page.title || null,
      claim: claim.claim || null,
      evidence: claim.evidence || null,
      sourceType: claim.source_type || null,
      publishedDate: claim.published_date || null,
      contentDate: claim.content_date || null,
      contentDateEvidence: claim.content_date_evidence || null,
      confidence: claim.confidence,
      extractFailed: Boolean(claim.failure),
      unusableReason,
      fetchError: page.ok === false && !unusableReason ? page.error || "" : null,
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
    if (row.unusableReason) {
      tags.appendChild(text("span", "tag conflict-flag", t("contentUnusable", row.unusableReason)));
    } else if (row.fetchError !== null) {
      tags.appendChild(text("span", "tag conflict-flag", t("fetchFailed")));
    }
    card.appendChild(tags);

    const emptyClaim = row.extractFailed ? t("extractFailed") : t("noClaim");
    const claimNode = text("div", row.claim ? "claim" : "claim empty", row.claim || emptyClaim);
    card.appendChild(labeled(t("claim"), claimNode));

    if (row.evidence) {
      card.appendChild(labeled(t("evidence"), text("blockquote", "evidence", row.evidence)));
    }
    if (row.fetchError) {
      card.appendChild(labeled(t("fetchFailed"), text("div", "claim empty", row.fetchError)));
    }

    const foot = text("div", "card-foot");
    if (row.publishedDate || row.contentDate) {
      if (row.publishedDate) {
        foot.appendChild(text("span", null, t("published", row.publishedDate)));
      }
      if (row.contentDate) {
        const contentNode = text("span", null, t("contentDated", row.contentDate));
        if (row.contentDateEvidence) contentNode.title = row.contentDateEvidence;
        foot.appendChild(contentNode);
      }
    } else {
      foot.appendChild(text("span", "unknown-date", t("dateUnknown")));
    }
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
  const all = run.pairs || [];
  const contradictions = all.filter((p) => p.relation === RELATION_CONTRADICT);
  const scoped = all.filter((p) => p.relation === RELATION_SCOPE);
  const unresolved = all.filter((p) => !p.relation).length;
  el("conflict-count").textContent = t("relationCount", contradictions.length, scoped.length);
  renderLegend(contradictions.length + scoped.length > LINK_CROWD_LIMIT);
  const hasScores = all.some((p) => p.scores && typeof p.scores === "object");
  el("scores-calibration").classList.toggle("hidden", !hasScores);

  for (const { card } of cards.values()) card.classList.remove("conflicted", "scoped");

  if (!contradictions.length) {
    const state = unresolved
      ? text("div", "empty-state partial", t("partialConflicts", unresolved))
      : text("div", "empty-state", t("noConflicts"));
    container.appendChild(state);
  } else {
    container.appendChild(conflictGroup(run, cards, contradictions, RELATION_CONTRADICT));
  }
  if (scoped.length) {
    container.appendChild(conflictGroup(run, cards, scoped, RELATION_SCOPE));
  }

  drawLinks([...contradictions, ...scoped], cards);
}

function conflictGroup(run, cards, pairs, relation) {
  const scope = relation === RELATION_SCOPE;
  const group = text("div", `conflict-group${scope ? " scope" : ""}`);
  group.appendChild(text("div", "group-title", t(scope ? "scopeGroup" : "contradictGroup")));

  const claims = run.claims || [];
  pairs.forEach((pair, i) => {
    const item = text("div", `conflict${scope ? " scope" : ""}`);
    const aInfo = cards.get(pair.a);
    const bInfo = cards.get(pair.b);
    if (aInfo) aInfo.card.classList.add(scope ? "scoped" : "conflicted");
    if (bInfo) bInfo.card.classList.add(scope ? "scoped" : "conflicted");

    const head = text("div", "conflict-pair");
    head.appendChild(text("span", null, `${scope ? "D" : "C"}${i + 1}`));
    head.appendChild(text("span", null, labelFor(pair.a, aInfo)));
    head.appendChild(text("span", "vs", scope ? "≠" : "VS"));
    head.appendChild(text("span", null, labelFor(pair.b, bInfo)));
    item.appendChild(head);

    const scoreTip = scoresTitle(pair.scores, pair.relation);
    if (scoreTip) item.title = scoreTip;

    item.appendChild(text("div", "conflict-nature", pair.nature || t("noNature")));
    appendScoreChips(item, pair.scores, pair.relation);

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
    group.appendChild(item);

    markPartner(aInfo, bInfo, relation);
    markPartner(bInfo, aInfo, relation);
  });
  return group;
}

function renderLegend(crowded) {
  const legend = el("conflict-legend");
  legend.innerHTML = "";
  for (const [key, className] of [
    ["legendContradict", "contradict"],
    ["legendScope", "scope"],
  ]) {
    const row = text("span", `legend-item ${className}`);
    row.appendChild(text("span", "legend-line"));
    row.appendChild(text("span", null, t(key)));
    legend.appendChild(row);
  }
  if (crowded) legend.appendChild(text("span", "legend-item hint", t("legendCrowded")));
}

function markPartner(target, partner, relation) {
  if (!target || !partner) return;
  const tags = target.card.querySelector(".tags");
  const scope = relation === RELATION_SCOPE;
  const label = t(scope ? "scopeWith" : "conflictWith", `S${partner.index + 1}`);
  if (!tags || [...tags.children].some((node) => node.textContent === label)) return;
  tags.appendChild(text("span", `tag ${scope ? "scope-flag" : "conflict-flag"}`, label));
}

function labelFor(url, info) {
  return info ? `S${info.index + 1} ${domainOf(url)}` : domainOf(url);
}

function scoresTitle(scores, topRelation) {
  if (!scores || typeof scores !== "object") return null;
  const lines = Object.entries(scores)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([label, value]) => {
      const mark = topRelation && label === topRelation ? " ←" : "";
      return `${label}: ${Number(value).toFixed(3)}${mark}`;
    });
  return `${t("scoresHint")}\n${lines.join("\n")}\n\n${t("scoresCalibrationHover")}`;
}

function appendScoreChips(parent, scores, topRelation) {
  if (!scores || typeof scores !== "object") return false;
  const row = text("div", "conflict-scores");
  const hint = text("span", "score-chip calib-hint", t("scoresCalibrationShort"));
  hint.title = t("scoresCalibrationHover");
  row.appendChild(hint);
  const entries = Object.entries(scores).sort((a, b) => Number(b[1]) - Number(a[1]));
  for (const [label, value] of entries) {
    const top = topRelation && label === topRelation;
    row.appendChild(
      text("span", `score-chip${top ? " top" : ""}`, `${label} ${Number(value).toFixed(3)}`),
    );
  }
  parent.appendChild(row);
  return true;
}

// The card whose links are being traced, so a redraw can restore the trace.
let tracedCard = null;

function spotlight(urls, cards, focus) {
  tracedCard = urls ? focus || null : null;
  for (const [url, { card }] of cards) {
    card.classList.toggle("dimmed", Boolean(urls) && !urls.includes(url));
  }
  const svg = el("conflict-links");
  svg.classList.toggle("tracing", Boolean(urls));
  for (const path of svg.querySelectorAll("path")) {
    const { a, b } = path.dataset;
    const traced =
      Boolean(urls) &&
      urls.includes(a) &&
      urls.includes(b) &&
      (!focus || a === focus || b === focus);
    path.classList.toggle("traced", traced);
  }
}

// Straight segments through the waypoints with rounded corners, so a routed
// link hugs the gutters instead of bulging back over the cards.
function elbowPath(points) {
  const r = 8;
  let d = `M ${points[0][0]} ${points[0][1]}`;
  for (let i = 1; i < points.length - 1; i += 1) {
    const [px, py] = points[i - 1];
    const [cx, cy] = points[i];
    const [nx, ny] = points[i + 1];
    const inLen = Math.hypot(cx - px, cy - py) || 1;
    const outLen = Math.hypot(nx - cx, ny - cy) || 1;
    const back = Math.min(r, inLen / 2);
    const ahead = Math.min(r, outLen / 2);
    d += ` L ${cx + ((px - cx) / inLen) * back} ${cy + ((py - cy) / inLen) * back}`;
    d += ` Q ${cx} ${cy}, ${cx + ((nx - cx) / outLen) * ahead} ${cy + ((ny - cy) / outLen) * ahead}`;
  }
  const last = points[points.length - 1];
  return `${d} L ${last[0]} ${last[1]}`;
}

function drawLinks(pairs, cards) {
  const svg = el("conflict-links");
  svg.innerHTML = "";
  // Every link drawn at full strength turns into a braid, so above the limit
  // they stay faint until a card or a pair is pointed at.
  svg.classList.toggle("crowded", pairs.length > LINK_CROWD_LIMIT);
  svg.classList.remove("tracing");
  const wrap = svg.parentElement.getBoundingClientRect();

  // Contradictions are painted last so they stay on top of the scope links.
  const ordered = [...pairs].sort(
    (p, q) => (p.relation === RELATION_CONTRADICT) - (q.relation === RELATION_CONTRADICT),
  );
  ordered.forEach((pair, order) => {
    const kind = pair.relation === RELATION_SCOPE ? "scope" : "contradict";
    const a = cards.get(pair.a);
    const b = cards.get(pair.b);
    if (!a || !b) return;
    const ra = a.card.getBoundingClientRect();
    const rb = b.card.getBoundingClientRect();
    const sameRow = Math.abs(ra.top - rb.top) < 4;
    const [left, right] = ra.left <= rb.left ? [ra, rb] : [rb, ra];
    const [upper, lower] = ra.top <= rb.top ? [ra, rb] : [rb, ra];
    // Fan the curves apart so links between the same two rows stay separable.
    const fan = ((order % 5) - 2) * 9;

    let d;
    let ends;
    const neighbours = sameRow && right.left - left.right < 40;
    if (neighbours) {
      const x1 = left.right - wrap.left;
      const y1 = left.top + left.height / 2 - wrap.top;
      const x2 = right.left - wrap.left;
      const y2 = right.top + right.height / 2 - wrap.top;
      const bow = Math.min(30, (x2 - x1) / 2 + 6);
      d = `M ${x1} ${y1} C ${x1 + bow} ${y1}, ${x2 - bow} ${y2}, ${x2} ${y2}`;
      ends = [[x1, y1], [x2, y2]];
    } else if (sameRow) {
      // Going straight across would run behind the cards in between, so dip
      // into the empty gutter under the row instead.
      const x1 = left.left + left.width / 2 - wrap.left;
      const x2 = right.left + right.width / 2 - wrap.left;
      const y = left.bottom - wrap.top;
      const dip = Math.min(32, 16 + Math.abs(fan));
      d = `M ${x1} ${y} C ${x1} ${y + dip}, ${x2} ${y + dip}, ${x2} ${y}`;
      ends = [[x1, y], [x2, y]];
    } else {
      const x1 = upper.left + upper.width / 2 - wrap.left;
      const y1 = upper.bottom - wrap.top;
      const x2 = lower.left + lower.width / 2 - wrap.left;
      const y2 = lower.top - wrap.top;
      if (lower.top - upper.bottom > 60) {
        // Rows that are not neighbours have a whole row of cards in between,
        // so the link runs along the gutters and down the margin beside the
        // grid rather than straight through those cards.
        const g1 = y1 + 18;
        const g2 = y2 - 18;
        const step = (order % 3) * 4;
        const lane = x1 + x2 < wrap.width ? -9 - step : wrap.width + 9 + step;
        d = elbowPath([
          [x1, y1],
          [x1, g1],
          [lane, g1],
          [lane, g2],
          [x2, g2],
          [x2, y2],
        ]);
      } else {
        const drop = Math.max(10, (y2 - y1) / 2);
        d = `M ${x1} ${y1} C ${x1 + fan} ${y1 + drop}, ${x2 + fan} ${y2 - drop}, ${x2} ${y2}`;
      }
      ends = [[x1, y1], [x2, y2]];
    }

    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("class", `link-${kind}`);
    path.setAttribute("d", d);
    path.dataset.a = pair.a;
    path.dataset.b = pair.b;
    const scoreTip = scoresTitle(pair.scores, pair.relation);
    if (scoreTip) path.setAttribute("title", scoreTip);
    svg.appendChild(path);
    for (const info of [a, b]) {
      info.card.onmouseenter = () => traceFromCard(info.card.dataset.url, cards);
      info.card.onmouseleave = () => spotlight(null, cards);
    }
    for (const [cx, cy] of ends) {
      const dot = document.createElementNS(SVG_NS, "circle");
      dot.setAttribute("class", `link-${kind}`);
      dot.setAttribute("cx", String(cx));
      dot.setAttribute("cy", String(cy));
      dot.setAttribute("r", "3");
      svg.appendChild(dot);
    }
  });

  // A redraw while the pointer sits on a card gets no fresh mouseenter.
  if (tracedCard && cards.has(tracedCard)) traceFromCard(tracedCard, cards);
}

function traceFromCard(url, cards) {
  const svg = el("conflict-links");
  const partners = new Set([url]);
  for (const path of svg.querySelectorAll("path")) {
    if (path.dataset.a === url) partners.add(path.dataset.b);
    if (path.dataset.b === url) partners.add(path.dataset.a);
  }
  spotlight(partners.size > 1 ? [...partners] : null, cards, url);
}

function renderJudgment(run) {
  const container = el("judgment");
  container.innerHTML = "";
  const judgment = run.judgment || {};

  const main = text("div", null);
  const answer = text("div", "answer");
  renderSafeMarkdown(answer, judgment.answer || t("noVerdict"));
  main.appendChild(answer);
  if (judgment.reasoning) {
    const reasoning = text("div", "reasoning");
    renderSafeMarkdown(reasoning, judgment.reasoning);
    main.appendChild(labeled(t("reasoning"), reasoning));
  }
  if ("conflicts" in judgment && !Array.isArray(judgment.conflicts)) {
    main.appendChild(text("div", "format-warning", t("formatWarningConflicts")));
  } else if (Array.isArray(judgment.conflicts) && judgment.conflicts.length) {
    const list = document.createElement("ul");
    list.className = "judge-conflicts";
    for (const conflict of judgment.conflicts) list.appendChild(text("li", null, conflict));
    main.appendChild(labeled(t("recordedConflicts"), list));
  }
  if ("trusted_sources" in judgment && !Array.isArray(judgment.trusted_sources)) {
    main.appendChild(text("div", "format-warning", t("formatWarningTrusted")));
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
  const color = value === null ? "#6b6560" : value >= 0.75 ? "#2f6b3a" : value >= 0.45 ? "#9a6b16" : "#b71c2b";

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
  const targetOffset = circumference * (1 - (value ?? 0));
  if (prefersReducedMotion()) {
    arc.setAttribute("stroke-dashoffset", String(targetOffset));
  } else {
    arc.setAttribute("stroke-dashoffset", String(circumference));
    requestAnimationFrame(() => {
      arc.style.transition = "stroke-dashoffset 400ms cubic-bezier(0.2, 0.8, 0.2, 1)";
      arc.setAttribute("stroke-dashoffset", String(targetOffset));
    });
  }
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

const STALL_TIMEOUT_MS = 30000;
const FLASH_MS = 220;
const FAKE_SCENARIO = new URLSearchParams(location.search).get("fake");
const FAKE_SPEED = new URLSearchParams(location.search).get("speed") || "1";

let mode = "cached";
let pairer = "claude";
let pairerOptions = [];

const live = {
  active: false,
  asking: false,
  abort: null,
  stream: null,
  slots: [],
  cards: new Map(),
  pairs: new Map(),
  totalSources: 0,
  totalPairs: 0,
  fetched: 0,
  claimed: 0,
  judged: false,
  judging: false,
  question: "",
  errors: [],
  stage: null,
  startedAt: 0,
  timer: null,
  stall: null,
  sourceFind: [],
};

function setMode(next) {
  mode = next === "live" ? "live" : "cached";
  for (const button of document.querySelectorAll("#mode-toggle button")) {
    button.classList.toggle("active", button.dataset.mode === mode);
  }
}

function setPairer(next) {
  pairer = next === "nli" ? "nli" : "claude";
  for (const button of document.querySelectorAll("#pairer-toggle button")) {
    button.classList.toggle("active", button.dataset.pairer === pairer);
  }
}

async function loadPairers() {
  try {
    const data = await fetchJSON("/api/pairers");
    pairerOptions = data.options || [];
    pairer = data.default || "claude";
    const selected = pairerOptions.find((o) => o.id === pairer);
    if (selected && !selected.available) pairer = "claude";
    for (const button of document.querySelectorAll("#pairer-toggle button")) {
      const id = button.dataset.pairer;
      const opt = pairerOptions.find((o) => o.id === id);
      const available = opt ? Boolean(opt.available) : id === "claude";
      button.disabled = !available;
      button.title = !available && opt?.reason ? t("pairerUnavailable", opt.reason) : "";
    }
    setPairer(pairer);
    applyStaticStrings();
  } catch {
    setPairer(pairer);
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
  if (live.abort) live.abort.abort();
  live.abort = null;
  live.active = false;
  live.asking = false;
  stopTimer();
  clearStall();
  el("run-button").textContent = t("runButton");
  el("run-button").classList.remove("running");
  el("ask-button").textContent = t("askButton");
  el("ask-button").classList.remove("running");
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
  live.judging = false;
  live.question = "";
  live.errors = [];
  live.stage = null;
  live.sourceFind = [];
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
  el("source-find-panel").classList.add("hidden");
  el("source-find-list").innerHTML = "";
  el("source-find-count").textContent = "";
}

function streamUrl(questionId) {
  if (FAKE_SCENARIO) {
    return `/api/fake-run/${encodeURIComponent(FAKE_SCENARIO)}?speed=${encodeURIComponent(FAKE_SPEED)}`;
  }
  return `/api/run/${encodeURIComponent(questionId)}?mode=${mode}&pairer=${encodeURIComponent(pairer)}`;
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
    case "source_search_start":
      onSourceSearchStart(event);
      break;
    case "source_candidate":
      onSourceCandidate(event);
      break;
    case "source_filtered":
      onSourceFiltered(event);
      break;
    case "sources_ready":
      onSourcesReady(event);
      break;
    case "sources_insufficient":
    case "ask_cost_rejected":
    case "ask_stopped":
      onAskStopped(event);
      break;
    case "ask_finished":
      break;
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
    case "heartbeat":
      // Keeps the stall timer alive through the long judge call; nothing to draw.
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

function paintSourceFind() {
  const list = el("source-find-list");
  list.innerHTML = "";
  el("source-find-panel").classList.remove("hidden");
  el("source-find-count").textContent = t("sourceFindCount", live.sourceFind.length);
  for (const item of live.sourceFind) {
    const row = document.createElement("li");
    row.className = item.kind === "filtered" ? "sf-filtered" : item.kind === "ready" ? "sf-ready" : "";
    const tag = text(
      "span",
      "sf-tag",
      item.kind === "filtered"
        ? t("sourceFindFiltered")
        : item.kind === "ready"
          ? t("sourceFindReady")
          : t("sourceFindCandidate"),
    );
    const body = text(
      "span",
      "sf-body",
      item.kind === "filtered"
        ? `${domainOf(item.url)} — ${item.reason}${item.detail ? ` (${item.detail})` : ""}`
        : item.kind === "ready"
          ? `${item.count} sources · primary: ${item.has_primary ? "yes" : "no"}`
          : `[${item.tier}] ${item.title || domainOf(item.url)}`,
    );
    row.appendChild(tag);
    row.appendChild(body);
    list.appendChild(row);
  }
}

function onSourceSearchStart(event) {
  live.question = event.question || live.question;
  el("question").textContent = live.question || t("noQuestion");
  el("content").classList.remove("hidden");
  setStage("stageSearching");
  live.sourceFind = [];
  paintSourceFind();
}

function onSourceCandidate(event) {
  live.sourceFind.push({
    kind: "candidate",
    url: event.url,
    title: event.title,
    tier: event.tier,
  });
  paintSourceFind();
}

function onSourceFiltered(event) {
  live.sourceFind.push({
    kind: "filtered",
    url: event.url,
    reason: event.reason,
    detail: event.detail,
  });
  paintSourceFind();
}

function onSourcesReady(event) {
  live.sourceFind.push({
    kind: "ready",
    count: event.count,
    has_primary: event.has_primary,
    urls: event.urls || [],
  });
  paintSourceFind();
  setStage("stageSourcesReady", event.count || 0);
}

function onAskStopped(event) {
  const detail = event.detail || "";
  if (event.type === "ask_cost_rejected" || event.reason === "cost_limit") {
    showError("askStoppedCost", detail || t("askOverBudget", event.total_usd || 0, event.max_cost_usd || 0));
  } else if (event.reason === "too_few_sources" || event.type === "sources_insufficient") {
    showError("askStoppedFew", detail);
  } else if (event.type === "ask_stopped") {
    showError("askStoppedOther", detail);
  }
}

function onStart(event) {
  live.question = event.question || "";
  live.totalSources = event.total_sources || 0;
  live.totalPairs = (live.totalSources * (live.totalSources - 1)) / 2;
  el("question").textContent = live.question || t("noQuestion");
  el("source-count").textContent = t("sourceCount", live.totalSources);
  el("conflict-count").textContent = t("relationCount", 0, 0);
  buildSkeletons(live.totalSources);
  renderGroupsProcessing(live.slots, t);
  setEvidenceView("groups");
  setStage("stageFetching", 0, live.totalSources);
  updateProgress();
}

function buildSkeletons(count) {
  const container = el("sources");
  container.innerHTML = "";
  live.slots = [];
  for (let index = 0; index < count; index += 1) {
    const card = text("div", "card");
    card.dataset.index = String(index);
    container.appendChild(card);
    const slot = {
      card,
      index,
      url: null,
      tier: null,
      claim: null,
      claimed: false,
      ok: null,
      chars: 0,
      fetchCounted: false,
      claimCounted: false,
      unusableReason: null,
      extractFailed: false,
    };
    live.slots.push(slot);
    paintSlot(slot);
  }
}

// One place that turns a slot's current state into DOM, so every stage of the
// run (and a mid-run language switch) renders from the same state.
function paintSlot(slot) {
  const card = slot.card;
  card.innerHTML = "";
  card.className = "card";
  if (!slot.url) card.classList.add("card-skeleton");
  else card.classList.add(slot.claimed ? "card-done" : "card-fetched");
  if (slot.ok === false) card.classList.add("card-failed");

  const head = text("div", "card-head");
  const domain = text("div", "domain");
  if (slot.url) {
    const link = document.createElement("a");
    link.href = slot.url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = domainOf(slot.url);
    domain.appendChild(link);
  } else {
    domain.textContent = "—";
  }
  head.appendChild(domain);
  head.appendChild(text("span", "card-index", `S${slot.index + 1}`));
  card.appendChild(head);

  const tags = text("div", "tags");
  if (!slot.url) {
    tags.appendChild(text("span", "tag unknown", t("pendingSource")));
  } else if (slot.claimed) {
    tags.appendChild(text("span", `tag ${tierClass(slot.tier)}`, slot.tier || "unknown"));
  } else if (slot.ok !== false) {
    tags.appendChild(text("span", "tag plain", t("fetchedChars", slot.chars)));
  }
  if (slot.unusableReason) {
    tags.appendChild(text("span", "tag conflict-flag", t("contentUnusable", slot.unusableReason)));
  } else if (slot.ok === false) {
    tags.appendChild(text("span", "tag conflict-flag", t("fetchFailed")));
  }
  card.appendChild(tags);

  if (slot.claimed) {
    const emptyClaim = slot.extractFailed ? t("extractFailed") : t("noClaim");
    const block = labeled(t("claim"), text("div", slot.claim ? "claim" : "claim empty", slot.claim || emptyClaim));
    block.className = "claim-block";
    card.appendChild(block);
  } else {
    const body = text("div", "skeleton-body");
    for (const width of ["92%", "78%", "60%"]) {
      const bar = text("div", "skeleton-bar");
      bar.style.width = width;
      body.appendChild(bar);
    }
    card.appendChild(body);
  }
}

// A language switch during a run has to repaint everything already on screen.
function repaintLive() {
  if (live.active) renderGroupsProcessing(live.slots, t);

  if (!live.active) return;
  el("question").textContent = live.question || t("noQuestion");
  el("source-count").textContent = t("sourceCount", live.totalSources);
  for (const slot of live.slots) paintSlot(slot);
  if (live.pairs.size || !el("pair-progress").classList.contains("hidden")) {
    el("pair-progress").textContent = t("pairProgress", live.pairs.size, live.totalPairs);
  }
  renderLiveConflicts();
  if (live.errors.length) onStepErrorRender();
  if (live.judging) onJudgeStart();
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
  slot.unusableReason = event.unusable_reason || null;
  slot.card.dataset.url = event.url;
  live.cards.set(event.url, { card: slot.card, index: slot.index });
  // A source that failed to fetch never produces a claim, so it is already in
  // its final state.
  if (!slot.ok) slot.claimed = true;
  paintSlot(slot);
  flash(slot.card);

  if (!slot.fetchCounted) {
    slot.fetchCounted = true;
    live.fetched += 1;
  }
  if (!slot.ok && !slot.claimCounted) {
    slot.claimCounted = true;
    live.claimed += 1;
  }
  setStage("stageFetching", live.fetched, live.totalSources);
  updateProgress();
}

function onClaimDone(event) {
  const slot = slotAt(event.index);
  if (!slot) return;
  slot.claim = event.claim || null;
  slot.tier = event.tier || null;
  slot.extractFailed = Boolean(event.failed);
  if (!slot.url) {
    slot.url = event.url;
    slot.card.dataset.url = event.url;
    live.cards.set(event.url, { card: slot.card, index: slot.index });
  }

  slot.claimed = true;
  paintSlot(slot);
  flash(slot.card);

  if (!slot.claimCounted) {
    slot.claimCounted = true;
    live.claimed += 1;
  }
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
    scores: event.scores ?? null,
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
  renderConflicts({ pairs: orderedPairs(), claims: claimRows() }, live.cards);
}

function claimRows() {
  return live.slots
    .filter((slot) => slot.url)
    .map((slot) => {
      const row = { url: slot.url, claim: slot.claim, tier: slot.tier };
      if (slot.extractFailed) row.failure = { step: "extract", detail: "", raw: null };
      return row;
    });
}

function onJudgeStart() {
  live.judging = true;
  setStage("stageJudging");
  const container = el("judgment");
  container.innerHTML = "";
  container.appendChild(text("div", "thinking", t("thinking")));
}

function onDone(event) {
  live.judged = true;
  live.judging = false;
  updateProgress();
  setStage("stageDone");
  stopLive();
  if (event.ask_stopped) {
    el("pair-progress").classList.add("hidden");
    return;
  }
  currentRun = {
    question: live.question,
    elapsed_seconds: event.elapsed,
    run_file: event.run_file,
    provenance: provisionalProvenance(),
    sources: live.slots.filter((s) => s.url).map((s) => ({ url: s.url, tier: s.tier })),
    pages: live.slots.filter((s) => s.url).map((s) => ({
      url: s.url,
      ok: s.ok !== false,
      error: s.ok === false ? s.unusableReason || "" : "",
      usable: !s.unusableReason,
      unusable_reason: s.unusableReason || "",
    })),
    claims: claimRows(),
    pairs: orderedPairs(),
    judgment: event.judgment || null,
    failures: live.errors.map((e) => ({ step: e.step, detail: e.detail })),
  };
  render(currentRun);
  el("pair-progress").classList.add("hidden");
  // 结果文件里有完整 provenance（含 NLI revision）。假剧本的 run_file 可能不存在，失败时保留上面的合成结果。
  if (event.run_file) {
    const name = String(event.run_file).split(/[/\\]/).pop();
    if (name) {
      fetchJSON(`/api/runs/${encodeURIComponent(name)}`)
        .then((run) => {
          currentRun = run;
          hideError();
          render(run);
          // 只刷新历史下拉，避免 loadRuns → loadRun 再清一次画面抢掉刚补上的 provenance。
          return refreshRunList({ selectName: name, loadSelected: false });
        })
        .catch(() => {});
    }
  }
}

function onStepError(event) {
  live.errors.push({ step: event.step, detail: event.detail });
  onStepErrorRender();
}

function onStepErrorRender() {
  renderFailures({ failures: live.errors.map((e) => ({ step: e.step, detail: e.detail })) });
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
  drawLinks(
    (currentRun.pairs || []).filter(
      (p) => p.relation === RELATION_CONTRADICT || p.relation === RELATION_SCOPE,
    ),
    cards,
  );
});

for (const button of document.querySelectorAll("#lang-toggle button, #lang-toggle-top button")) {
  button.onclick = () => setLang(button.dataset.lang);
}
for (const button of document.querySelectorAll("#mode-toggle button")) {
  button.onclick = () => setMode(button.dataset.mode);
}
for (const button of document.querySelectorAll("#pairer-toggle button")) {
  button.onclick = () => {
    if (!button.disabled) setPairer(button.dataset.pairer);
  };
}
el("run-button").onclick = startRun;
el("stall-switch").onclick = switchToCached;
el("ask-button").onclick = () => requestAsk();
el("ask-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    requestAsk();
  }
});
el("ask-cancel").onclick = closeAskDialog;
el("ask-confirm").onclick = () => {
  const pending = askPending;
  closeAskDialog();
  if (pending) startAsk(pending.question, pending.pairer);
};
el("ask-open").onclick = () => openAskDialog();
el("view-detail-cta").onclick = () => {
  el("detail-section").scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth" });
};
for (const button of document.querySelectorAll("#view-toggle button")) {
  button.onclick = () => {
    const next = button.dataset.view === "table" ? "table" : "groups";
    setEvidenceView(next);
  };
}
el("sidebar-toggle").onclick = () => {
  const sidebar = el("sidebar");
  const open = !sidebar.classList.contains("open");
  sidebar.classList.toggle("open", open);
  el("sidebar-toggle").setAttribute("aria-expanded", open ? "true" : "false");
};
el("history-filter").addEventListener("input", () => filterHistory());

let askPending = null;

function openAskDialog() {
  el("ask-panel").classList.remove("hidden");
  el("ask-confirm-block").classList.add("hidden");
  el("ask-confirm").classList.add("hidden");
  el("ask-button").classList.remove("hidden");
  el("ask-dialog").classList.remove("hidden");
  el("ask-input").focus();
}

function closeAskDialog() {
  askPending = null;
  el("ask-dialog").classList.add("hidden");
  el("ask-confirm-block").classList.add("hidden");
  el("ask-confirm").classList.add("hidden");
  el("ask-panel").classList.remove("hidden");
  el("ask-button").classList.remove("hidden");
}

function filterHistory() {
  const q = (el("history-filter").value || "").trim().toLowerCase();
  for (const option of el("run-select").options) {
    const hay = `${option.textContent || ""} ${option.value || ""}`.toLowerCase();
    option.hidden = Boolean(q) && !hay.includes(q);
  }
}

async function requestAsk() {
  if (live.active) return;
  const question = el("ask-input").value.trim() || t("askExample1");
  if (!el("ask-input").value.trim()) el("ask-input").value = question;
  hideError();
  if (FAKE_SCENARIO) {
    askPending = { question, pairer };
    el("ask-dialog-question").textContent = question;
    el("ask-dialog-estimate").textContent = t("askDialogEstimate", 0.39, 0.63, 4, 8, 1.0);
    const pairerName = pairer === "nli" ? t("pairerNli") : t("pairerClaude");
    el("ask-dialog-pairer").textContent = t("askDialogPairer", pairerName, pairer === "nli");
    el("ask-confirm-block").classList.remove("hidden");
    el("ask-confirm").classList.remove("hidden");
    el("ask-dialog").classList.remove("hidden");
    return;
  }
  try {
    const response = await fetch("/api/ask/estimate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, pairer }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `${response.status}`);
    const estimate = body.estimate || {};
    if (estimate.over_budget) {
      showError("askOverBudget", estimate.low_usd || estimate.total_usd || 0, estimate.max_cost_usd || 0);
      return;
    }
    askPending = { question: body.question || question, pairer: body.pairer || pairer };
    el("ask-dialog-question").textContent = askPending.question;
    el("ask-dialog-estimate").textContent = t(
      "askDialogEstimate",
      Number(estimate.low_usd ?? estimate.total_usd ?? 0),
      Number(estimate.high_usd ?? estimate.total_usd ?? 0),
      Number(estimate.low_sources || 4),
      Number(estimate.high_sources || 8),
      Number(estimate.max_cost_usd || 1),
    );
    const pairerName = askPending.pairer === "nli" ? t("pairerNli") : t("pairerClaude");
    el("ask-dialog-pairer").textContent = t("askDialogPairer", pairerName, Boolean(estimate.pairer_free));
    el("ask-confirm-block").classList.remove("hidden");
    el("ask-confirm").classList.remove("hidden");
    el("ask-dialog").classList.remove("hidden");
  } catch (e) {
    showError("loadFailed", "ask/estimate", e.message);
  }
}

async function startAsk(question, runPairer) {
  resetLive();
  live.active = true;
  live.asking = true;
  live.question = question;
  el("content").classList.remove("hidden");
  el("progress-strip").classList.remove("hidden");
  el("ask-button").textContent = t("askAsking");
  el("ask-button").classList.add("running");
  setStage("stageConnecting");
  startTimer();
  armStall();

  if (FAKE_SCENARIO) {
    const stream = new EventSource(
      `/api/fake-run/${encodeURIComponent(FAKE_SCENARIO)}?speed=${encodeURIComponent(FAKE_SPEED)}`,
    );
    live.stream = stream;
    stream.onmessage = (message) => {
      armStall();
      try {
        handleEvent(JSON.parse(message.data));
      } catch {
        /* ignore */
      }
    };
    stream.onerror = () => {
      if (!live.active) return;
      stopLive();
      showError("streamFailed");
    };
    return;
  }

  const controller = new AbortController();
  live.abort = controller;
  try {
    const response = await fetch("/api/ask/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, pairer: runPairer }),
      signal: controller.signal,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `${response.status}`);
    }
    await readSseStream(response.body, (event) => {
      armStall();
      handleEvent(event);
    });
  } catch (e) {
    if (controller.signal.aborted) return;
    stopLive();
    showError("streamFailed");
  }
}

async function readSseStream(body, onEvent) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    for (const chunk of chunks) {
      const line = chunk.split("\n").find((row) => row.startsWith("data: "));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(6)));
      } catch {
        /* ignore malformed */
      }
    }
  }
}

// Demo escape hatch: Ctrl+Alt+C drops back to cached mode mid-run.
window.addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.altKey && event.code === "KeyC") {
    event.preventDefault();
    switchToCached();
  }
});

setMode("cached");
applyStaticStrings();
setEvidenceView("groups");
loadQuestions().catch(() => {});
loadPairers().catch(() => {});
loadRuns().catch((e) => showError("listFailed", e.message));
