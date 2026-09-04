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
