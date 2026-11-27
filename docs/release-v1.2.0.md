# Crossfire v1.2.0

Model iteration 2 + inference-time `unrelated` masking. Published pairer is **v2** (more training data) with `NLI_MASK_UNRELATED` on by default.

## What’s in this version

Everything from **v1.1.2**, plus:

- **NLI pairer v2** on Hugging Face [`FishySean/crossfire-pairer`](https://huggingface.co/FishySean/crossfire-pairer)
  - Locked revision: `2f8d20c46d994b023a098362dcaed7750f2ef2a0` (val-loss seed **43** from `iter2-final-20261127-064414`)
  - Training set grew with 7 new scope questions (474 labeled pairs; **89-pair test frozen**)
  - With masking: three-seed macro-F1 **0.59 ± 0.06**, accuracy **81%**; published model F1 **0.55**, accuracy **81%**
- **`NLI_MASK_UNRELATED` (default on)**: at inference, set the `unrelated` logit to `-inf` (labels/training unchanged). Same-question claim pairs should not score as unrelated by construction.
- Mask gate: 6 checkpoints (v1+v2 × 3 seeds) had **0** correct→wrong flips; **33** wrong→correct. See `notes/iter2-mask-eval.json` and `notes/iteration-2.md`.
- Publish choice: v2 vs v1 three-seed F1 is tied (~0.59 vs ~0.60); ship **v2** for more training data (and higher accuracy).

## Install

See [README.md](../README.md). For local NLI:

```bash
uv sync --group nli
# .env
# PAIRER=nli
# NLI_MODEL_REVISION is locked in crossfire/config.py
```

## Notes

- Confidence scores remain **uncalibrated**.
- `scope` recall is still weak; published seed is not the highest test-F1 seed (selection is validation loss only).
- Step 10 Anthropic spend (bank + Claude labeling): about **$4.3–$5** (under $12 budget). Colab T4 training had no Anthropic cost.
