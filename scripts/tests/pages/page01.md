# page01.jpg — ground truth

Squared paper, spiral notebook, Russian notation (`Отв:` = answer), comma decimals.
Five problems. **Читатель: confirm the ⚠️ lines — my reading of them is uncertain.**

| № | Statement | Student's answer | Correct | Verdict | First divergence |
|---|---|---|---|---|---|
| 1 | `(2(x+7))² = 81` | `x = -2,5` | `{-2,5; -11,5}` | **differ** | `2(x+7) = 9` — only the `+9` branch; it's `±9`. A *lost root*, not a wrong one |
| 2 | `\|4(x+2)\| = 82` | `{19, -23}` | `{18,5; -22,5}` | **differ** | `x+2 = ±21` — 82/4 is 20,5, not 21 |
| 3 | ⚠️ `x+7 = y+8` / `x = y+1` | ⚠️ `x = 6, y = 7` (a digit is crossed out) | — | — | Both equations are the same line, so the system has infinitely many solutions. A `read_ok = 0` case |
| 4 | `y = x+2` | a **drawn graph** | — | **uncomparable** | Must route to `review`. Never fail the kid |
| 5 | ⚠️ `2^(x²) = 2^27` | `x = ±3` | `{3√3, -3√3}` | **differ** | `x = √27` is right; `√27 = 3√3 ≈ 5,196`, not 3 |

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

## Still needed for the gate sets

This page has no *fully correct* solution on it, so it can't populate the false-accusation set — the
one that matters most. Need 2–3 pages of correct work, plus one deliberately blurry.
