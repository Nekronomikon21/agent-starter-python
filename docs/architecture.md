# Architecture

**Stage 5 — Break it into atomic modules.**

> Structure only. Wording lives in `policy.md`, risks in `failure_modes.md`, cases in `scenarios.md`.

## Shape

One model reads the page into typed rows. Two workers then start **at the same time** over those
rows: a fast model re-solves each problem from the statement alone, a strong model reads the
student's working off the photo. A row where the fast solve agrees with the student is settled at
once and the strong model drops it. The user hears back twice — once when the fast pass finishes,
once when the review lands.

## The pieces

| Module | Does one thing | Input → Output |
|--------|----------------|----------------|
| `read_page` | read the problem and the answer off the photo | image → `list[Problem]` |
| `solve` | re-derive the answer, blind to the student | statement → `correct_answer` |
| `compare` | are two answers the same answer | (student, correct) → `agree` / `differ` / `uncomparable` |
| `review` | find the mistake, reading the page itself | (photo, statement, label) → `mistake(line, why)` / `valid` / `wrong_problem` |
| `clarify` | resolve a shaky reading | row → confirmed `student_answer` |
| `correct` | let the user fix a misread afterwards | label + typed answer or new photo → updated row |
| `respond` | settled rows → chat messages | rows → message 1, message 2 |

`solve` and `review` are the two independent models, independent by **method**: one re-derives from
scratch, the other verifies a given derivation.

## What each model may see

| | photo | statement | student's working | student's answer | correct_answer |
|---|---|---|---|---|---|
| `read_page` | ✔ | — | — | — | — |
| `solve` | — | ✔ | **never** | **never** | — |
| `review` | ✔ | ✔ | ✔ (reads it) | — | **never** |

Two exclusions carry the whole design. `solve` cannot see the student's work, so it cannot be talked
into agreeing with it — a wall, not an instruction. `review` cannot see `correct_answer`, so it isn't
handed its conclusion. `review` reads the working off the photo rather than from `read_page`, so a
transcription error can't propagate into the diagnosis.

## Tiers

| Module | Tier |
|--------|------|
| `read_page` | vision, handwriting-capable — undecided, see `learnings.md` |
| `solve` | `fast` — it can only *clear* a row; disagreement escalates |
| `review` | `smart` — it decides accusations, and exonerates |

## Routing

```
photo
  └─► read_page ──► rows (status=pending)
                      │
        ┌─────────────┴──────────────┐        (both start at once)
        ▼                            ▼
   solve (fast, per row)        review (smart, per row)
        │                            │  ── row already cleared   → skip
        ▼                            │  ── row clears in-flight  → cancel
   compare                           │  ── prefers disputed rows
        │                            │
   agree ──► cleared ────────────────┘
        │
   differ / uncomparable ──► disputed
        │
        ├──► MESSAGE 1  (fires when the fast pass finishes all rows)
        │
        ├── read_ok = false ──► clarify ──► compare again
        │
        └── read_ok = true  ──► review ──► MESSAGE 2

any reply ──► correct ──► re-run from compare
```

**Two gates before the bot asks the user anything:** `read_ok = false` **and** the row is disputed. A
shaky reading that still agreed needs no question.

**Solve calls fire per row, concurrently** — not batched. Batching returns everything at once, so
`review` speculates blind the whole time and burns the expensive tier on rows that were fine.

## Row states

`pending` → `solved` → `cleared`, or `disputed` → `awaiting_user` / `diagnosed` / `exonerated`.
A user correction returns any row to `solved` for a fresh `compare`.

`exonerated` exists so a retraction is a state the system owes, not a message we hope got sent.

## Data

`Problem` (`src/agent/mathcheck/models.py`) → table `mathcheck_problems`, one row per problem:

| Column | Notes |
|---|---|
| `id`, `telegram_id`, `created_at` | every query scoped by `telegram_id` |
| `label` | as written on the page — `1`, `3a`. Not an index; it's what the user taps |
| `statement` | the problem as read |
| `student_answer` | as read, or as corrected by the user |
| `answer_source` | `read` or `user_confirmed` |
| `correct_answer` | NULL until `solve` fills it. **Not always numeric** — "infinitely many solutions" is an answer |
| `read_ok` | bool from `read_page`. Gate 1 for asking the user |
| `uncertain_field` | `statement` or `answer`, set when `read_ok` is false |
| `status` | see row states |

The table is the shared work queue both workers read and write, which is what makes cancel-and-skip
safe.

## Services

`llm` (three models by tier, via OpenRouter) · `db` (Neon, the queue above) · **not** `media`,
**not** `storage` — the photo lives in memory for the request so `clarify` can re-read it.

## `compare` is code, not a model

sympy, in `src/agent/mathcheck/compare.py`. It is the cheapest, most-run, most deterministic step,
and models get answer equivalence wrong (`learnings.md`). `uncomparable` routes to `review`.

## Open decisions

1. `review` says `valid`, `solve` said wrong — who wins? Recommend `review`: stronger model, and it
   examined the working.
3. Cancelling an in-flight call saves latency and most, not all, of the tokens already generated.
4. Student and `solve` wrong the same way settles the row as correct. Rare, fails mild — accepted.
5. Message 1 after the whole fast pass (drafted) vs per row.
6. `read_ok` per row (as specified) plus `uncertain_field`, since a bare flag can't say what to ask.
7. Correction keyboard lists every task, not only disputed ones — a misread can wrongly *clear* a row.
8. `read_page` model — undecided on one page. See `learnings.md`.
