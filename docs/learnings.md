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

- **LLM / prompts:** _(e.g. "balanced tier handles the analysis fine; fast tier mislabels keys")_
- **Models & tiers:** _(which tier for which step, and why)_
- **Media (fal):** _(which model, what inputs matter, typical latency/cost)_
- **Storage / DB:** _(gotchas, naming, what worked)_
- **Surprises / dead ends:** _(things that didn't work, so you don't retry them)_

## Open questions

_(Things you still need to figure out.)_
