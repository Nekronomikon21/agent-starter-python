# Journal

This is the running trace of your thinking as you build. It's the most important
document in the project — more than any single piece of code.

**How to use it**
- Add an entry at *meaningful* moments: a decision (and **why**), something you
  learned, a dead end you backed out of, a milestone reached.
- **Not** every edit. Capture the thinking, not the keystrokes.
- Always **timestamp** with date **and** time. Newest entries go at the bottom.
- Both you and Claude should add entries.

Format:

```
## YYYY-MM-DD HH:MM — Short title
What you were trying to do, what you decided, and why. What you learned.
```

---

## 2026-05-29 12:00 — Project initialized from the agent starter
Cloned the starter. Next: fill in `docs/problem.md` (what can't I do today?) and the
"Your project" section of `README.md` (what am I building?). Then design before coding.

## 2026-06-15 — Added example #3: inspiration_bot (Telegram, both-directions agent)
Built the third worked example as a Telegram bot, deliberately keeping the repo single-spirit
(pure Python toolbox) instead of going React/Next + Better Auth — that's a separate starter,
not this one. Telegram dissolves the "auth" question: identity is the verified `telegram_id`
on every update; the users table is keyed on it; authorization is a thin optional allowlist.

Key decisions:
- **Environments as a first-class concept.** Added `ENVIRONMENT` (+ telegram/cron settings) to
  config.py. Same code, different *values* in `.env` vs Railway. Separate bot token per env is
  mandatory, not hygiene: two consumers on one token = Telegram 409. This is the example's spine.
- **Webhook vs polling, chosen by environment.** Local = long polling (no public URL); prod =
  webhook into a FastAPI app that also hosts the cron endpoint. One codebase.
- **Cron = frequent tick + per-user due-check.** Railway Cron (hourly) → `run_due_sends`, which
  honours each user's hour/timezone/cadence and is idempotent via `last_sent_at`. `is_due` is a
  pure function, unit-tested offline. Same `cron` command forces an immediate send in dev.
- **Tool-using agent with injected scope.** pydantic-ai `Deps(telegram_id)` is injected, never a
  tool argument — so the model physically can't reach another user's data. Read tools granted
  freely; one reversible write tool (set_schedule); delete + image-gen kept out of the model's
  hands (human-confirmed / orchestrated). This is the security lesson I most want to land.
- **Packaging:** multi-file example as a package (`examples/__init__.py` + the bot's `__init__.py`),
  so absolute imports work under both `python -m ...` and `fastapi run ...` (verified how
  fastapi-cli walks `__init__.py` parents). Added `pythonpath=["."]` so pytest can import it.

Verified the installed APIs before writing (pydantic-ai 1.104 deps/tools/BinaryContent; PTB 22.8
Application/handlers/webhook) rather than trusting memory. ruff + pyright clean; 9 offline tests.

## 2026-08-17 15:45 — Local dev debug: Proton VPN silently blocks Postgres on 5432
Tried to run `examples.inspiration_bot.bot` locally and hit three failures in a row. Worth
recording because only the last one was interesting, and it cost real time to find.

1. `TELEGRAM_BOT_TOKEN` was still the `.env.example` placeholder → PTB raised `InvalidToken`.
2. A one-off `TimedOut` on the first `get_me` — transient, PTB's default read timeout is 5s.
3. The real one: `post_init` → `apply_migrations` → asyncpg died with
   `ConnectionResetError [WinError 64]` during the TLS upgrade to Neon.

**Proton VPN was up and held the default route.** It forwards HTTPS fine but won't carry
Postgres on 5432. The diagnosis that actually nailed it: TCP to `example.com:9999` — a port
with nothing listening — "connected" in 0.0s. That means the tunnel was accepting *every*
outbound connection locally and only then deciding whether to forward it. Confirmed by
hitting the *same Neon host* on two ports: 443 completed a TLS handshake in 0.4s, 5432
stalled ~20s then RST. Same host, same IPs, only the port differs → not Neon, not our code.
VPN off → closed ports time out as they should, and Neon connects in 2.8s (PostgreSQL 18.4).

**Lesson for next time:** when a service is unreachable, don't stop at "TCP connects, so the
network is fine" — under a transparent tunnel a successful connect proves nothing. Probe a
port you *know* is closed as a control, and compare two ports on the same host to separate a
port block from a host problem.

**Also worth knowing:** this never affects the Railway deploy — Railway reaches Neon from its
own network with no VPN in the path. So "works deployed, broken locally" is expected here.

Follow-up worth doing: `agent-doctor` has no Telegram check at all and its DB check didn't
catch this either — it would have reported a healthy setup. A live `get_me()` plus a real
connect would have found all three failures in one command.

## 2026-08-17 16:00 — Two real bugs behind "photos don't work, bot went quiet"
Reported symptoms: the bot never recognises pictures, and it stopped replying entirely.
Three distinct causes, only two of which were the code's fault.

**1. Photos: PTB's default timeouts are too tight (real bug, fixed).**
`on_photo` failed 4/4 with `TimedOut` inside `photo.get_file()`. `HTTPXRequest` defaults to
`read_timeout=5.0`, and this link to Telegram is consistently marginal at 5s — the same reason
an earlier `get_me` timed out at 5s but succeeded at 20s. Text ingestion worked throughout,
because a text message needs no file download. **That asymmetry is the tell: text fine +
photos never = timeouts, not vision.** `build_application()` now sets 20s connect / 30s read /
60s media-write, and 40s for the long-poll. These are ceilings, not waits — free on a fast link.

**2. Missing `tzdata` (real bug, fixed).** `ZoneInfo("UTC")` raised `ZoneInfoNotFoundError` —
`available_timezones()` returned **0**. Windows has no IANA tz database and we never depended on
`tzdata`. `run_due_sends` builds a `ZoneInfo` per user *before* the `force` check, so the morning
job would have crashed on the first real user. It looked fine earlier only because the table was
empty. One test module couldn't even be collected. Added `tzdata`; 16 tests pass (was 0 + error).

**3. The bot going quiet was my own debugging (not a bug).** I had written a wait-script that
polled `getUpdates` every 3s to confirm the poller was up. Telegram terminates the *existing*
long-poll whenever a new `getUpdates` arrives, so my probe repeatedly killed the poller's poll
and raised `Conflict` inside it. With no error handler registered, that stopped the updater while
the process stayed alive — a bot that looks healthy and never answers again.

Lessons, both now in `failure_modes.md`:
- **Never call `getUpdates` to health-check a running bot.** The check destroys the thing it
  measures. Read the log instead. The 409 trick is valid exactly once, not in a loop.
- **"The process is running" is not a health check.** Added `add_error_handler` so a stopped
  updater is at least loud. Worth knowing this failure exists in the webhook path's shape too.
- A misleading first diagnosis: I saw two `python.exe` running the bot module and called it two
  pollers. It wasn't — `main()` logged once; the child is a loguru `enqueue=True` spawn artifact
  on Windows, which re-imports the module under a non-`__main__` name so the guard holds. Check
  what a process actually *did* (its log) before trusting what its command line implies.

## 2026-09-03 23:26 — Project defined: a photo-in, steps-out maths homework bot
Started the real project (docs/ had been untouched templates until now). Walked stages 1–3 before
any code, per the method. The decisions worth recording:

- **Scope: school-level homework, for kids.** Not university, not olympiad. A bounded domain is the
  single biggest reliability lever available — and it's a real audience we can test with at a table.
- **Photo is the front door.** The insight in `problem.md`: the maths isn't the friction, *getting
  the problem off paper* is. Nobody retypes `3(x − 4) = 2x + 5` at 21:00. Text input still works
  because it costs nothing and it's the only way to write offline tests.
- **Steps, never a bare answer.** A final number is exactly the thing search already provides badly.
- **No self-verification in v1 — decided, not overlooked.** Chose a strong model + an honest standing
  caveat over a sympy check or a two-solve comparison. Recorded in `problem.md` as an *accepted gap*
  with a named trigger for revisiting: any wrong answer seen in real use. I pushed back on this (a
  wrong worked solution gets copied into a notebook and learned) and was overruled deliberately —
  which is the right way for it to be overruled.
- **The mitigation that survived anyway: restate the problem before solving it.** It's not
  verification of the maths, it's verification of the *reading* — and photo misreads (a 6 for a 5, a
  dropped exponent) are a failure class no model tier fixes. One line, near-zero cost, catches it.

Two failure modes I'd have missed without the inspiration_bot scars: **PTB's 5s default read
timeout** kills every `get_file` on this link (text works, photos never do — that asymmetry is the
tell), and **maths notation collides with Telegram Markdown** — `*`, `_`, `^`, `\` are exactly the
control characters, so a correct solution can arrive mangled or not at all. Both are in
`failure_modes.md` before a line of code, rather than after a debugging evening.

Next: stage 4 (`policy.md` — the system prompt and the restate/solve/follow-up flow) and stage 5
(`architecture.md`), then tests before the bot.

## 2026-09-04 11:51 — Reframed: a checker, not a solver. Which reopens the verification decision.
One sentence from the user moved the whole project: *"I have solved a math problem, but I don't know
whether I'm right. The bot should first check my answer and if it's wrong find my mistake."*

Yesterday's design solved problems from a photo, and treated the kid's own pencil working as a
**distractor to ignore** — it was literally a row in `failure_modes.md`. That working is now the
payload. Rewrote stages 1–3 (`problem.md`, `user_stories.md`, `failure_modes.md`, `scenarios.md`,
README) rather than patching them; the failure surface is different enough that patching would have
left yesterday's assumptions buried in the text.

**What actually changed, and why it matters:**

- **The dominant failure inverted.** For a solver, the risk is a wrong solution — visible, because
  the steps are on screen and a user can inspect them. For a checker, the risk is a wrong **verdict**,
  which is a single bit with nothing to inspect. And it's *asymmetric*: a false "you're wrong" sends
  a kid to rewrite a correct answer and to distrust their own work. That's worse than any wrong
  solution the previous design could have produced.
- **So the "no self-verification" decision from yesterday no longer follows from its own reasoning.**
  I accepted it then because errors would be visible in the shown steps. That argument doesn't
  survive the reframing, so I've marked it *open* in `problem.md` rather than silently carrying it
  forward. Flagged for the user to re-decide — with the observation that checking *equivalence* is a
  far narrower and cheaper use of a CAS than solving, so the middle path is much better value here
  than it was yesterday.
- **Anchoring is now a hard rule.** If the model sees the student's wrong working before it solves,
  it tends to agree with it — so a wrong answer gets a tick. **Solve independently first, let their
  steps in only for the comparison.** This is an ordering constraint on the architecture, not a
  prompt nicety, and it's the kind of thing that would have been near-impossible to retrofit.
- **Generous marking is a first-class requirement.** `2/4` vs `1/2`, `0.75` vs `3/4`, `17 = x` vs
  `x = 17`, factorising where the class completed the square. Every one of those is a *correct*
  answer that a naive string comparison calls wrong. This is where a checker loses a user for good.
- **One mistake, not four.** A slip at line 2 makes lines 3–6 "wrong" as well, but there is only one
  error. Report the **first divergence** and say the rest follows correctly from where they were.
  That's the difference between teaching and marking.
- **Reading handwriting, not print.** Harder, and it introduces a failure the solver never had: a
  misread digit produces a confidently explained mistake *at a line the kid never wrote*. Hence:
  restate the reading before any verdict, and when uncertain **ask, don't accuse**.

Added two named test sets in `scenarios.md` that serve as the stage-8 gate — a **false-accusation
set** (10 correct answers in varied forms and methods; a single false "wrong" is a release blocker)
and a **first-divergence set** (10 attempts with a planted error at a known line). These are the two
things that decide whether the bot is any good, and neither can be checked by unit tests.

Next: the open verification decision, then stage 4 (`policy.md`) and stage 5 (`architecture.md`).

## 2026-09-04 12:06 — Architecture: speculative race between a fast solver and a slow reviewer
The user designed this one; I mostly stress-tested it and wrote it down (`docs/architecture.md`).
Model 1 reads the page into rows. Models 2 (fast, re-solves from the statement) and 3 (strong, walks
the student's working) start **at the same time** over those rows; any row where model 2 agrees with
the student is settled instantly and model 3 is cancelled on it — or skips it if it hasn't got there.

**Why it's good, beyond the obvious latency win.** I'd raised two objections yesterday and this
design absorbs both:

- *Anchoring* becomes structural. `solve` receives only the `statement` column — the student's steps
  physically aren't in its context. That's a wall, not a prompt instruction that can drift.
- *"Don't put the cheap model on the verdict"* — **I was wrong about this and said so.** The fast
  model can only ever *clear* a row (agreement with the student, i.e. two independent sources
  concurring). Every disagreement escalates to the strong model. That's the correct use of a cheap
  tier: a fast path with escalation, not a decision-maker.

The consequence I hadn't seen until I walked the truth table: the case *student right, fast model
wrong* — the false accusation I've been most worried about since the reframing — is exactly a
disagreement, so it routes into the strong model automatically. The expensive check runs only where
it's needed, and it's already in flight by the time we know we need it.

**The one flaw, and it's a serious one.** `review` runs *only* on rows where something has
apparently gone wrong. Prompt it as "find the student's mistake" and it will find one — in correct
work too. A model asked to locate an error in a flawless derivation invents a plausible one. That
turns the best safety mechanism in the system into a generator of false accusations. So `review`
must be framed as "are these steps valid?" with **exoneration as a first-class outcome**, and it
must never see `correct_answer` (which would tell it what conclusion to reach). Logged as open
decision 2, and it's the highest-risk detail in the whole design.

Two smaller calls: `compare` is **plain code, not a model** (sympy) — `2/4`, `0.5` and `1/2` are one
answer, and it's the most-run step in the system, so determinism is free quality. And `read_page`
must capture the student's working **in order**, not just their final answer; `review` has nothing
to walk without it. That column would have been easy to leave out and expensive to add later.

The database earned its place after all — I'd questioned it as over-engineering when it looked like a
hand-off between two steps, but with two workers racing over shared rows it's a genuine work queue
with per-row state, which is what makes cancel-and-skip safe.

Next: stage 4 (`policy.md`) — the reply shapes for cleared / diagnosed / uncertain, and the tone
rules for telling a child they're wrong. Then tests before any bot code.

## 2026-09-04 12:09 — Two messages: the fast answer, then the explanation
User added: the moment the fast model finishes, send a first message with the correct answers for
the problems the student got wrong; the diagnosis follows. Good for the user (a number to retry with
immediately, instead of staring at a spinner), and it collides with two things already written.

**It spends the false-accusation guard before it fires.** The whole point of racing the strong model
was to catch *student right, fast model wrong* before the kid hears about it. Announcing at the end
of the fast pass means the kid has already been told, and `review` can only retract. Prevention
demoted to correction.

The fix turned out to be **wording, not architecture**: message 1 *reports* rather than *judges* —
"I get 17 for #2, checking your working now," never "you're wrong." Identical information, identical
speed, but a number the bot got is revisable where an accusation isn't. Retraction is now a designed
message ("actually, your 9 is right; my first pass had it wrong") and `exonerated` is a row
**state**, so a retraction is something the system owes rather than something we hope got sent. The
general shape is worth remembering: when a fast path publishes before a slow path verifies, weaken
the *claim* rather than delay the message.

**The second collision is with our own problem statement, and I flagged it rather than solved it.**
`problem.md` says the thing that fails you today is that the back of the book gives the final answer
and nothing else. Message 1, taken literally, *is* the back of the book, and it arrives first and
short, so it's the one that gets read. I still think the call is right (knowing the answer lets you
retry it yourself, which beats reading someone else's explanation), but it puts a real burden on
stage 4: message 1 has to stay thin enough that the diagnosis is visibly where the value is. Carried
into `policy.md` as a tone constraint rather than left as a good intention.

Open decision 5 added: message 1 after the whole fast pass (drafted) vs. per row, which is faster
but noisy on a page of eight.

## 2026-09-04 12:49 — Asking the user: gated by a 0/1 read flag, with a ladder and a back-door
User specified the whole misread interaction: ask the user (reply is "yes" or the number); if the
answer isn't something you can type — a set, a graph — re-read the image instead; if that fails too,
offer a poll of likely readings. Plus a standing **"you misread my answer"** button on every reply,
listing task labels (1, 2, 3a, 3b), which reopens one task for a typed answer or a new photo.

And the constraint that makes it affordable: **don't confirm every answer.** `read_page` marks each
task 0 or 1 at read time — 1 means "clear, don't bother the user."

**The refinement I added: two gates, not one.** `read_ok = 0` alone isn't enough to justify a
question. The bot should ask only when the reading was shaky **and the row is disputed** — because a
shaky reading that still agreed with the correct answer needs no confirmation. That drops the
question rate to roughly the intersection of two already-small sets, and it means the common case
(everything right) is silent. Worth noting the general form: don't validate an input until something
downstream actually depends on it being right.

**Also added `uncertain_field`.** A bare per-row 0/1 says *something* is shaky but not *what*, and
`clarify` needs to know whether to ask about the answer, the statement or the steps. One extra enum
column turns a vague "did I read this right?" into "for 3a I read your answer as 1 — is that right?"

**And `label`.** The user's example — 1, 2, 3a, 3b — killed my assumption that a row index would do.
Tasks have names as written on the page, and that's what the user taps. Easy to add now, migration
later.

Two notes on the ladder as designed. Step 2's re-read must be **targeted at one field**, not a second
full pass: re-running the same prompt on the same image mostly reproduces the same misreading, while
"transcribe exactly the final answer of 3a" is a genuinely different, narrower task. And the
correction back-door re-runs a row from `compare`, **never** from `read_page` — once the user has
told us what they wrote, that is authoritative and no model gets to second-guess it (`answer_source
= user_confirmed`).

**One honest limit.** `read_ok` is a model's own estimate of its reading, and models are overconfident
— it will occasionally return 1 on a misread. So the flag reduces interruptions; it doesn't make
misreads impossible. That's precisely why the `valid` exit and the correction button both exist: three
independent nets, each cheap, none load-bearing alone.

Next: `policy.md` (stage 4) — exact wording for both messages, the clarify question, the poll, the
retraction, and the tone rules.

## 2026-09-04 16:14 — Docs tightened, risks re-rated, policy.md drafted
Cut the water: user_stories 50→34, scenarios 110→72, failure_modes 72→59. Dropped stories that
described Telegram rather than the product (`/start`, "send a photo", "type instead"). Added the rule
to `CLAUDE.md` so it holds for every doc from here.

**The risk re-rating had real content, not just trimming:**
- **`compare` is the #1 risk, not `solve`.** Student answers reach sympy as OCR text — `x = 17 cm`,
  `17`, `{1, 3}`, `1/2 or 0.5`. Parsing *that* is where a correct kid gets failed. It was one row
  among twenty; it should have been at the top.
- **`solve` slipping is low, not medium.** The user was right that school algebra doesn't trouble a
  modern model. That doesn't weaken the race — it names what the race is actually for: the disputed
  pile is reading and comparison failures, which is exactly what `review`'s two exits catch.
- **Anchoring left the table.** `solve` structurally cannot receive the student's steps, so it's an
  invariant, not a live risk. Rating a solved problem as a risk hides the real ones.

Consequence for stage 6: `compare` deserves the heaviest test coverage in the project — a table of
real answer strings run offline, no LLM, no photo. Cheapest tests here, guarding the worst failure.

`policy.md` drafted: tone, control flow, the three prompt briefs (including what each model must
**never** receive), and literal message templates for msg 1, diagnosis, retraction, `wrong_problem`,
the clarify question, the poll, and the correction flow. Writing the wording out was worth it — it
forced the "all cleared → no message 2 at all" case, which nothing had specified.

Next: stage 6. `compare` first, offline, before any bot code.

## 2026-09-04 16:28 — `compare` built and tested; prose parses as maths
Stage 6 started with the #1 risk, offline: 34 tests, no model, no photo, no credentials. All green,
ruff and pyright clean.

**The finding worth the whole exercise:** `"see the graph"` parses as `see*the*graph` — a perfectly
valid sympy product of symbols — so it came back **`differ`**, not `uncomparable`. A kid who writes a
word answer gets told they're wrong. It's the exact failure this module exists to prevent, it fails
*silently*, and nothing in the design docs predicted it; only running it did. Fixed by rejecting any
3+ letter run that isn't a known function (variables are 1–2 chars, prose isn't).

Also: `parse_expr(global_dict={})` breaks the parser (its generated code needs sympy's own names) —
blank `__builtins__` instead, which is the actual eval risk. `rationalize` is required or 0.75 and
3/4 compare through float noise. `√8` needs a regex, not a character swap, or it parses as a symbol.

`uncomparable` is deliberately never `differ`: anything unreadable routes to `review` rather than
failing the student. That asymmetry is tested explicitly.

Next: `read_page`. Blocked on real handwriting samples — 5–10 photos, some correct, some with a known
mistake at a known line.

## 2026-09-04 16:39 — Vision research: 87% of errors are transcription, and a flash model wins
Read Levine et al., *Automated Grading of Handwritten Mathematics Using Vision-Capable LLMs*
(arXiv 2605.19043) — the same task as this project, published this year.

- **87% of errors in their best model were transcription failures, not rubric misapplication.**
  Reading the page dominates everything. Independent confirmation of the risk re-rating: `solve`
  really isn't the problem, and effort spent on solving quality is misallocated.
- **Gemini 3 Flash beat GPT-5.1 and GPT-5-mini** (89–99% vs 87–95%). A flash-class model won on
  handwriting. Worth knowing before assuming the expensive tier reads best.
- **Their errors skewed to false positives** — hallucinating correct work — rather than false
  negatives. That's the mild direction for us; our worst case is the rarer one in their data.
- **Image capture beats prompt tuning.** Blur and rotation caused most failures, and they say gains
  come from better photos, not better prompts. So the retake guidance in `policy.md` is doing more
  work than any prompt I could write.
- **They mishandled equivalent expressions** (rounded decimals vs exact fractions) — a model doing
  the comparison. That is exactly what `compare` was built to avoid, confirmed independently the same
  day I built it.

**The conflict worth thinking about:** they deliberately chose **one-shot** transcribe+grade over
separated steps, citing higher accuracy. Our pipeline separates. I don't think we should collapse it
— separation is what buys the anchoring wall and the fast/slow race — but there's a change that takes
most of the benefit: **give `review` the photo, not just the transcribed steps.** The anchoring wall
constrains `solve`, which must never see the student's work; `review` is already allowed to see it.
Today `review` reasons over a transcription that may itself contain the error it's hunting for, which
makes the `valid` and `wrong_problem` exits weaker than they look. Logged as open decision 8.

Model choice: the Flash line has moved past the paper's version (`gemini-3.8-flash` shipped two days
ago; 3.7 is the stable candidate) and our `fast` tier is still `gemini-2.5-flash-lite`. But the
paper's own headline is that *image capture* dominates — so picking from a leaderboard would be the
wrong move. Bake-off on the user's real photos when they arrive.

## 2026-09-04 16:40 — `review` reads the photo; `read_page` stops transcribing working
Applied open decision 8. `review` now receives the **image** plus the `statement` as read, and no
transcribed steps.

Two things fall out that are worth stating, because neither was obvious when I proposed it:

**`statement` changes role.** It's no longer input for review to reason *from*; it's the thing to
check the page *against*. That's what finally makes `wrong_problem` mean something concrete — *the
statement I was given isn't what's on this page* — rather than a vague mismatch feeling. Passing the
statement is what preserves that exit; reading everything fresh from the photo would lose it.

**`steps` stopped being load-bearing, so it's gone.** Nothing consumed it once review read the page
itself. Keeping a column no decision depends on is exactly the indirection CLAUDE.md warns against —
and dropping it makes the read pass cheaper and shorter, which matters because that pass is the
critical path for message 1. `uncertain_field` narrows to `statement` or `answer` for the same reason.

The anchoring wall is untouched: it always constrained **`solve`**, which still receives only the
statement and still cannot see the student's work. `review` was always allowed to look — it just
used to look through a lossy transcription.

## 2026-09-04 16:46 — First real page broke `compare` in four ways the docs never imagined
One photo (`scripts/tests/pages/page01.jpg`) and the module I shipped an hour ago was wrong on it.

**`-2,5` vs `-2.5` returned `differ`.** Comma decimals. My splitter treated `,` as an answer
separator, so a correct kid gets failed by punctuation — the exact #1 risk, in the first real input.
Three more the same page: `±3` wasn't expanded to two values, `∈` wasn't read as stating an answer,
and the `Отв:` label tripped the prose check and sent the whole answer to `uncomparable`.

The disambiguation that makes commas tractable: **Russian sets separate with `;` precisely because
`,` is the decimal point.** So `;` wins when present, and a bare comma is a decimal point only when
it sits between two digits. `19, -23` is still a list.

**Every one of these came from looking at a photo, not from thinking harder.** Yesterday's docs are
detailed and none of them predicted a comma. That's the argument for stage 6 running on real inputs
as early as possible — the design doc's list of edge cases is a list of the ones you can imagine.

The page also happens to contain three distinct diagnosis shapes, which is more than I'd have thought
to write by hand:
- №1 — a **lost root** (`2(x+7) = ±9`, only `+9` taken). The answer isn't wrong, it's *incomplete*.
  `compare` says `differ` on the count, which is right, but the explanation "you lost a root" is a
  different sentence from "line 2 is wrong". Worth checking `review` can tell those apart.
- №2 — plain arithmetic (82/4 read as 21, not 20,5). The ordinary case.
- №5 — the **last** line is the wrong one; `x = √27` is correct and `√27 = 3` is not. A useful
  counterweight to the assumption that mistakes happen early.

№4 is answered with a drawn graph — the `uncomparable` path, now tested with Cyrillic prose too.
№3 I can't read confidently (crossed-out digit, and the system is degenerate — both equations are the
same line, so it has infinitely many solutions). Logged as ⚠️ for the user to confirm.

**Still blocked on the set that matters most:** this page has no fully correct solution, so the
false-accusation set is still empty. That's the one where a single failure blocks release.
