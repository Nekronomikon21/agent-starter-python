# page01.jpg — ground truth

Squared paper, spiral notebook, Russian notation (`Отв:` = answer), comma decimals.
Five problems. №3 and №5 confirmed by the user 2026-09-04.

| № | Statement | Student's answer | Correct | Verdict | First divergence |
|---|---|---|---|---|---|
| 1 | `(2(x+7))² = 81` | `x = -2,5` | `{-2,5; -11,5}` | **differ** | `2(x+7) = 9` — only the `+9` branch; it's `±9`. A *lost root*, not a wrong one |
| 2 | `\|4(x+2)\| = 82` | `{19, -23}` | `{18,5; -22,5}` | **differ** | `x+2 = ±21` — 82/4 is 20,5, not 21 |
| 3 | `x+7 = y+8` / `x = y+1` | `x = 6, y = 7` (a digit crossed out) | **infinitely many** | **uncomparable** → review | Both equations reduce to `x = y+1`, so the system is degenerate. A specific pair isn't the answer — and `(6, 7)` doesn't even satisfy `x = y+1` |
| 4 | `y = x+2` | a **drawn graph** | — | **uncomparable** | Must route to `review`. Never fail the kid |
| 5 | `2^(x^x) = 2^27` | `x = ±3` | `3` | **differ** | `x = √27` — treated `x^x` as `x²`. It's `x^x = 27`, so `x = 3` by inspection (3³ = 27). Their `3` is right; the `-3` is an extraneous root. The `√27` line is the first divergence (confirmed) |

## What this page taught us

Four notations that broke `compare` and were on nobody's list:

- **Comma decimals** — `4,5` is four and a half. The splitter read it as two answers, so `-2,5` vs
  `-2.5` returned `differ`. A correct kid failed by a comma.
- **`±`** — `x = ±3` states two values.
- **`∈`** — `x ∈ {19, -23}` states an answer the same way `=` does.
- **`Отв:`** — a label. Left in place it trips the prose check and the whole answer goes
  `uncomparable`.

Also: Russian sets separate with `;` **because** `,` is the decimal point. That disambiguates
`{-2,5; -11,5}` — which is why the splitter prefers `;` when it's present.

## A category the design missed: answers that are statements

№3's correct answer is **"infinitely many solutions"** — not a number. Same family as "no solution"
and "any x". `compare` returns `uncomparable` for these and routes to `review`, which is the right
behaviour, but two consequences follow:

- `solve` must be able to *say* such an answer, so `correct_answer` is not always numeric.
- These rows **always** cost a review call, since `compare` can never clear them.

№5 also breaks an assumption: `x^x = 27` isn't solvable by elementary algebra. sympy won't get it;
the model has to see that 3³ = 27. Worth knowing before assuming school problems are easy solves.

## Still needed for the gate sets

This page has no *fully correct* solution on it, so it can't populate the false-accusation set — the
one that matters most. Need 2–3 pages of correct work, plus one deliberately blurry.
