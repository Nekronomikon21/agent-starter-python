# Problem

**Stage 1 — Identify the limits of your current agency.**

> Draft v2, 2026-09-04. **Reframed:** this is a *checker*, not a solver. Assumptions marked ⚠️.

## The problem, in my words

I've done the maths. I have an answer on the page. **I don't know if it's right** — and that's a
worse place to be than not having started, because I can't tell the difference between "done" and
"confidently wrong."

The back of the book, when there is one, gives the *final answer only*. So it tells me I'm wrong and
nothing else. I then re-read my own working looking for my own mistake, which is exactly the thing I
already proved I can't do — I made the mistake because that step looked correct to me, and it still
looks correct to me on the second read. That's the loop nobody gets out of alone:

- **Right answer, no confidence.** I move on unsure, and never find out I got lucky.
- **Wrong answer, no diagnosis.** I know it's wrong. I don't know *where*, so I redo the whole thing
  and often reproduce the same slip.
- **Nobody available to look.** A teacher would glance at it and say "line 2 — you dropped the
  minus." That five-second glance is the thing I can't get at 21:00.

What I want is that glance: **is it right, and if not, which line did it go wrong on, and why.**

## Why an agent (not just a script or a calculator)

- **A calculator gives me the answer, which I already have.** It can't look at *my* working.
- **The input is a photograph of handwriting.** My steps, in my hand, next to a printed problem. No
  parser handles that; reading it *is* the intelligence.
- **Finding the *first* wrong step is a judgement call.** One slip at line 2 makes every line after it
  "wrong" — but there's only **one mistake**. Telling me that is teaching; listing four errors is noise.
- **Marking has to be generous.** `0.5`, `1/2` and `2/4` are the same answer. A different-but-valid
  method is not a mistake. Getting that wrong is worse than saying nothing.

## Why a Telegram bot (not a web app)

- **The camera and the chat are in the same hand.** Photograph the page, send it. No URL, no upload
  button, no login.
- **No account to create.** ⚠️ *Assumption: a kid uses it directly.* Telegram already authenticated
  them; every message arrives with a verified `from.id`.
- **Cheap to abandon.** If it's not useful after a week, nothing was built that must be maintained.

## What "done" looks like

I photograph the problem with my working next to it. Within a few seconds: *"Your answer x = 7
doesn't come out — everything's fine down to line 2, but there you multiplied 3(x − 4) into 3x − 4;
the −4 gets multiplied too."* One mistake, named, at the right line. If I was right, it says so
plainly and I move on.

## The decision this reframing reopens (open, 2026-09-04)

v1 was going to trust a strong model with no self-check, on the grounds that a wrong solution is
visible in the steps. **That reasoning doesn't survive the reframing.** A verdict is a single bit —
"you're wrong" shows the user nothing they can inspect, and a *false* "you're wrong" sends a kid to
rewrite a correct answer. See `failure_modes.md`; decision pending.
