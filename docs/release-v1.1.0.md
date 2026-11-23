# Crossfire v1.1.0

Dashboard release: the UI becomes a newspaper-style investigation shell driven by server-side `RunSummary` (source rulings, key values, headlines).

## What’s in this version

Everything from **v1.0.1**, plus:

### Backend (shipped in the v1.1 prep commit)

- `Claim.key_value` from extract
- `Judgment.source_rulings` (trusted / wrong / outdated / scope / neutral) from judge
- `summarize_run` / `summary_to_dict` exposed on `/api/runs/...` and SSE `done`
- Old runs without rulings still summarize (trusted/neutral fallback)
- Phase-1 eval: **5/5** with `PAIRER=nli` (~$1.73 actual tokens)

### Frontend

- App shell: fixed sidebar (~200px) + main column; ask flow in a modal
- Above-the-fold bento: eyebrow, display serif title, CSS skyline+red disc, KPI strip from `summary.counts`, radial evidence graph, verdict pane (headline, answer, donut, legend, primary CTA)
- Graph \| Table segmented control; table reuses source cards
- Detail section keeps full sources / pairs / judgment; NLI raw note from summary
- ES modules under `web/static/js/` (no bundler): `app.js`, `graph.js`, `dashboard.js`, `dom.js`
- Design tokens + motion (`transform`/`opacity` only) with `prefers-reduced-motion`
- Visual diff log: `notes/ui-diff-log.md` (≥3 rounds)
- Screenshots: `docs/screenshots/17–21-dashboard-*.png`

## Eval

| | Result |
|---|---|
| Suite | frozen `evals/` |
| Pairer | NLI |
| Score | **5/5** (same as prior baseline) |
| Approx. cost | ~$1.73 (439680 in / 27684 out) |

## Known limitations

- Radial graph is SVG layout, not a chart library — dense 8+ sources stay readable but not identical to the marketing collage
- Bottom bento row sits just below the 1440×900 fold by design
- Live runs still skeleton cards in Table; Graph fills from `summary` after `done` / history load

## Install

See [README.md](../README.md).
