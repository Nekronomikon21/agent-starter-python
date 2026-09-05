# Deploying (Railway)

**Stage 8 — ship it.** We deploy with [Railway](https://docs.railway.com/) using its
**CLI** (no GitHub needed). Railway is the simplest reliable host for always-on apps and
bots: the Hobby plan (~$5/mo, includes some usage) **never sleeps**, so your Telegram bot
or web app stays up.

The project ships with a `Dockerfile`, so Railway builds the same container we run locally.

## One-time setup

```bash
brew install railway      # macOS. Other OSes: see https://docs.railway.com/
railway login             # opens your browser
```

## Deploy in 5 steps

```bash
# 1. Create a project (run this in your project folder)
railway init --name my-agent

# 2. Build + deploy the Dockerfile. If it says "multiple services / specify a service",
#    link the directory once with `railway service` (pick it), or add `--service my-agent`.
railway up

# 3. Set your secrets as Railway variables (NEVER commit .env — it's gitignored AND
#    dockerignored, so it's never in the image). Set every variable your app needs:
railway variables \
  --set "OPENROUTER_API_KEY=sk-or-..." \
  --set "APP_PASSWORD=pick-a-password" \
  --set "FAL_KEY=..." \
  --set "DATABASE_URL=postgresql://..."
  # ...and any R2_* you use

# 4. Give it a public URL
railway domain

# 5. Open it
railway open
```

## What gets deployed

The `Dockerfile` builds your project with `uv` and, by default, runs `src/agent/web.py`.
To deploy a **different entrypoint** (an example, a Telegram bot, a worker), add a
`railway.toml` at the repo root:

```toml
[deploy]
startCommand = "fastapi run path/to/app.py"   # a web app
# startCommand = "python -m agent.bot"          # a long-running bot/worker
```

(This repo's `railway.toml` is set to run the `examples/agent_idea_web` demo — change it to
your own app, or delete it to use the Dockerfile default.)

## This project (mathcheck): what deploying it actually needs

`src/agent/mathcheck/app.py` is the production entrypoint —
`startCommand = "fastapi run src/agent/mathcheck/app.py"`. No cron: nothing here is scheduled.

Variables: `ENVIRONMENT=production`, a **prod** `TELEGRAM_BOT_TOKEN`, `DATABASE_URL`,
`OPENROUTER_API_KEY`, `TELEGRAM_WEBHOOK_SECRET`, `ALLOWED_TELEGRAM_IDS`, then `PUBLIC_URL` once
`railway domain` has given you one. No `FAL_KEY` and no `R2_*` — this project uses neither.

Three things specific to this bot:

- **`ALLOWED_TELEGRAM_IDS` must not be empty in production.** Every photo is a page read, a solve
  per row and an Opus review, all on your key. The allowlist is the only thing between a stranger
  and the bill; the bot logs a warning at startup if it's open.
- **Updates are queued, not awaited.** Checking a page takes ~40s. Holding Telegram's connection
  that long gets the update re-delivered on timeout — two answers, two bills — so the webhook puts
  it on PTB's queue and returns immediately. That also preserves `MAX_CONCURRENT_PAGES`.
- **`post_init` runs the migrations, and FastAPI must call it by hand.** `Application.initialize()`
  does *not* run it — only `run_polling`/`run_webhook` do (PTB's own docstring says so). `app.py`
  calls it explicitly; drop that line and the table never exists in production.

## Deploying a Telegram bot (webhook + cron + environments)

Worked example: `examples/inspiration_bot`. Locally a bot uses **long polling** (no public
URL). In production it switches to a **webhook** into a FastAPI app, plus a **cron** for
scheduled work. The switch is driven entirely by config — the *idea of environments*:

> **Use a different bot token (and database) for dev vs prod.** Telegram allows only one
> update-consumer per token, so your local poller and your deployed webhook **cannot** share
> a token (you'd get `409 Conflict`). Make two bots with @BotFather. A separate database also
> keeps test data and dev migrations away from real users.

1. **Make a production bot** with @BotFather (a second, different token).
2. **Set the start command** (in `railway.toml`):
   ```toml
   [deploy]
   startCommand = "fastapi run examples/inspiration_bot/app.py"
   ```
3. **Set production variables** (note `ENVIRONMENT=production`, and a *prod* token/DB):
   ```bash
   railway variables \
     --set "ENVIRONMENT=production" \
     --set "TELEGRAM_BOT_TOKEN=<prod-bot-token>" \
     --set "DATABASE_URL=postgresql://...<prod-db>" \
     --set "OPENROUTER_API_KEY=sk-or-..." \
     --set "FAL_KEY=..." \
     --set "TELEGRAM_WEBHOOK_SECRET=$(openssl rand -hex 16)" \
     --set "CRON_SECRET=$(openssl rand -hex 16)"
     # ...and your R2_* variables
   ```
4. **Give it a domain and tell the app its URL** (the app registers the webhook on boot):
   ```bash
   railway domain                                   # e.g. https://my-bot.up.railway.app
   railway variables --set "PUBLIC_URL=https://my-bot.up.railway.app"
   ```
   On the next boot you'll see `webhook registered at ...` in `railway logs`. Message your
   prod bot to confirm.
5. **Schedule the daily nudge** — pick one:
   - **Railway Cron service (simplest):** add a *second* service from the same repo, with the
     same variables, a start command of `python -m examples.inspiration_bot.cron`, and a
     **cron schedule** of `0 * * * *` (hourly). Because `ENVIRONMENT=production`, it honours
     each user's own hour/timezone/cadence and only messages those who are due. (Sending
     messages uses the Bot API, *not* `getUpdates`, so it never conflicts with the webhook.)
   - **Any HTTP scheduler:** have it `POST https://my-bot.up.railway.app/cron/tick` hourly
     with header `X-Cron-Secret: <CRON_SECRET>`. Same logic, via the protected endpoint.

To trigger a tick by hand (prod or local), `curl` the endpoint:
```bash
curl -X POST -H "X-Cron-Secret: <CRON_SECRET>" https://my-bot.up.railway.app/cron/tick
```

## Gotchas (learned the hard way — these are real)

- **Do NOT put `$PORT` in your start command.** Railway runs the start command *without a
  shell*, so `$PORT` is passed literally and the app fails with
  `'$PORT' is not a valid integer`. `fastapi run` already reads the `PORT` env var Railway
  injects and binds `0.0.0.0`, so just write `fastapi run app.py` — no `--port`, no `--host`.
- **Secrets are Railway variables, not your `.env`.** The `.env` file never reaches the
  image (gitignored + dockerignored). Set each value with `railway variables --set`. These
  are **readable** by anyone with access to your project (dashboard / CLI) — fine for a solo
  project with throwaway keys, and handy if you ever need to recover them. For genuinely
  sensitive or shared credentials, Railway has **Sealed Variables** (write-only: used at
  runtime but never readable again — so you can't recover those either).
- **Protect anything you expose publicly.**
  - A **web UI** → set `APP_PASSWORD` so it's behind a login (see `examples/agent_idea_web`,
    Pattern C). Otherwise it's open to the world and your API bill.
  - A **headless app with an HTTP endpoint** (e.g. a webhook receiver) → require a **secret
    token** on every request (a shared key in the URL or a header you check). Never deploy an
    open, unauthenticated endpoint.
  - A **bot with no inbound HTTP** (a polling Telegram bot) is already protected by its
    platform token — just keep that token secret.
- **Bots don't need a domain.** Only run `railway domain` for things that serve HTTP. A
  polling bot just needs to be running — skip the domain.
- **Database & migrations:** your app reaches out to Neon over the network; migrations run
  on startup (the demo calls `db.apply_migrations` in its lifespan). Nothing extra to do.

## Day-to-day

```bash
railway up                         # redeploy after code changes
railway variables --set "K=V"      # change a variable (triggers a redeploy)
railway logs                       # build/deploy/runtime logs (your first debugging stop)
railway status                     # project, environment, service, URL
railway open                       # open the dashboard
```

## Cost

Hobby plan is ~$5/mo and includes some usage; small apps/bots fit inside the included
credit. It never sleeps, which is the whole point for an always-on agent.
