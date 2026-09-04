# Architecture

**Stage 5 — Break it into atomic modules.**

> Draft v3, 2026-09-04, from the user's design. Two workers race over a shared table; the expensive
> model runs only where the cheap one and the student disagree; the user is asked only where the
> reading was flagged shaky.

## The shape in one paragraph

One model **reads** the page into typed rows — one row per problem, carrying the student's working
and a **0/1 flag saying whether the reading is trustworthy**. Two workers then start
**simultaneously** over those rows: a fast model **re-solves** each problem from the statement alone,
and a strong model **walks the student's actual working**. Any row where the fast solve agrees with
the student is settled instantly and the strong model drops it. **The moment the fast pass finishes,
the user gets a first message with the answers it got**; the diagnosis follows when the review lands.
Where a row is in dispute *and* the reading was flagged shaky, the bot asks rather than accuses — and
after every reply the user can still say "you misread me" and correct it by hand.

## The pieces

| Module | Does one thing | Input → Output |
|--------|----------------|----------------|
| `read_page` | read the problem and the answer off the photo | image → `list[Problem]` (label, statement, student_answer, `read_ok` 0/1, `uncertain_field`) |
| `solve` | re-derive the answer, **blind to the student** | statement → `correct_answer` |
| `compare` | decide if two answers are the same number/expression | (student answer, correct answer) → `agree / differ / uncomparable` |
| `review` | find the mistake, reading the page itself | (**photo**, statement) → `first_divergence(line, why)`, `valid`, or `wrong_problem` |
| `clarify` | resolve a shaky reading, cheapest route first | row → confirmed `student_answer` (see the ladder below) |
| `correct` | let the user fix a misread after the fact | tapped label + typed answer or new photo → updated row, re-run |
| `respond` | turn settled rows into chat messages | rows → **message 1**, **message 2**, correction keyboard |

`solve` and `review` are the two independent models: independent in a stronger sense than two runs of
one model, because they use **different methods** — one re-derives from scratch, the other verifies a
given derivation.

## The anchoring wall (structural, not a prompt rule)

`solve` receives **only** `statement`. The student's steps and answer are not in its context and
cannot be — they live in different columns and are never passed. A model shown wrong working tends to
agree with it; this design makes that impossible rather than discouraged. `review` is the one place
the student's working is allowed into a model, and it **never sees `correct_answer`** — being told
the expected answer would hand it its conclusion.

**`review` gets the photo, not a transcription** (decided 2026-09-04). 87% of grading errors in the
literature are transcription errors (`docs/learnings.md`), so reasoning over `read_page`'s output
means hunting for an error inside text that may already contain it. It reads the working itself, and
receives `statement` only as the thing to check the page *against* — which is what makes
`wrong_problem` meaningful: *the statement I was given isn't what's on this page*.

## The two exits (decided 2026-09-04)

`review` is prompted to **find the mistake** — it only ever runs on rows where the answers already
differ, so a second opinion on the maths would be overkill for school problems. But it may return two
other answers, at no extra call and no extra latency:

- **`valid`** — "I walked the steps and they're all fine."
- **`wrong_problem`** — "this working isn't for the problem I was given."

They exist because *a disagreement doesn't imply the student erred*. A row reaches `disputed` by four
routes and only one is a maths mistake:

| Why the row is disputed | Student actually | Caught by |
|---|---|---|
| The student made a mistake | wrong | — (the normal path) |
| `read_page` misread the **student's answer** (`7` as `1`) | **right** | `valid` |
| `compare` couldn't match an **equivalent form** | **right** | `valid` |
| `read_page` misread the **printed problem** | **right** | `wrong_problem` |
| `solve` slipped | right | `valid` |

Without the exits, a model told "find the mistake" in flawless work invents a plausible one and the
student "fixes" a correct line. **When an exit fires we do not deliver a verdict** — we ask.

## When we ask the user (and when we don't)

**We do not confirm every reading.** Two gates must both be true before the bot asks anything:

1. **`read_ok = 0`** — `read_page` itself flagged this row as shaky, and named the
   `uncertain_field` (`statement` / `steps` / `answer`) so the question can be specific.
2. **The row is `disputed`** — a shaky reading that still produced agreement needs no question.

A row with `read_ok = 1` is trusted; a disagreement there is treated as a real student mistake. That
keeps the common case at zero interruptions.

### The escalation ladder (`clarify`)

| Step | What | Why in this order |
|---|---|---|
| 1 | **Ask in chat**, specifically: *"For 3a I read your answer as 1 — is that right, or what did you write?"* Reply is **"yes"** or the number. | Cheapest, fastest, authoritative |
| 2 | **Targeted re-read**, when the answer isn't the kind of thing you can type — a set, an interval, a sketch, a graph. One field only: *"transcribe exactly the final answer of 3a."* | Typing a set or a curve is worse UX than looking again. Narrow scope, so it genuinely re-reads instead of repeating itself |
| 3 | **Poll** with two or three likely readings, plus "none of these". | Last resort: recognition beats recall, and tapping beats typing a set |

## Correcting a misread after the fact

Every reply carries a **"you misread my answer"** button. Tapping it shows the task labels found on
the page — `1`, `2`, `3a`, `3b` — and tapping one asks for the real answer **typed in chat, or as a
new photo**. The row's `student_answer` is replaced, `answer_source` becomes `user_confirmed`, and
the row re-runs from `compare` (never from `read_page` — the user's word is authoritative).

The verdict is then re-issued honestly: *"With 17 for 3a — that's right, my mistake."* This is the
backstop for the case the `read_ok` flag misses, and the only place a student's answer enters the
system without a model in the loop.

## Two messages, not one

| | When | Contains |
|---|---|---|
| **Message 1** | the instant `solve` finishes all rows | which rows agreed, and **the answers `solve` got** for the ones that didn't |
| **Message 2** | when `review` finishes the disputed rows | the first wrong line + the rule — or a retraction, or a `clarify` question |

**Message 1 reports; it does not judge.** *"I get 17 for 3a — checking your working now"*, never
*"you're wrong."* It goes out **before** the false-accusation guard has run, and a number the bot got
is revisable where an accusation isn't. Message 1 stays deliberately thin: the explanation is the
point, and must not read as the footnote.

## Model tiers

| Module | Tier | Why |
|--------|------|-----|
| `read_page` | vision / handwriting-capable | The hardest input; 2-D maths layout (fraction stacks, exponents, radicals) is where general OCR fails |
| `solve` | `fast` | It can only *clear* a row or open a revisable report; it never issues a final "wrong" alone |
| `review` | `smart` | It decides the accusations, and exonerates |
| `clarify` step 2 | same as `read_page` | One field, one instruction |

## Data flow

```
photo
  └─► read_page ──► rows (label, statement, student_answer, read_ok 0|1, status=pending)
                      │
        ┌─────────────┴──────────────┐          (both start at once)
        ▼                            ▼
   solve (fast, per row)        review (smart, per row, reads the photo)
        │                            │
        ▼                            │  ── row already cleared   → skip
   compare(student, correct)         │  ── row clears mid-flight → cancel
        │                            │  ── prefers already-disputed rows
   agree ──► cleared ────────────────┘
        │
   differ ──► disputed
        │
        ├──► MESSAGE 1: "1, 2 right. For 3a I get 17 — checking."
        │
        ├── read_ok = 0 ──► clarify: ask → re-read → poll ──► compare again
        │
        └── read_ok = 1 ──► review ──► MESSAGE 2
                                        ├─ first_divergence ──► one line, one rule
                                        ├─ valid ────────────► "your working looks right, I think
                                        │                       I got this one wrong" (exonerated)
                                        └─ wrong_problem ────► "did I read the question right?"

every reply ──► [ you misread my answer ] ──► pick label ──► type it / new photo ──► re-compare
```

## Row states

`pending` → `solved` → **`cleared`**, or **`disputed`** → `awaiting_user` / `diagnosed` /
`exonerated`. A user correction sends any row back to `solved` for a fresh `compare`.

## Data you store

Table `mathcheck_problems` — one row per problem found on a photo:

| Column | Notes |
|---|---|
| `id`, `telegram_id`, `created_at` | every query scoped by `telegram_id` |
| `label` | **as written on the page** — `1`, `3a`, `3b`. Not a row index; it's what the user taps |
| `statement` | the problem as read |
| `student_answer` | as read, or as corrected by the user |
| `answer_source` | `read` or `user_confirmed` — a corrected answer is never re-read or second-guessed |
| `correct_answer` | NULL until `solve` fills it |
| `read_ok` | 0/1 from `read_page`. Gate 1 for asking the user |
| `uncertain_field` | `statement` or `answer`, set when `read_ok = 0`, so the question is specific |
| `status` | `pending / solved / cleared / disputed / awaiting_user / diagnosed / exonerated` |

The table is what makes the race safe: the shared work queue both workers read and write, and where a
cancelled or skipped row is recorded. `exonerated` exists so a retraction is a *state*, not a message
we hope got sent.

## Which starter services does each use?

- `llm` — all three models, chosen by tier, via OpenRouter.
- `db` (Neon) — the queue above.
- `media` (fal) — **not used.**
- `storage` (R2) — **not used in v1.** The photo is held in memory for the life of the request so
  `clarify` step 2 can re-read it; it isn't persisted.

## Not a model: `compare`

`compare` is plain Python (sympy for symbolic and numeric equivalence), because `2/4`, `0.5` and
`1/2` must be one answer, and because it is the cheapest, most deterministic, most-run step in the
system. `uncomparable` (a word answer, a proof, a diagram) is a legitimate third outcome — it routes
the row to `review` rather than guessing.

## Open decisions

1. **`review` says valid, `solve` said wrong — who wins?** Recommendation: `review`. It is the
   stronger model *and* it examined the actual working.
2. ~~`review`'s framing~~ — **decided 2026-09-04, see "The two exits".**
3. **Speculative cost.** Cancelling an in-flight call saves latency and most, not all, of the tokens
   already generated. Acceptable at this volume; revisit if pages of 20 become normal.
4. **Both wrong in the same way** settles the row as correct with no review. Rare, fails in the mild
   direction — accepted.
5. **Does message 1 wait for the whole page, or go per row?** Drafted: one message after the fast
   pass completes.
6. **Should `read_ok` be per row or per field?** Drafted per row (as specified) *plus*
   `uncertain_field`, because a bare per-row flag can't tell `clarify` what to ask about.
8. ~~Should `review` receive the photo?~~ — **decided 2026-09-04: yes.** It reads the working off
   the page; `read_page` no longer transcribes steps at all, which makes the read pass cheaper and
   shorter — and that pass is on the critical path for message 1.
7. **Which labels go in the correction keyboard** — every task on the page, or only the disputed
   ones? Drafted: all of them, because a misread can also produce a wrongly *cleared* row.
