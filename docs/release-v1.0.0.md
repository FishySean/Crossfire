# Crossfire v1.0.0

First tagged release of the multi-source fact-checking engine.

> Prefer **v1.0.1** for the latest release notes (includes this release plus the cost-estimate fix): [`release-v1.0.1.md`](release-v1.0.1.md).

## What’s in this version

- End-to-end pipeline: find sources → fetch → extract claims → pairwise compare → judge
- Ask-a-Question UI + CLI (`crossfire ask`) with cost estimate and confirm
- Live fetchers: **HTTP** (default, free) and **Steel** (optional cloud browser)
- Pairers: **Claude** (default) and local **NLI** (`FishySean/crossfire-pairer`)
- Frozen eval suite under `evals/`
- URL validation at `Source` / SourceFinder (rejects whitespace / non-http URLs)
- Hexagonal layout (`domain` → `application` → adapters); architecture tests enforce imports
- Bilingual README (`README.md` / `README.zh.md`) and `docs/architecture.md`
- MIT license

## Hugging Face model

- Repo: [FishySean/crossfire-pairer](https://huggingface.co/FishySean/crossfire-pairer)
- Locked revision: `0517c59dfa13038226b4b66c3fa6b605b9215df5`
- Test macro-F1 ≈ 0.614 (seed 44); three-seed mean ≈ 0.576

## Known limitations

- HTTP fetcher fails on hard anti-bot / JS-only pages
- Contested topics often produce hedged single claims → few contradictions
- NLI: small data; weak `same_question_different_scope`; uncalibrated confidence; contradict ≈ untuned base
- Cost estimates use a 4-source floor; more sources cost more

## Install

See [README.md](../README.md). Requires Python 3.12+, `uv`, and `ANTHROPIC_API_KEY`.
