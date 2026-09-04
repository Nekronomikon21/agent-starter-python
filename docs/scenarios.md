# Scenarios

**Stage 3 — Concrete walkthroughs.** This is the stage-8 test checklist.

> Draft v3, 2026-09-04. Real inputs → expected result. One line each.

## Right

1. `3(x − 4) = 2x + 5`, answered `x = 17` → *"✓ x = 17."* Nothing more.
2. `2/3 + 1/4`, answered `11/12` → confirmed.
3. Four problems, all correct → one message, and `review` never runs.

## Wrong

4. Same equation, working `3x − 4 = 2x + 5` → `x = 9` → *"line 1 — 3(x − 4) is 3x − 12, the −4 gets
   multiplied too. The rest follows fine."* **Must not** also flag lines 2–4.
5. `2/3 + 1/4` answered `3/7` → denominators added; needs a common denominator. Stated as a rule.
6. Fixed and re-sent → checked fresh, no memory of the old attempt.
7. Asks "just show me" after a diagnosis → full solution.

## Two messages

8. Four problems, 2 and 4 wrong → **msg 1** (after the fast pass): *"1 and 3 look right. For 2 I get
   17, for 4 I get 11/12 — checking your working."* **msg 2**: first wrong line for each.
9. Msg 1 flagged 2, `review` returns `valid` → *"Actually your 9 is right — my first pass had it
   wrong."* Never silence, never leaving the flag standing.

## Shaky reading

10. `read_ok = 0` on 2's answer **and** disputed → *"For 2 I read your answer as 1 — is that right?"*
    No verdict until they reply.
11. `read_ok = 0` but the row **cleared** → **no question**. This is the gate that keeps it quiet.
12. `read_ok = 1` and disputed → straight to review, treated as a real mistake.
13. Answer is `{1, 3}` or a sketch → skip typing, targeted re-read of that field; if still unclear,
    poll of 2–3 likely readings + "none of these".

## Correction

14. Taps **"you misread my answer"** → labels `1 / 2 / 3a / 3b` → taps `3b`, types `11/12` → row
    re-runs from `compare` only → *"With 11/12 for 3b — that's right, my mistake."*
15. A correction makes a previously **cleared** row wrong → re-issued honestly. (Why the keyboard
    lists every task.)

## Marking generously

16. `0.75` vs `3/4`, `2/4` vs `1/2`, `17 = x` vs `x = 17`, an unsimplified surd → **right**.
17. Quadratic factorised where the class used the formula → **right**.
18. Right answer via two errors that cancel → says right, then notes the step that doesn't follow.
19. Answer only, no working, wrong → *"Not right — send your working and I'll find where."*

## Reading edge cases

20. Whole page, four attempted → "Which one?"
21. Blurry / cropped → names what's unreadable, one retake tip, **no verdict**.
22. Geometry with an unlabelled diagram → asks for the labels. **Never invents an angle.**
23. Ambiguous `1`/`7` → asks; never picks one and delivers a verdict on it.
24. Crossed-out lines, arrows, working out of order → follows if it can, else asks for the order.
25. Not maths → polite decline, no paid call.

## Infrastructure

26. Photo download times out → honest retry message, bot stays up.
27. Solution full of `*`, `_`, `^` → renders correctly in a **real chat**, not just the log.
28. Unknown user with allowlist set → declined **before** any paid call.
29. Two instances on one token → `409`; fixed by the dev/prod token split.

## The two gate sets (stage 8, hand-marked)

30. **False-accusation set** — 10 *correct* answers in varied forms and methods, real handwriting.
    Every one must come back right. **A single false "wrong" blocks release.**
31. **First-divergence set** — 10 attempts with a planted error at a known line. The bot must name
    that line, and only that line.
