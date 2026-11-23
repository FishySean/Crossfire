export const SVG_NS = "http://www.w3.org/2000/svg";

export const el = (id) => document.getElementById(id);

export function text(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value != null) node.textContent = value;
  return node;
}

export function labeled(label, node) {
  const wrap = text("div", null);
  wrap.appendChild(text("div", "field-label", label));
  wrap.appendChild(node);
  return wrap;
}

export function domainOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return String(url || "").replace(/^https?:\/\//, "").split("/")[0] || url;
  }
}

export function tierClass(tier) {
  if (tier === "primary") return "primary";
  if (tier === "news") return "news";
  if (tier === "aggregator") return "aggregator";
  return "unknown";
}

export function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function truncate(value, max = 42) {
  const s = String(value || "");
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}
