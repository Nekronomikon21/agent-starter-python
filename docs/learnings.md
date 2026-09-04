# Learnings

**Stage 6 — Test atomic modules in isolation. Iterate. Keep learnings.**

As you build and test each module on its own, write down what you discover: which
prompt phrasing worked, which model/tier was good enough, surprising failures, costs,
quirks of a service. This saves you (and Claude) from re-learning the same things.

`journal.md` is the *chronological* trace; this file is the *distilled* "here's what we
know now" — keep it tidy and current.

## What we've learned

### `compare` (sympy, no model) — 2026-09-04

- **Prose parses as maths, silently.** `"see the graph"` becomes `see*the*graph`, a valid product of
  symbols, so it returned `differ` — a kid failed for writing words. Reject any alphabetic run of 3+
  letters that isn't a known function. Variables are 1–2 chars; prose isn't.
- **`parse_expr(global_dict={})` breaks.** The parser's generated code needs sympy's own names
  (`Integer`, ...). Pass the sympy namespace with `__builtins__` blanked — builtins are the actual
  eval risk, not the sympy names.
- **`rationalize` is required**, else `0.75` and `3/4` compare through float noise.
- **`√8` needs a regex, not a character swap.** `√`→`sqrt` gives `sqrt8`, which parses as a symbol.
- Use `Expr`, not `Basic`, in type hints — `Basic` has no `__sub__` and pyright rejects it.

### Vision model for `read_page` — research, 2026-09-04

Source: Levine et al., *Automated Grading of Handwritten Mathematics Using Vision-Capable LLMs*
(arXiv 2605.19043), plus OpenRouter model pages.

- **87% of errors were transcription, not grading.** Reading the page dominates everything else.
  Confirms the risk re-rating: `solve` is not the problem.
- **Gemini 3 Flash beat GPT-5.1 and GPT-5-mini** (89–99% vs 87–95% rubric accuracy). A flash-class
  model won. Don't assume the frontier tier reads handwriting best.
- **Errors skewed to false *positives*** (hallucinating correct work), not false negatives — the mild
  direction for us.
- **Image quality dominates prompt tuning.** Blurry and rotated pages caused most failures; the paper
  says gains come from better capture, not better prompts. Retake guidance > prompt polish.
- **Models mishandled equivalent expressions** (rounded decimals vs exact fractions) — independent
  confirmation that `compare` belongs in code, not a model.
- **They chose one-shot transcribe+grade over separate steps**, citing higher accuracy. Conflicts
  with our pipeline — see the open question below.
- Flash line has moved well past the paper's version: `google/gemini-3.8-flash` ($0.75/$3.75, 1M ctx,
  vision) shipped 2026-09-02, two days ago. `google/gemini-3.7-flash` is the stable candidate.
  Our `fast` tier is still `gemini-2.5-flash-lite`.

**Don't pick from a leaderboard.** The paper's own finding is that image capture dominates, so the
model must be chosen on *our* photos of *our* handwriting. Bake-off harness once samples arrive.

- **LLM / prompts:** _(e.g. "balanced tier handles the analysis fine; fast tier mislabels keys")_
- **Models & tiers:** _(which tier for which step, and why)_
- **Media (fal):** _(which model, what inputs matter, typical latency/cost)_
- **Storage / DB:** _(gotchas, naming, what worked)_
- **Surprises / dead ends:** _(things that didn't work, so you don't retry them)_

## Open questions

_(Things you still need to figure out.)_
