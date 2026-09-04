# Failure Modes

**Stage 3 — Failure as UX.** Mechanism is in `architecture.md`; this is what breaks and what the
user sees.

> v4, 2026-09-04 — risks re-rated. A false "you're wrong" is the worst outcome: the kid rewrites
> correct work and stops trusting themselves.

## Top risks, honestly ranked

1. **`compare` calls a correct answer different.** The real #1. Student answers arrive via OCR as
   `x = 17 cm`, `17`, `{1, 3}`, `1/2 or 0.5` — sympy parsing is where a correct kid gets failed.
2. **A misread produces a fabricated mistake** at a line never written. Handwriting, and `read_ok`
   returns 1 on misreads (models are overconfident).
3. **Only message 1 gets read.** It arrives first and short — the *back of the book* failure this
   project exists to escape.
4. **`get_file` times out.** Already happened here (`journal.md` 2026-08-17). Certain unless fixed.
5. **Maths notation breaks Telegram Markdown** (`*`, `_`, `^`, `\`). Fine in the log, mangled in chat.

**Downgraded on review:** `solve` slipping on school algebra is *low*, not medium — which is why the
disputed pile is mostly reading and comparison failures, not maths ones. Anchoring is *structurally
impossible* (`solve` never receives their steps), so it's a hard rule, not a live risk.

## Everything else

| What goes wrong | Risk | Handling |
|---|---|---|
| Valid alternative method marked wrong | med | Judge the answer; steps only for internal consistency |
| `review` inherits a transcription error and hunts a bug that isn't there | med | It reads the photo itself, not `read_page`'s text (87% of errors are transcription — `learnings.md`) |
| Every downstream line flagged, not just the first | med | First divergence only |
| Msg 1 lands before `review` verifies | high | Msg 1 **reports, not judges**: "I get 17 for 2 — checking" |
| `review` exonerates a row msg 1 flagged | med | Designed retraction; `exonerated` is a row state, not a hope |
| Right answer, wrong method | low | Say right, note the step that doesn't follow |
| Whole page, several attempted | high | Ask which one |
| Blurry / cropped / angled | high | Name what's unreadable + one retake tip. No verdict |
| Ambiguous `1`/`7`, `x` vs `×` | high | `read_ok = 0` → ask. `x` vs `×` silently changes the problem |
| Unreadable diagram | med | Ask for the labels. Never invent an angle |
| Crossed-out lines, working out of order | high | Ask for the order; never invent one |
| Answer only, no working | high | Verdict yes, diagnosis no — say so |
| Reads like a red pen | high | Name the step, not the person: "line 2 is wrong", never "you're careless" |
| **Softening a wrong answer** — "not quite", "almost", "good effort" | high | Wrong is wrong. A hedged verdict misinforms as surely as a false one |
| Explains a one-off instead of a rule | med | "The −4 gets multiplied too" is reusable |
| Check takes 15–20s | high | Ack in under a second + typing action |
| LLM call fails | med | One honest sentence, logged, bot stays up |
| Same token dev + prod | high | `409`. Separate token per environment |
| Updater dies, process lives | med | `add_error_handler`. "It's running" is not a health check |
| Stranger runs up vision cost | low | Allowlist, declined before any paid call |
| Not maths / reply over 4096 chars | low | Polite decline / split at step boundaries |

## Hard rules

- Solve independently **before** looking at their working.
- Never state a verdict without first restating what was read.
- **One mistake** — the first divergence only.
- Never mark an equivalent answer or a valid alternative method wrong.
- Never invent a step they didn't write. Uncertain → ask.
- A user-confirmed answer is authoritative; no model second-guesses it.
- One bad photo never crashes the bot or leaks a traceback.

On any failure: one short sentence in the bot's normal voice. Never a raw error, never silence,
never a verdict it isn't sure of.
