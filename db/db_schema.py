"""
Database schema for the personal finance agent.

Maps directly onto the four memory layers from CLAUDE.md:
  1. Durable user facts  -> users, goals, budgets, prefs
  2. Financial history   -> accounts, transactions, split_snapshots
  3. Conversational mem   -> conversations, messages, conversation_summary
  4. Soft (learned) prefs -> learned_preferences
  + notification state    -> pending_notifications

SQLite for the demo (file-based, zero setup). The column shapes are what
matter; swap to Postgres later without touching the rest of the app.
Authoritative state lives HERE; the LLM context is assembled from these rows.
"""

import sqlite3

SCHEMA = """
-- ── Layer 1: durable user facts ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    display_name    TEXT,
    telegram_chat_id TEXT,            -- where to push notifications
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS goals (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    goal_type       TEXT NOT NULL,    -- 'open' | 'target'
    amount          REAL,             -- null for open goals
    target_date     TEXT,             -- null for open goals
    engagement      TEXT NOT NULL,    -- 'low' | 'high'  (routes framework)
    framework       TEXT,             -- '50_30_20' | 'zero_based' | 'pay_first'
    active          INTEGER DEFAULT 1,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS budgets (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    -- category allocations as JSON: {"groceries": 600, "dining": 200, ...}
    allocations     TEXT NOT NULL,
    -- ratios actually targeted, JSON: {"needs":0.55,"wants":0.25,"savings":0.20}
    target_ratios   TEXT NOT NULL,
    period          TEXT NOT NULL,    -- e.g. '2026-06' (monthly)
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prefs (
    user_id         TEXT PRIMARY KEY REFERENCES users(id),
    quiet_hours     TEXT,             -- JSON {"start":"22:00","end":"07:00"}
    max_pushes_day  INTEGER DEFAULT 3,
    digest_time     TEXT DEFAULT '08:00',
    persona         TEXT DEFAULT 'neutral'  -- 'neutral' | 'coach'
);

-- ── Layer 2: financial history (ledger) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS accounts (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    name            TEXT NOT NULL,
    balance         REAL NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'CHF'
);

CREATE TABLE IF NOT EXISTS transactions (
    id              TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL REFERENCES accounts(id),
    amount          REAL NOT NULL,    -- negative = outflow
    currency        TEXT NOT NULL DEFAULT 'CHF',
    merchant        TEXT NOT NULL,
    category        TEXT,             -- need|want|savings, set by categorizer
    ts              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_txn_account_ts ON transactions(account_id, ts);

-- periodic snapshots so the dashboard can chart progress over time
CREATE TABLE IF NOT EXISTS split_snapshots (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    period          TEXT NOT NULL,    -- '2026-06'
    needs_pct       REAL NOT NULL,
    wants_pct       REAL NOT NULL,
    savings_pct     REAL NOT NULL,
    goal_progress   REAL,             -- 0..1 toward target, null for open goals
    taken_at        TEXT NOT NULL
);

-- ── Layer 3: conversational memory ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    started_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role            TEXT NOT NULL,    -- 'user' | 'assistant' | 'tool'
    content         TEXT NOT NULL,
    ts              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_conv_ts ON messages(conversation_id, ts);

-- one running compressed summary per user (older turns folded in)
CREATE TABLE IF NOT EXISTS conversation_summary (
    user_id         TEXT PRIMARY KEY REFERENCES users(id),
    summary         TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- ── Layer 4: agent-learned (soft) preferences ──────────────────────────────
-- Structured & reviewable; NOT free text the LLM rewrites at will.
CREATE TABLE IF NOT EXISTS learned_preferences (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    kind            TEXT NOT NULL,    -- e.g. 'suppress_alert'
    subject         TEXT NOT NULL,    -- e.g. 'dining_80pct'
    value           TEXT NOT NULL,    -- e.g. 'true'
    -- safety alerts (breach, goal-risk) are NEVER suppressible regardless
    suppressible    INTEGER DEFAULT 1,
    evidence_count  INTEGER DEFAULT 1,  -- how many times observed
    updated_at      TEXT NOT NULL
);

-- ── Notification state (minimal carried context for replies) ────────────────
CREATE TABLE IF NOT EXISTS pending_notifications (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    tier            TEXT NOT NULL,    -- 'actionable' (only these need replies)
    summary         TEXT NOT NULL,    -- "offered buffer-pull CHF 30"
    offered_actions TEXT NOT NULL,    -- JSON of the buttons presented
    status          TEXT NOT NULL DEFAULT 'awaiting',  -- awaiting|resolved|expired
    created_at      TEXT NOT NULL,
    resolved_at     TEXT
);
"""


def init_db(path: str = "finance_agent.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


if __name__ == "__main__":
    init_db()
    print("Schema created: finance_agent.db")
