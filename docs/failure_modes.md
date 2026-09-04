# Failure Modes

**Stage 3 — What breaks, and what the user sees.**

> Mechanism is in `architecture.md`, wording in `policy.md`. This doc owns risk.

A checker's failures are **asymmetric**: telling a kid who is right that they're wrong is the worst
thing this bot can do. They rewrite correct work and stop trusting themselves.

## A disagreement does not mean the student erred

The disputed pile is mostly *reading* failures, not maths ones — 87% of grading errors in the
literature are transcription (`learnings.md`). Only one of these five routes is a student mistake:

| Why a row is disputed | Student actually | Caught by |
|---|---|---|
| They made a mistake | wrong | the normal path |
| Their answer was misread (`7` as `1`) | **right** | `review` → `valid` |
| `compare` couldn't match an equivalent form | **right** | `review` → `valid` |
| The printed problem was misread | **right** | `review` → `wrong_problem` |
| `solve` slipped | **right** | `review` → `valid` |

This is why `review` may exonerate. Told only to "find the mistake", it invents one in correct work.

## Top risks

1. **`compare` calls a correct answer different.** Answers arrive as OCR text — `x = 17 cm`,
   `{1, 3}`, `1/2 or 0.5`, comma decimals. Parsing is where a correct kid gets failed.
2. **A misread produces a fabricated mistake** at a line never written. `read_ok` returns true on
   misreads; models are overconfident.
3. **Only message 1 gets read.** It arrives first and short — the *back of the book* failure this
   project exists to escape.
4. **`get_file` times out.** Already happened here (`journal.md` 2026-08-17). Certain unless fixed.
5. **Maths notation breaks Telegram Markdown** (`*`, `_`, `^`, `\`). Fine in the log, mangled in chat.

## The rest

| What goes wrong | Risk | Response |
|---|---|---|
| Valid alternative method marked wrong | med | Judge the answer, not the road to it |
| **An unanswered problem called wrong** — `x = ?`, blank, working that stops partway | high | `compare` can't parse it, the row disputes, and `review` asked for the mistake invents one. `answer_kind = missing` *and* a deterministic blank check route it to `unanswered` |
| **A drawn answer reviewed as if it were working** | high | `solve` has nothing to solve and `review` invents a critique of the sketch — it did, on page01 №4. `answer_kind = drawing` skips both: say we can't check a drawing |
| **A row with no statement** — a crop that cut the question off, a continuation sheet | high | `solve("")` sends the model an empty prompt; every provider 400s. Guarded in code, alongside the answer-side checks, and routed to `unreadable` |
| **One row's provider error losing the whole page** | high | A bare `gather` propagates, so one 400 killed all five rows and the chat went silent after the progress note. Failures are contained per row: solve → hand to `review`, review → `failed` |
| **The bot going silent on an unhandled error** | high | The user sees "Got it — 5 problems" and then nothing, ever, which is indistinguishable from a crash. `on_photo` catches, says so plainly, and invites a retry |
| Every downstream line flagged, not just the first | med | First divergence only |
| Message 1 lands before review verifies | high | It reports, never judges |
| Review exonerates a row message 1 flagged | med | Retract explicitly; `exonerated` is a state |
| Right answer, wrong method | low | Say right, then note the step that doesn't follow |
| Whole page, several attempted | high | Ask which one |
| Blurry / cropped / angled | high | Name what's unreadable, one retake tip, no verdict |
| Ambiguous `1`/`7`, `x` vs `×` | high | `read_ok = false` → ask |
| Unreadable diagram | med | Ask for the labels; never invent an angle |
| Crossed-out lines, working out of order | high | Ask for the order; never invent one |
| Answer only, no working | high | Verdict yes, diagnosis no — say so |
| Reads like a red pen | high | Name the step, not the person |
| Softening a wrong answer | high | Wrong is wrong; a hedge misinforms like a false verdict |
| Check takes 15–20s | high | Ack in under a second, then **refresh the typing action every 4s** — Telegram's lasts ~5s, so sending it once leaves the chat looking crashed |
| LLM call fails | med | One honest sentence; the bot stays up |
| Same token dev + prod | high | `409`. Separate token per environment |
| Updater dies, process lives | med | `add_error_handler`. "It's running" is not a health check |
| Anything else calling `getUpdates` | med | Kills the running long-poll |
| Stranger runs up vision cost | low | Allowlist, declined before any paid call |
| Not maths / reply over 4096 chars | low | Decline politely / split at step boundaries |

## Hard rules

- Solve independently **before** looking at their working.
- Never state a verdict without restating what was read.
- **One mistake** — the first divergence only.
- Never mark an equivalent answer or a valid alternative method wrong.
- Never invent a step they didn't write. Uncertain → ask.
- A user-confirmed answer is authoritative.
- One bad photo never crashes the bot or leaks a traceback.
