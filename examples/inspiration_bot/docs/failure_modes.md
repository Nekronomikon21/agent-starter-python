# Failure Modes

> **Worked example** for the Inspiration Bot. (Stage 3: failure as UX. For an agent that
> *initiates* and *deletes*, this doc is the most important one.)

| What could go wrong | Likely / bad | How we handle it |
|---|---|---|
| Same bot token used in dev **and** prod | high / bad | Telegram `409 Conflict` — two consumers can't share a token. **Separate tokens per environment** (see `architecture.md`); the dev/prod split makes this structural, not a reminder |
| Dev run accidentally messages **real users** | medium / very bad | Dev uses a separate token *and* a separate database — there are no real users in the dev DB to message. The morning job loops over *its* environment's users only |
| Unsupported message type (voice, video, sticker) | high / mild | Friendly decline: "I can take photos and text for now" — never a silent drop or crash |
| Photo download / vision call fails | medium / mild | Tell the user it didn't go through and to retry; log the error; **the bot process stays up** for everyone else |
| An LLM / media / DB call is down mid-chat | low / bad | Catch per-handler: reply with an honest "couldn't process that just now," log it; one user's error never takes the bot down |
| Network slower than the library's default timeouts | high / bad | PTB defaults to a **5s** read timeout, which a high-latency link misses on every photo download (`TimedOut` inside `get_file`). `build_application()` sets generous ceilings (30s read, 60s media write). Symptom to recognise: text works, photos never do |
| Updater dies but the **process stays alive** | medium / very bad | An unhandled error (classically `Conflict`) stops polling while the process lingers, so the bot looks healthy and simply never replies again. `add_error_handler` logs it loudly. Checking "is the process running?" is *not* a health check |
| Anything else calling `getUpdates` on the same token | medium / bad | Telegram terminates the *existing* long-poll, so even a one-off debug `getUpdates` kills a running poller. Never poll the API to "check" a live bot — read the log instead |
| No IANA timezone database (Windows dev) | high / bad | `ZoneInfo("UTC")` raises `ZoneInfoNotFoundError`; `run_due_sends` builds a `ZoneInfo` per user, so the whole morning job dies. Fixed by depending on **`tzdata`**, which Linux gets from the OS but Windows never has |
| Morning job: one user's send throws | medium / bad | Per-user try/except — log and continue to the next user. One bad profile must not stop the whole broadcast |
| Cron endpoint hit by a stranger | medium / bad | `POST /cron/daily` requires a secret token (header), else `401`. Same rule as any deployed headless endpoint |
| A stranger finds the bot and runs up the bill | medium / bad | Optional `ALLOWED_TELEGRAM_IDS` allowlist (authorization, separate from Telegram's authentication); unknown users get a polite "not enabled" reply. Open if unset (fine for local dev) |
| `/delete` fires by accident | medium / very bad | **Two-step confirm** (inline "Yes, delete everything / Cancel"). Only on explicit confirm do we remove items, their R2 images, and the user row |
| Profile drifts into nonsense over many updates | low / mild | Profile is regenerated from a bounded prompt each time (current profile + new item → concise rewrite), not blindly appended, so it can't grow unboundedly |
| User asks for a send time but we don't know their timezone | high / mild | The agent **asks** for a city/timezone instead of guessing; until set, `timezone` defaults to UTC. A wrong 7am is worse than one question |
| Cron tick runs twice (retry, overlap) → double send | medium / bad | `run_due_sends` is idempotent: it only sends if `last_sent_at` isn't already today, and stamps it on send |
| Agent sets an absurd schedule (hour 27, "Mars/Phobos") | low / mild | `set_schedule` validates: hour 0–23, a known IANA timezone, cadence in {daily, weekdays, weekly}; on bad input it tells the user, changes nothing |

## Hard rules

- **Never** run polling and webhook against the same token (the `409` above).
- **Never** delete a user's data without an explicit confirmation in the same conversation.
- **Never** let one user's error (a bad photo, a failed call) crash the bot or abort the morning job for others.
- **Always** scope every database query by `telegram_id` — one user must never see another's items.
- The `/cron/daily` endpoint **always** requires its secret token.

## What the user sees on failure

A short, human sentence in chat ("Hmm, I couldn't read that image — mind sending it again?"), never
a raw traceback. The morning job is silent to users on failure (it just logs and skips), so a broken
profile never produces a broken-looking message.
