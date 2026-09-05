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
| `bot` | Telegram wiring only | update → handler → the modules above |
| `store` | the last page per user | `mathcheck_sessions`, so a correction outlives a restart |
| `app` | production entrypoint | FastAPI + webhook; local runs poll instead |

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
| `solve` | `balanced` — measured on page01: `fast` scored 1/3, `balanced` 3/3 (`learnings.md`) |
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

`pending` → `cleared`, or `disputed` → `awaiting_user` / `diagnosed` / `exonerated` /
`wrong_problem`. A drawn answer goes straight to `uncheckable`, an unanswered one to `unanswered`,
a row with no question text to `unreadable` — none is ever solved or reviewed.
A user correction returns any row to `solved` for a fresh `compare`.

`failed` is the one state we own rather than describe: a model call for that row errored, so we
cannot judge it. It is deliberately not `uncheckable` — telling a student their answer is a drawing
when our own request 400'd is a lie about whose fault it is.

**A failure is always one row wide.** `solve` failing hands the row to `review`, which reads the
photo and never needed our answer; `review` failing marks that row `failed` and the worker keeps
walking the page. One provider error must never cost the other four rows.

`exonerated` exists so a retraction is a state the system owes, not a message we hope got sent.

## Data

Table `mathcheck_sessions` (`src/agent/mathcheck/store.py`), **one row per user** — the last page
they sent:

| Column | Notes |
|---|---|
| `telegram_id` | primary key. Telegram's verified id; every query scoped by it |
| `photo_file_id` | Telegram's id for the photo. **We store no bytes** — a correction re-downloads it |
| `media_type` | always `image/jpeg` from Telegram |
| `awaiting` | the label we asked about, NULL when we didn't |
| `rows` | JSONB: the settled `Row`s, via `store._dump_row` |
| `updated_at` | |

**Not one row per problem, and not a work queue.** The original design here was a normalised
`mathcheck_problems` table "both workers read and write" — but that queue never came to exist: the
race in `pipeline.py` happens in memory inside a single request and never touches a database. What
actually needs persisting is narrower, so the schema matches the narrower job. The rows are JSONB
because they are read and written whole, never queried by field; a column per `Row` attribute would
cost a migration every time the pipeline grows a status and buy nothing.

`Problem`'s own fields (`label`, `statement`, `student_answer`, `answer_kind`, `read_ok`,
`uncertain_field`) live inside that JSONB, alongside `correct_answer`, `answer_source`, `status` and
the `Review` verdict. An empty `statement` is not a column but a guard — no question text means
nothing to solve *and* nothing to check working against.

**Migration filenames are prefixed too**, not just tables: `001_mathcheck_init.sql`. The `_migrations`
ledger is shared across every project in the database and keyed on the bare filename, so a second
`001_init.sql` is silently skipped — no error, just a missing table (`docs/learnings.md`).

## Where state lives

One page's rows live in memory for the length of a request. Across messages — the correction button,
a typed clarify reply — the last page per user lives in `mathcheck_sessions`, so it **survives a
restart**, which a deploy performs on every release. A user with no stored page still gets the
honest "that page is gone" reply.

The photo is the part that could have forced a blob store, and doesn't: we keep Telegram's
`file_id` and re-download on demand, so `storage` and `media` stay out of this project entirely.

**Up to `bot.MAX_CONCURRENT_PAGES` (8) pages run at once.** PTB processes updates one at a time by
default, which is invisible with one user and brutal with two — the second person's photo waits
behind the first person's whole pipeline and they get no reply at all, ack included. The cap is not
`concurrent_updates(True)`, which means 256: every page is a read, a solve per row and an Opus
review, so unbounded fan-out is a bill.

Sessions are keyed per user, so users never collide. One user sending several photos at once is the
loose end: `SESSIONS[uid]` holds the last page *started*, so a correction lands on that one.

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
