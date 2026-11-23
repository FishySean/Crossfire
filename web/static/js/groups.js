import { domainOf, el, prefersReducedMotion, text, truncate } from "./dom.js";

const COLUMN_DEFS = [
  { id: "trusted", className: "ok", labelKey: "groupTrusted" },
  { id: "faulty", className: "danger", labelKey: "groupFaulty" },
  { id: "scope", className: "scope", labelKey: "groupScope" },
  { id: "neutral", className: "neutral", labelKey: "groupNeutral" },
  { id: "failed", className: "danger", labelKey: "groupFailed", hideIfEmpty: true },
  { id: "processing", className: "neutral", labelKey: "groupProcessing", hideIfEmpty: true },
];

function summarySources(run) {
  if (run?.summary?.sources?.length) return run.summary.sources;
  const sources = run?.sources || [];
  return sources.map((s) => ({
    url: s.url,
    domain: domainOf(s.url),
    status: "neutral",
    reason: null,
    key_value: null,
    claim: null,
    tier: s.tier || null,
    source_type: null,
    content_date: null,
  }));
}

function pathLabel(url) {
  try {
    const u = new URL(url);
    const parts = u.pathname.split("/").filter(Boolean);
    return parts.length ? decodeURIComponent(parts[parts.length - 1]).replace(/_/g, " ") : "";
  } catch {
    return "";
  }
}

/** en.wikipedia.org → wikipedia；cnbc.com → cnbc */
function shortSite(domain) {
  const host = String(domain || "").replace(/^www\./, "");
  const parts = host.split(".").filter(Boolean);
  if (parts.length >= 2) return parts[parts.length - 2];
  return host || domain;
}

function decorateRows(rows) {
  const domainCount = {};
  for (const row of rows) {
    const d = row.domain || domainOf(row.url);
    domainCount[d] = (domainCount[d] || 0) + 1;
  }
  const seenPage = {};
  return rows.map((row, index) => {
    const domain = row.domain || domainOf(row.url);
    let pageLabel = "";
    if (domainCount[domain] > 1) {
      const leaf = pathLabel(row.url) || `S${index + 1}`;
      pageLabel = `${shortSite(domain)} · ${leaf}`;
      seenPage[pageLabel] = (seenPage[pageLabel] || 0) + 1;
      if (seenPage[pageLabel] > 1) pageLabel = `${pageLabel} · S${index + 1}`;
    }
    return { ...row, domain, pageLabel };
  });
}

function pairsFor(run, url) {
  const out = [];
  for (const pair of run.pairs || []) {
    if (pair.a !== url && pair.b !== url) continue;
    const other = pair.a === url ? pair.b : pair.a;
    const conf =
      pair.scores && pair.relation && typeof pair.scores[pair.relation] === "number"
        ? pair.scores[pair.relation]
        : null;
    out.push({ other, relation: pair.relation || "?", confidence: conf });
  }
  return out;
}

export function setEvidenceView(view) {
  const groups = view !== "table";
  el("groups-view").classList.toggle("hidden", !groups);
  el("table-view").classList.toggle("hidden", groups);
  for (const button of document.querySelectorAll("#view-toggle button")) {
    const active = button.dataset.view === (groups ? "groups" : "table");
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  }
}

function buildCard(row, run, t) {
  const card = text("article", `group-card status-${row.status || "neutral"}`);
  card.dataset.url = row.url;
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  card.setAttribute("aria-expanded", "false");

  // 域名单独一行；区分标签单独一行；tier 在域名下方 —— 避免和域名抢宽。
  const domainLine = text("div", "group-card-domain", row.domain || domainOf(row.url));
  domainLine.title = row.url;
  card.appendChild(domainLine);
  if (row.pageLabel) {
    card.appendChild(text("div", "group-card-page", row.pageLabel));
  }
  if (row.tier) {
    card.appendChild(text("div", "group-card-tier", null)).appendChild(
      text("span", `tag ${row.tier}`, row.tier),
    );
  }

  const body = text("div", "group-card-body");
  const key = row.key_value || (row.claim ? truncate(row.claim, 120) : "");
  if (key) body.appendChild(text("div", "group-card-key", key));
  if (row.content_date) body.appendChild(text("div", "group-card-date", row.content_date));
  if (row.status === "processing") body.appendChild(text("div", "group-card-key shimmer-bar", "…"));
  card.appendChild(body);

  const detail = text("div", "group-card-detail hidden");
  if (row.claim) detail.appendChild(text("div", "claim", row.claim));
  if (row.reason) detail.appendChild(text("div", "claim empty", row.reason));
  const related = pairsFor(run, row.url);
  if (related.length) {
    const list = document.createElement("ul");
    list.className = "group-card-pairs";
    for (const item of related) {
      const li = document.createElement("li");
      const conf = item.confidence;
      const low = conf != null && conf < 0.5;
      if (low) li.className = "pair-uncertain";
      li.textContent = t("pairWith", domainOf(item.other), item.relation, conf, low);
      list.appendChild(li);
    }
    detail.appendChild(list);
  } else if (row.status !== "processing") {
    detail.appendChild(text("div", "claim empty", t("groupNoPairs")));
  }
  card.appendChild(detail);

  const toggle = () => {
    const open = detail.classList.contains("hidden");
    detail.classList.toggle("hidden", !open);
    card.setAttribute("aria-expanded", open ? "true" : "false");
    card.classList.toggle("expanded", open);
  };
  card.addEventListener("click", (event) => {
    if (event.target.closest("a")) return;
    toggle();
  });
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      toggle();
    }
  });
  return card;
}

function paintColumns(host, buckets, run, t) {
  host.innerHTML = "";
  const filled = [];
  const emptyBits = [];
  for (const col of COLUMN_DEFS) {
    const rows = buckets[col.id] || [];
    if (col.hideIfEmpty && !rows.length) continue;
    if (!rows.length) {
      // 紧凑摘要：短标签 + 数量，不占等宽栏
      emptyBits.push(`${t(col.labelKey)} ${0}`);
      continue;
    }
    filled.push({ col, rows });
  }

  const filledWrap = text("div", "groups-filled");
  for (const { col, rows } of filled) {
    const section = text("section", `group-column ${col.className}`);
    section.dataset.column = col.id;
    const head = text("header", "group-column-head");
    head.appendChild(text("h3", null, t("groupColumnTitle", t(col.labelKey), rows.length)));
    section.appendChild(head);
    const stack = text("div", "group-column-stack");
    for (const row of rows) stack.appendChild(buildCard(row, run, t));
    section.appendChild(stack);
    filledWrap.appendChild(section);
  }
  host.appendChild(filledWrap);

  if (emptyBits.length) {
    host.appendChild(text("div", "groups-empty-summary", emptyBits.join(" · ")));
  }
}

function bucketize(rows) {
  const buckets = { trusted: [], faulty: [], scope: [], neutral: [], failed: [], processing: [] };
  for (const row of rows) {
    const st = row.status || "neutral";
    if (st === "trusted") buckets.trusted.push(row);
    else if (st === "wrong" || st === "outdated") buckets.faulty.push(row);
    else if (st === "scope") buckets.scope.push(row);
    else if (st === "failed") buckets.failed.push(row);
    else if (st === "processing") buckets.processing.push(row);
    else buckets.neutral.push(row);
  }
  return buckets;
}

export function renderGroupedEvidence(run, t) {
  const host = el("groups-view");
  if (!host) return;
  const apply = () => {
    const rows = decorateRows(summarySources(run));
    paintColumns(host, bucketize(rows), run || { pairs: [] }, t);
  };
  if (document.startViewTransition && !prefersReducedMotion()) {
    try {
      document.startViewTransition(apply);
      return;
    } catch {
      /* fall through */
    }
  }
  apply();
}

export function renderGroupsProcessing(slots, t) {
  const host = el("groups-view");
  if (!host) return;
  const rows = decorateRows(
    (slots || []).map((slot, index) => ({
      url: slot.url || `pending://${index}`,
      domain: slot.url ? domainOf(slot.url) : "—",
      status: "processing",
      reason: null,
      key_value: slot.claim || null,
      claim: slot.claim || null,
      tier: slot.tier || null,
      source_type: null,
      content_date: null,
    })),
  );
  paintColumns(host, bucketize(rows), { pairs: [] }, t);
}
