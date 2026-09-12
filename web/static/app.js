const el = (id) => document.getElementById(id);
const SVG_NS = "http://www.w3.org/2000/svg";

let currentRun = null;

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
    showError("out/runs/ 下没有找到任何 JSON 结果文件。");
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
  try {
    currentRun = await fetchJSON(`/api/runs/${encodeURIComponent(name)}`);
    hideError();
    render(currentRun);
  } catch (e) {
    showError(`读取 ${name} 失败：${e.message}`);
    el("content").classList.add("hidden");
  }
}

function showError(message) {
  const banner = el("error-banner");
  banner.textContent = message;
  banner.classList.remove("hidden");
}

function hideError() {
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

function renderFailures(run) {
  const banner = el("failure-banner");
  const failures = Array.isArray(run.failures) ? run.failures : run.failures ? [run.failures] : [];
  if (!failures.length) {
    banner.classList.add("hidden");
    banner.innerHTML = "";
    return;
  }
  banner.innerHTML = "";
  const head = text("div", null);
  head.appendChild(text("strong", null, `本次运行有 ${failures.length} 次调用失败，结果可能不完整。`));
  banner.appendChild(head);
  const list = document.createElement("ul");
  for (const failure of failures) {
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
  el("question").textContent = run.question || "(无问题原文)";
  const meta = el("run-meta");
  meta.innerHTML = "";
  const bits = [];
  if (run.question_id) bits.push(`ID ${run.question_id}`);
  if (run.started_at) bits.push(`开始于 ${run.started_at}`);
  if (run.elapsed_seconds !== undefined) bits.push(`耗时 ${run.elapsed_seconds}s`);
  if (run.pages_fetched !== undefined) bits.push(`抓取成功 ${run.pages_fetched}`);
  if (run.pages_failed) bits.push(`抓取失败 ${run.pages_failed}`);
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
  el("source-count").textContent = `${rows.length} 个来源`;

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

    const claimNode = text("div", row.claim ? "claim" : "claim empty", row.claim || "该来源未就此问题给出主张");
    card.appendChild(labeled("主张", claimNode));

    if (row.evidence) {
      card.appendChild(labeled("证据原文", text("blockquote", "evidence", row.evidence)));
    }
    if (row.fetchError) {
      card.appendChild(labeled("抓取失败", text("div", "claim empty", row.fetchError)));
    }

    const foot = text("div", "card-foot");
    const dateNode = text(
      "span",
      row.publishedDate ? null : "unknown-date",
      `发布日期 ${row.publishedDate || "unknown"}`,
    );
    foot.appendChild(dateNode);
    if (typeof row.confidence === "number") {
      foot.appendChild(text("span", null, `来源置信度 ${Math.round(row.confidence * 100)}%`));
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
  el("conflict-count").textContent = pairs.length ? `${pairs.length} 处矛盾` : "0 处矛盾";

  for (const { card } of cards.values()) card.classList.remove("conflicted");

  if (!pairs.length) {
    container.appendChild(text("div", "empty-state", "未发现矛盾 — 各来源之间没有互相抵触的主张"));
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

    item.appendChild(text("div", "conflict-nature", pair.nature || "（未说明差异所在）"));

    const claimA = claims.find((c) => c.url === pair.a);
    const claimB = claims.find((c) => c.url === pair.b);
    if (claimA || claimB) {
      const grid = text("div", "conflict-claims");
      grid.appendChild(text("div", null, `${domainOf(pair.a)}：${(claimA && claimA.claim) || "—"}`));
      grid.appendChild(text("div", null, `${domainOf(pair.b)}：${(claimB && claimB.claim) || "—"}`));
      item.appendChild(grid);
    }

    item.onmouseenter = () => spotlight([pair.a, pair.b], cards);
    item.onmouseleave = () => spotlight(null, cards);
    container.appendChild(item);
  });

  drawLinks(pairs, cards);
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
    const x1 = ra.left + ra.width / 2 - wrap.left;
    const y1 = ra.top - wrap.top;
    const x2 = rb.left + rb.width / 2 - wrap.left;
    const y2 = rb.top - wrap.top;
    const lift = Math.min(46, 14 + Math.abs(x2 - x1) / 8);
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute(
      "d",
      `M ${x1} ${y1} C ${x1} ${y1 - lift}, ${x2} ${y2 - lift}, ${x2} ${y2}`,
    );
    svg.appendChild(path);
  }
}

function renderJudgment(run) {
  const container = el("judgment");
  container.innerHTML = "";
  const judgment = run.judgment || {};

  const main = text("div", null);
  main.appendChild(text("div", "answer", judgment.answer || "（本次运行没有给出结论）"));
  if (judgment.reasoning) {
    main.appendChild(labeled("判断理由", text("div", "reasoning", judgment.reasoning)));
  }
  if (Array.isArray(judgment.conflicts) && judgment.conflicts.length) {
    const list = document.createElement("ul");
    list.className = "judge-conflicts";
    for (const conflict of judgment.conflicts) list.appendChild(text("li", null, conflict));
    main.appendChild(labeled("结论中记录的分歧", list));
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
    trusted.appendChild(text("div", "claim empty", "未记录采信来源"));
  }
  main.appendChild(labeled("采信来源", trusted));
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
  wrap.appendChild(text("div", "ring-label", "置信度"));
  return wrap;
}

window.addEventListener("resize", () => {
  if (!currentRun) return;
  const cards = new Map();
  document.querySelectorAll(".card").forEach((card, index) => cards.set(card.dataset.url, { card, index }));
  drawLinks((currentRun.pairs || []).filter((p) => p.relation === "contradict"), cards);
});

loadRuns().catch((e) => showError(`加载运行列表失败：${e.message}`));
