import { el, prefersReducedMotion, text } from "./dom.js";

function countsFrom(run) {
  const summary = run?.summary;
  if (summary?.counts) {
    return {
      sources: summary.counts.sources ?? 0,
      pairs: summary.counts.pairs ?? 0,
      faulty: summary.counts.faulty_sources ?? 0,
      scope: summary.counts.scope_sources ?? 0,
    };
  }
  const pairs = run?.pairs || [];
  return {
    sources: (run?.sources || []).length || (run?.claims || []).length,
    pairs: pairs.length,
    faulty: pairs.filter((p) => p.relation === "contradict").length,
    scope: pairs.filter((p) => p.relation === "same_question_different_scope").length,
  };
}

function animateCount(node, target) {
  if (prefersReducedMotion()) {
    node.textContent = String(target);
    return;
  }
  const end = Number(target) || 0;
  const start = performance.now();
  const duration = 400;
  const tick = (now) => {
    const p = Math.min(1, (now - start) / duration);
    node.textContent = String(Math.round(end * p));
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

export function renderMetrics(run, t) {
  const strip = el("metrics-strip");
  strip.innerHTML = "";
  const c = countsFrom(run);
  const items = [
    { value: c.sources, label: t("metricSources"), className: "" },
    { value: c.pairs, label: t("metricComparisons"), className: "" },
    { value: c.faulty, label: t("metricFaulty"), className: "danger" },
    { value: c.scope, label: t("metricScopeSources"), className: "scope" },
  ];
  for (const item of items) {
    const cell = text("div", `metric ${item.className}`.trim());
    const value = text("div", "metric-value", "0");
    cell.appendChild(value);
    cell.appendChild(text("div", "metric-label", item.label));
    strip.appendChild(cell);
    animateCount(value, item.value);
  }
}

export function renderVerdictPane(run, t, { renderSafeMarkdown, confidenceRing }) {
  const summary = run?.summary;
  const judgment = run?.judgment || {};
  const headline =
    summary == null
      ? t("verdict")
      : t.lang === "zh"
        ? summary.headline_zh
        : summary.headline_en;
  // t.lang injected below via bind
  const lang = renderVerdictPane.lang || "en";
  el("verdict-headline").textContent =
    summary == null ? t("verdict") : lang === "zh" ? summary.headline_zh : summary.headline_en;

  const answer = el("verdict-answer");
  answer.innerHTML = "";
  const answerNode = text("div", "answer");
  renderSafeMarkdown(answerNode, judgment.answer || t("noVerdict"));
  answer.appendChild(answerNode);

  const ringHost = el("verdict-ring");
  ringHost.innerHTML = "";
  ringHost.appendChild(confidenceRing(judgment.confidence));

  const legend = el("verdict-legend");
  legend.innerHTML = "";
  const trusted = summary?.trusted_count ?? 0;
  const faulty = summary?.wrong_or_outdated_count ?? 0;
  const scope = summary?.scope_source_count ?? 0;
  for (const [cls, label, n] of [
    ["ok", t("legendTrusted"), trusted],
    ["danger", t("legendFaulty"), faulty],
    ["scope", t("legendScopeSources"), scope],
  ]) {
    const li = document.createElement("li");
    li.appendChild(text("span", `pill ${cls}`, label));
    li.appendChild(text("span", null, String(n)));
    legend.appendChild(li);
  }
}

export function bindVerdictLang(lang) {
  renderVerdictPane.lang = lang;
}

export function renderBottomPanels(run, t) {
  const summary = run?.summary;
  const contra = el("contradiction-body");
  const scopeBody = el("scope-body");
  const composition = el("composition-body");
  contra.innerHTML = "";
  scopeBody.innerHTML = "";
  composition.innerHTML = "";

  const groups = summary?.conflict_groups || [];
  if (!groups.length) {
    contra.appendChild(text("div", "empty-state", t("noConflicts")));
  } else {
    for (const group of groups) {
      const row = text("div", "summary-row");
      const label = (renderBottomPanels.lang || "en") === "zh" ? group.label_zh : group.label_en;
      row.appendChild(text("div", "conflict-nature", label));
      contra.appendChild(row);
    }
  }

  const scopeSources = (summary?.sources || []).filter((s) => s.status === "scope");
  if (!scopeSources.length) {
    scopeBody.appendChild(text("div", "claim empty", t("noScopeSources")));
  } else {
    for (const row of scopeSources) {
      scopeBody.appendChild(
        text(
          "div",
          "summary-row scope",
          `${row.domain}: ${row.key_value || row.claim || row.reason || ""}`,
        ),
      );
    }
  }

  const byTier = summary?.composition_by_tier || {};
  const entries = Object.entries(byTier).filter(([, n]) => n > 0);
  const max = Math.max(1, ...entries.map(([, n]) => n));
  if (!entries.length) {
    composition.appendChild(text("div", "claim empty", t("noComposition")));
  } else {
    for (const [tier, n] of entries) {
      const row = text("div", "composition-bar");
      row.appendChild(text("span", null, tier));
      const track = text("div", "composition-track");
      const fill = text("div", "composition-fill");
      fill.style.width = `${Math.round((n / max) * 100)}%`;
      track.appendChild(fill);
      row.appendChild(track);
      row.appendChild(text("span", null, String(n)));
      composition.appendChild(row);
    }
  }
}

export function bindBottomLang(lang) {
  renderBottomPanels.lang = lang;
}

export function renderNliNote(run, t) {
  const note = el("nli-raw-note");
  const summary = run?.summary;
  if (!summary) {
    note.textContent = "";
    return;
  }
  note.textContent = t(
    "nliRawNote",
    summary.nli_contradict_pairs || 0,
    summary.nli_contradict_low_confidence || 0,
  );
}

export function renderHeroSubtitle(run, t) {
  const node = el("question-subtitle");
  if (!node) return;
  const summary = run?.summary;
  if (!summary) {
    node.textContent = "";
    return;
  }
  const lang = renderHeroSubtitle.lang || "en";
  node.textContent = lang === "zh" ? summary.headline_zh : summary.headline_en;
}

export function bindHeroLang(lang) {
  renderHeroSubtitle.lang = lang;
}
