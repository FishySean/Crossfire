import { domainOf, el, prefersReducedMotion, text, truncate } from "./dom.js";

const COLUMN_DEFS = [
  { id: "trusted", statuses: ["trusted"], className: "ok", labelKey: "groupTrusted" },
  { id: "faulty", statuses: ["wrong", "outdated"], className: "danger", labelKey: "groupFaulty" },
  { id: "scope", statuses: ["scope"], className: "scope", labelKey: "groupScope" },
  { id: "neutral", statuses: ["neutral"], className: "neutral", labelKey: "groupNeutral" },
  { id: "failed", statuses: ["failed"], className: "danger", labelKey: "groupFailed", hideIfEmpty: true },
  { id: "processing", statuses: ["processing"], className: "neutral", labelKey: "groupProcessing", hideIfEmpty: true },
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
    return parts.length ? parts[parts.length - 1].replace(/_/g, " ") : "";
  } catch {
    return "";
  }
}

function uniqueTitles(rows) {
  const domainCount = {};
  for (const row of rows) {
    const d = row.domain || domainOf(row.url);
    domainCount[d] = (domainCount[d] || 0) + 1;
  }
  const seen = {};
  return rows.map((row, index) => {
    const domain = row.domain || domainOf(row.url);
    let title = domain;
    if (domainCount[domain] > 1) {
      const leaf = pathLabel(row.url);
      title = leaf ? `${domain} · ${leaf}` : `${domain} · S${index + 1}`;
    }
    seen[title] = (seen[title] || 0) + 1;
    if (seen[title] > 1) title = `${title} · S${index + 1}`;
    return { ...row, displayTitle: title };
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
    out.push({ other, relation: pair.relation || "?", confidence: conf, nature: pair.nature || "" });
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

function buildCard(row, run, t, { expanded = false } = {}) {
  const card = text("article", `group-card status-${row.status || "neutral"}`);
  card.dataset.url = row.url;
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  card.setAttribute("aria-expanded", expanded ? "true" : "false");

  const head = text("div", "group-card-head");
  head.appendChild(text("div", "group-card-title", row.displayTitle || row.domain || domainOf(row.url)));
  if (row.tier) head.appendChild(text("span", `tag ${row.tier}`, row.tier));
  card.appendChild(head);

  const body = text("div", "group-card-body");
  const key = row.key_value || (row.claim ? truncate(row.claim, 120) : "");
  if (key) body.appendChild(text("div", "group-card-key", key));
  if (row.content_date) body.appendChild(text("div", "group-card-date", row.content_date));
  if (row.status === "processing") body.appendChild(text("div", "group-card-key shimmer-bar", "…"));
  card.appendChild(body);

  const detail = text("div", `group-card-detail${expanded ? "" : " hidden"}`);
  if (row.claim) detail.appendChild(text("div", "claim", row.claim));
  if (row.reason) detail.appendChild(text("div", "claim empty", row.reason));
  const related = pairsFor(run, row.url);
  if (related.length) {
    const list = document.createElement("ul");
    list.className = "group-card-pairs";
    for (const item of related) {
      const p =
        item.confidence == null ? "" : ` p=${Number(item.confidence).toFixed(2)}`;
      list.appendChild(
        text("li", null, `${item.relation}${p} · ${domainOf(item.other)}${item.nature ? ` — ${item.nature}` : ""}`),
      );
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
  for (const col of COLUMN_DEFS) {
    const rows = buckets[col.id] || [];
    if (col.hideIfEmpty && !rows.length) continue;
    const section = text("section", `group-column ${col.className}`);
    section.dataset.column = col.id;
    const head = text("header", "group-column-head");
    head.appendChild(text("h3", null, `${t(col.labelKey)}（${rows.length}）`));
    section.appendChild(head);
    const stack = text("div", "group-column-stack");
    if (!rows.length) {
      stack.appendChild(text("div", "group-empty", t("groupEmpty")));
    } else {
      for (const row of rows) stack.appendChild(buildCard(row, run, t));
    }
    section.appendChild(stack);
    host.appendChild(section);
  }
}

export function renderGroupedEvidence(run, t) {
  const host = el("groups-view");
  if (!host) return;
  const apply = () => {
    const rows = uniqueTitles(summarySources(run));
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
    paintColumns(host, buckets, run || { pairs: [] }, t);
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
  const rows = (slots || []).map((slot, index) => ({
    url: slot.url || `pending://${index}`,
    domain: slot.url ? domainOf(slot.url) : "—",
    status: "processing",
    reason: null,
    key_value: slot.claim || null,
    claim: slot.claim || null,
    tier: slot.tier || null,
    source_type: null,
    content_date: null,
  }));
  const titled = uniqueTitles(rows);
  paintColumns(
    host,
    { trusted: [], faulty: [], scope: [], neutral: [], failed: [], processing: titled },
    { pairs: [] },
    t,
  );
}
