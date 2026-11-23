# Crossfire v1.1.2

UI polish on the grouped evidence view (frontend-only). README hero and `docs/screenshots/22–23` are reshot with settled KPIs.

## What’s in this version

Everything from **v1.1.1**, plus:

- Sidebar wide enough for full **CROSSFIRE** logo (invariant: `scrollWidth ≤ clientWidth`)
- Screenshots / e2e use `prefers-reduced-motion` and assert KPI text equals `summary.counts`
- History labels: question · date · pairer (not filenames); README shots keep real demo runs only
- Card titles: domain on its own ellipsis line; tier below; same-domain pages show `wikipedia · Page`
- Empty ruling groups collapse to a one-line summary; filled groups share width with `auto-fill` card grids
- Pair lines i18n once each (`vs domain · relation · p=…`); `p<0.5` marked uncertain; EN chrome has no Chinese UI strings
- Visual diff Round 5: `notes/ui-diff-log.md`

## Install

See [README.md](../README.md).
