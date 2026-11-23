import { SVG_NS, domainOf, el, prefersReducedMotion, text, truncate } from "./dom.js";

const STATUS_CLASS = {
  trusted: "trusted",
  wrong: "wrong",
  outdated: "outdated",
  scope: "scope",
  neutral: "neutral",
  failed: "failed",
};

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

function edgeClass(status) {
  if (status === "wrong" || status === "outdated" || status === "failed") return "edge faulty";
  if (status === "scope") return "edge scope";
  return "edge";
}

export function setEvidenceView(view) {
  const graph = view !== "table";
  el("graph-view").classList.toggle("hidden", !graph);
  el("table-view").classList.toggle("hidden", graph);
  for (const button of document.querySelectorAll("#view-toggle button")) {
    const active = button.dataset.view === (graph ? "graph" : "table");
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  }
}

export function renderRadialGraph(run, { onSelect } = {}) {
  const svg = el("radial-graph");
  const detail = el("node-detail");
  svg.innerHTML = "";
  detail.classList.add("hidden");
  detail.innerHTML = "";
  if (!run) return;

  const rows = summarySources(run);
  const width = svg.clientWidth || 640;
  const height = 300;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.34;
  const reduced = prefersReducedMotion();

  const hub = document.createElementNS(SVG_NS, "g");
  hub.setAttribute("class", "hub-node");
  const hubRect = document.createElementNS(SVG_NS, "rect");
  hubRect.setAttribute("x", String(cx - 70));
  hubRect.setAttribute("y", String(cy - 22));
  hubRect.setAttribute("width", "140");
  hubRect.setAttribute("height", "44");
  hub.appendChild(hubRect);
  const hubText = document.createElementNS(SVG_NS, "text");
  hubText.setAttribute("class", "hub-label");
  hubText.setAttribute("x", String(cx));
  hubText.setAttribute("y", String(cy + 5));
  const q = typeof run.question === "string" ? run.question : run.question?.text || "Question";
  hubText.textContent = truncate(q, 28);
  hub.appendChild(hubText);
  svg.appendChild(hub);

  const n = Math.max(rows.length, 1);
  rows.forEach((row, index) => {
    const angle = (Math.PI * 2 * index) / n - Math.PI / 2;
    const x = cx + Math.cos(angle) * radius;
    const y = cy + Math.sin(angle) * radius;
    const status = STATUS_CLASS[row.status] || "neutral";

    const edge = document.createElementNS(SVG_NS, "path");
    edge.setAttribute("class", edgeClass(row.status));
    edge.setAttribute("d", `M ${cx} ${cy} L ${x} ${y}`);
    edge.dataset.url = row.url;
    if (!reduced) {
      const len = Math.hypot(x - cx, y - cy);
      edge.style.strokeDasharray = String(len);
      edge.style.strokeDashoffset = String(len);
      edge.style.transition = `stroke-dashoffset 400ms cubic-bezier(0.2, 0.8, 0.2, 1) ${Math.min(index * 60, 720)}ms`;
      requestAnimationFrame(() => {
        edge.style.strokeDashoffset = "0";
      });
    }
    svg.insertBefore(edge, hub);

    const g = document.createElementNS(SVG_NS, "g");
    g.setAttribute("class", `source-node ${status}`);
    g.setAttribute("tabindex", "0");
    g.setAttribute("role", "button");
    g.dataset.url = row.url;
    const cardW = 118;
    const cardH = 54;
    const rect = document.createElementNS(SVG_NS, "rect");
    rect.setAttribute("x", String(x - cardW / 2));
    rect.setAttribute("y", String(y - cardH / 2));
    rect.setAttribute("width", String(cardW));
    rect.setAttribute("height", String(cardH));
    g.appendChild(rect);

    const dot = document.createElementNS(SVG_NS, "circle");
    dot.setAttribute("class", `status-dot ${status}`);
    dot.setAttribute("cx", String(x - cardW / 2 + 10));
    dot.setAttribute("cy", String(y - 12));
    dot.setAttribute("r", "4");
    g.appendChild(dot);

    const title = document.createElementNS(SVG_NS, "text");
    title.setAttribute("x", String(x - cardW / 2 + 18));
    title.setAttribute("y", String(y - 8));
    title.textContent = truncate(row.domain || domainOf(row.url), 14);
    g.appendChild(title);

    const value = document.createElementNS(SVG_NS, "text");
    value.setAttribute("x", String(x - cardW / 2 + 10));
    value.setAttribute("y", String(y + 10));
    value.textContent = truncate(row.key_value || row.claim || row.status, 18);
    g.appendChild(value);

    if (row.content_date) {
      const date = document.createElementNS(SVG_NS, "text");
      date.setAttribute("x", String(x - cardW / 2 + 10));
      date.setAttribute("y", String(y + 22));
      date.setAttribute("fill", "#6b6560");
      date.textContent = row.content_date;
      g.appendChild(date);
    }

    if (row.status === "failed") {
      const mark = document.createElementNS(SVG_NS, "text");
      mark.setAttribute("x", String(x + cardW / 2 - 14));
      mark.setAttribute("y", String(y - 10));
      mark.textContent = "✕";
      g.appendChild(mark);
    }

    if (!reduced) {
      g.style.opacity = "0";
      g.style.transform = "translateY(8px)";
      g.style.transition = `opacity 250ms cubic-bezier(0.2, 0.8, 0.2, 1) ${Math.min(index * 60, 720)}ms, transform 250ms cubic-bezier(0.2, 0.8, 0.2, 1) ${Math.min(index * 60, 720)}ms`;
      requestAnimationFrame(() => {
        g.style.opacity = "1";
        g.style.transform = "translateY(0)";
      });
    }

    const activate = () => {
      for (const node of svg.querySelectorAll(".source-node")) {
        node.classList.toggle("dimmed", node.dataset.url !== row.url);
      }
      for (const line of svg.querySelectorAll(".edge")) {
        line.classList.toggle("dimmed", line.dataset.url !== row.url);
      }
      detail.classList.remove("hidden");
      detail.innerHTML = "";
      detail.appendChild(text("div", "domain", row.domain || domainOf(row.url)));
      detail.appendChild(text("div", "pill " + (status === "trusted" ? "ok" : status === "scope" ? "scope" : status === "neutral" ? "neutral" : "danger"), row.status));
      if (row.key_value) detail.appendChild(text("div", null, row.key_value));
      if (row.claim) detail.appendChild(text("div", null, row.claim));
      if (row.reason) detail.appendChild(text("div", "claim empty", row.reason));
      if (typeof onSelect === "function") onSelect(row.url);
    };

    g.addEventListener("click", activate);
    g.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        activate();
      }
    });
    svg.appendChild(g);
  });
}

export function clearRadialSelection() {
  const svg = el("radial-graph");
  if (!svg) return;
  for (const node of svg.querySelectorAll(".source-node")) node.classList.remove("dimmed");
  for (const line of svg.querySelectorAll(".edge")) line.classList.remove("dimmed");
  const detail = el("node-detail");
  if (detail) {
    detail.classList.add("hidden");
    detail.innerHTML = "";
  }
}
