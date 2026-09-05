-- Maths-homework checker — conversation state that survives a restart.
--
-- Tables are prefixed `mathcheck_` so they don't collide with other projects
-- sharing this database (the shared-database convention in CLAUDE.md).
--
-- ONE ROW PER USER, not one per problem. `architecture.md` originally specified a
-- normalised `mathcheck_problems` table, described as "the shared work queue both
-- workers read and write" — but that queue never came to exist. `pipeline.py`
-- races the fast solve against the slow review in memory, inside a single
-- request, and never touches a database. What actually needs persisting is much
-- narrower: the last page a user sent, so the correction button still works after
-- a restart. That is exactly one row per user.
--
-- The rows are JSONB rather than columns because they are read and written whole,
-- never queried by field. A column per `Row` attribute would buy nothing and cost
-- a migration every time the pipeline grows a status.
CREATE TABLE IF NOT EXISTS mathcheck_sessions (
    telegram_id   BIGINT      PRIMARY KEY,           -- Telegram's verified id (our identity)
    photo_file_id TEXT        NOT NULL,              -- re-downloaded on demand; we store no bytes
    media_type    TEXT        NOT NULL DEFAULT 'image/jpeg',
    awaiting      TEXT,                              -- label we asked about, NULL when we didn't
    rows          JSONB       NOT NULL,              -- the settled Rows, as `store._dump_row`
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
