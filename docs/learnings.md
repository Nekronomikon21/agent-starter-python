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

### `read_page` bake-off on page01 — 2026-09-04

Run it with `uv run python scripts/bakeoff.py --show`.

| model | answers | statement | flagged | s |
|---|---|---|---|---|
| `anthropic/claude-opus-4.8` | 5/5 | 0.96 | 2 | 7.6 |
| `google/gemini-3.7-flash` | 5/5 | 0.98 | 1 | 15.8 |
| `google/gemini-3.8-flash` | 4/5 | 0.98 | 1 | 68.7 |

- **The prompt mattered far more than the model.** Gemini scored 1/5 until the instructions
  forbade LaTeX; it was emitting `\pm 3` and `egin{cases}`, not misreading. One line took it to
  5/5. Suspect the harness before the model.
- **`Literal[0, 1]` breaks structured output** on Gemini — it arrives as a string enum `"0"`/`"1"`
  and fails validation. Use `bool`. Claude accepted it; Gemini didn't.
- **Latency is not yet rankable.** The same model took 11s on one run and 68s on the next. Provider
  variance swamps the difference; don't choose on one run.
- **№3 (a crossed-out digit) splits them**: 3.8-flash reads `y = 5`, 3.7-flash and Opus read `y = 7`.
  A genuine ambiguity — exactly what `read_ok = false` is for.
- **One page can't decide this.** All three are ≥ 4/5 on five problems. Undecided until there are
  more pages, especially correct ones.

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
