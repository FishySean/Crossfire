# Crossfire v1.1.1

Patch: replace the radial evidence graph with a document-flow **grouped-by-ruling** view that cannot overlap.

## What’s in this version

Everything from **v1.1.0**, plus:

- Evidence pane default is **Groups | Table** (was Graph | Table)
- Columns: Trusted / Wrong·outdated / Scope / Neutral / Failed（失败栏仅在有失败时出现）; empty columns show “（无）”
- Cards use CSS Grid/Flex only — no absolute positioning; same-domain pages get path labels (`wikipedia · Topic`)
- Click expands in place (accordion); keyboard Tab/Enter supported
- Verdict answer: max 6 lines + “Show full answer” (no dead truncation)
- Removed radial SVG / node-detail code and styles
- Playwright invariant suite across 8 fixtures × 4 viewports (no card overlap, no text overflow, unique titles)
- Fixtures include the slimmed NVIDIA CEO ask run

## Screenshots

- Before (radial overlap): `docs/screenshots/22-radial-nvidia-before.png`
- After (groups): `docs/screenshots/22-groups-nvidia-above-fold.png`

## Install

See [README.md](../README.md).
