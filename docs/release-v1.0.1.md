# Crossfire v1.0.1

Patch release on top of v1.0.0: cost estimates are calibrated from real ask runs, and the per-question budget cannot be bypassed after more sources are found.

## What’s in this version

Everything from **v1.0.0**, plus the **v1.0.1** fix below.

### From v1.0.0

- End-to-end pipeline: find sources → fetch → extract claims → pairwise compare → judge
- Ask-a-Question UI + CLI (`crossfire ask`) with cost estimate and confirm
- Live fetchers: **HTTP** (default, free) and **Steel** (optional cloud browser)
- Pairers: **Claude** (default) and local **NLI** (`FishySean/crossfire-pairer`)
- Frozen eval suite under `evals/`
- URL validation at `Source` / SourceFinder (rejects whitespace / non-http URLs)
- Hexagonal layout (`domain` → `application` → adapters); architecture tests enforce imports
- Bilingual README (`README.md` / `README.zh.md`) and `docs/architecture.md`
- MIT license

### v1.0.1 — cost estimate calibration

- Recalibrated ask token ceilings from real runs (Node.js LTS, UN Secretary-General, Go ×2). Extract/judge/pair constants raised so estimates are no longer systematically low (e.g. Step 8 Go ask: UI said ~$0.18, actual $0.2747; new 6-source NLI estimate ~$0.51).
- Confirm dialog and CLI show a **range** ($low at 4 sources – $high at 8 sources), not only the floor.
- **Second budget check**: after usable sources are known, re-estimate; if over `MAX_COST_PER_QUESTION`, stop before extract (loud event + message). Pre-run check still uses the 4-source floor.
- Regression fixture: `tests/fixtures/ask_costs/go-20261122.json` locks “new estimate ≥ actual” for that run.

## Hugging Face model

- Repo: [FishySean/crossfire-pairer](https://huggingface.co/FishySean/crossfire-pairer)
- Locked revision: `0517c59dfa13038226b4b66c3fa6b605b9215df5`
- Test macro-F1 ≈ 0.614 (seed 44); three-seed mean ≈ 0.576

## Known limitations

- HTTP fetcher fails on hard anti-bot / JS-only pages
- Contested topics often produce hedged single claims → few contradictions
- NLI: small data; weak `same_question_different_scope`; uncalibrated confidence; contradict ≈ untuned base
- SourceFinder token usage is still not stored in run files (FIND_* ceilings are conservative defaults)
- Actual recorded ask cost still excludes finder tokens (estimate includes them)

## Install

See [README.md](../README.md). Requires Python 3.12+, `uv`, and `ANTHROPIC_API_KEY`.
