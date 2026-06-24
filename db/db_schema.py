"""
Database schema for the personal finance agent.

Maps directly onto the four memory layers from CLAUDE.md:
  1. Durable user facts  -> users, goals, budgets, prefs
  2. Financial history   -> accounts, transactions, split_snapshots
  3. Conversational mem   -> conversations, messages, conversation_summary
  4. Soft (learned) prefs -> learned_preferences
  + notification state    -> pending_notifications
  + CSV import            -> csv_mapping_profiles, import_batches
  + categorization HIL    -> category_proposals, merchant_category_overrides

SQLite for the demo (file-based, zero setup). The column shapes are what
matter; swap to Postgres later without touching the rest of the app.
Authoritative state lives HERE; the LLM context is assembled from these rows.
"""

from __future__ import annotations

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

-- CSV column mapping profiles (durable, user-editable)
CREATE TABLE IF NOT EXISTS csv_mapping_profiles (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    display_name    TEXT NOT NULL,
    column_map      TEXT NOT NULL,    -- JSON: lucid_field -> csv header name
    sign_rule       TEXT,             -- JSON: single_amount | debit_credit | etc.
    encoding        TEXT DEFAULT 'utf-8-sig',
    delimiter       TEXT DEFAULT ',',
    header_hash     TEXT,             -- sha256 of normalized header row for match
    is_default      INTEGER DEFAULT 0,
    -- ETL agent memory fields
    source_label    TEXT,             -- user-visible format name e.g. "Mastercard CH"
    confirmed       INTEGER DEFAULT 0, -- 1 = user explicitly confirmed this mapping
    use_count       INTEGER DEFAULT 0, -- number of successful imports using this profile
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_csv_profile_user ON csv_mapping_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_csv_profile_header ON csv_mapping_profiles(user_id, header_hash);

-- One row per import run / file
CREATE TABLE IF NOT EXISTS import_batches (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    source_path     TEXT NOT NULL,
    content_sha256  TEXT NOT NULL,
    mapping_profile_id TEXT REFERENCES csv_mapping_profiles(id),
    imported_at     TEXT NOT NULL,
    row_count       INTEGER NOT NULL DEFAULT 0,
    skipped_duplicate_count INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'completed'  -- completed|partial|rolled_back
);
CREATE INDEX IF NOT EXISTS idx_import_batches_user_path ON import_batches(user_id, source_path);

-- ── Layer 2: financial history (ledger) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS accounts (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    name            TEXT NOT NULL,
    balance         REAL NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'CHF',
    account_type    TEXT NOT NULL DEFAULT 'checking',  -- checking | credit_card | savings
    has_income      INTEGER NOT NULL DEFAULT 0          -- 1 = salary / regular income present
);

CREATE TABLE IF NOT EXISTS transactions (
    id              TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL REFERENCES accounts(id),
    amount          REAL NOT NULL,    -- negative = outflow
    currency        TEXT NOT NULL DEFAULT 'CHF',
    merchant        TEXT NOT NULL,
    clean_name      TEXT,             -- normalised merchant name set by Labeller agent
    category        TEXT,             -- raw: need|want|savings (legacy bucket)
    line_category   TEXT,             -- raw: rent|groceries|… (legacy fine label)
    normalized_category TEXT,         -- canonical taxonomy key, e.g. 'groceries_food'
    ts              TEXT NOT NULL,
    import_batch_id TEXT REFERENCES import_batches(id),
    external_fingerprint TEXT       -- dedupe key for CSV imports
);
CREATE INDEX IF NOT EXISTS idx_txn_account_ts ON transactions(account_id, ts);
CREATE UNIQUE INDEX IF NOT EXISTS idx_txn_fingerprint
    ON transactions(account_id, external_fingerprint)
    WHERE external_fingerprint IS NOT NULL;

-- Ledger categorization agent — proposals only until HIL commit
CREATE TABLE IF NOT EXISTS category_proposals (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    txn_id          TEXT NOT NULL REFERENCES transactions(id),
    proposed_bucket     TEXT,         -- raw: need|want|savings (legacy)
    proposed_line       TEXT,         -- raw: closed vocabulary line label (legacy)
    proposed_normalized TEXT,         -- canonical taxonomy key, e.g. 'restaurants'
    rationale       TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending|accepted|rejected
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cat_prop_user_status ON category_proposals(user_id, status);

CREATE TABLE IF NOT EXISTS merchant_category_overrides (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL REFERENCES users(id),
    merchant_normalized TEXT NOT NULL,  -- raw pattern matched against transaction merchant
    canonical_name      TEXT,           -- clean display name set by Labeller agent
    bucket              TEXT,           -- raw: need|want|savings (legacy)
    line_category       TEXT,           -- raw: fine label (legacy)
    normalized_category TEXT,           -- canonical taxonomy key, e.g. 'groceries_food'
    -- Labeller agent memory fields
    source              TEXT NOT NULL DEFAULT 'user_confirmed',
                        -- 'user_confirmed' | 'sector_rule' | 'llm_proposed'
    confidence          REAL NOT NULL DEFAULT 1.0,  -- 0.0–1.0; user_confirmed=1.0
    override_count      INTEGER NOT NULL DEFAULT 0, -- times user manually changed the suggestion
    updated_at          TEXT NOT NULL,
    UNIQUE(user_id, merchant_normalized)
);

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


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def migrate_schema(conn: sqlite3.Connection) -> None:
    """Apply additive migrations for DBs created before ingest / HIL tables."""
    # transactions columns added in the ingest phase
    cols = _table_columns(conn, "transactions")
    if "line_category" not in cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN line_category TEXT")
    if "import_batch_id" not in cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN import_batch_id TEXT")
    if "external_fingerprint" not in cols:
        conn.execute(
            "ALTER TABLE transactions ADD COLUMN external_fingerprint TEXT"
        )
    # Sub-plan 1: clean_name column for Labeller agent
    if "clean_name" not in cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN clean_name TEXT")
    # Normalized category taxonomy
    if "normalized_category" not in cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN normalized_category TEXT")

    # Partial unique index (may fail on very old SQLite — ignore if exists)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_txn_fingerprint "
        "ON transactions(account_id, external_fingerprint) "
        "WHERE external_fingerprint IS NOT NULL"
    )
    # csv_mapping_profiles columns added for category support (table may not
    # exist in very old DBs — the CREATE TABLE IF NOT EXISTS in SCHEMA covers it)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "csv_mapping_profiles" in tables:
        prof_cols = _table_columns(conn, "csv_mapping_profiles")
        if "category_col" not in prof_cols:
            conn.execute(
                "ALTER TABLE csv_mapping_profiles ADD COLUMN category_col TEXT"
            )
        # Sub-plan 1: ETL agent memory fields on csv_mapping_profiles
        if "source_label" not in prof_cols:
            conn.execute(
                "ALTER TABLE csv_mapping_profiles ADD COLUMN source_label TEXT"
            )
        if "confirmed" not in prof_cols:
            conn.execute(
                "ALTER TABLE csv_mapping_profiles "
                "ADD COLUMN confirmed INTEGER DEFAULT 0"
            )
        if "use_count" not in prof_cols:
            conn.execute(
                "ALTER TABLE csv_mapping_profiles "
                "ADD COLUMN use_count INTEGER DEFAULT 0"
            )
        if "skip_patterns" not in prof_cols:
            conn.execute(
                "ALTER TABLE csv_mapping_profiles ADD COLUMN skip_patterns TEXT"
            )

    # merchant_category_overrides: Sub-plan 1 Labeller agent memory fields
    if "merchant_category_overrides" in tables:
        mco_cols = _table_columns(conn, "merchant_category_overrides")
        if "canonical_name" not in mco_cols:
            conn.execute(
                "ALTER TABLE merchant_category_overrides "
                "ADD COLUMN canonical_name TEXT"
            )
        if "source" not in mco_cols:
            conn.execute(
                "ALTER TABLE merchant_category_overrides "
                "ADD COLUMN source TEXT NOT NULL DEFAULT 'user_confirmed'"
            )
        if "confidence" not in mco_cols:
            conn.execute(
                "ALTER TABLE merchant_category_overrides "
                "ADD COLUMN confidence REAL NOT NULL DEFAULT 1.0"
            )
        if "override_count" not in mco_cols:
            conn.execute(
                "ALTER TABLE merchant_category_overrides "
                "ADD COLUMN override_count INTEGER NOT NULL DEFAULT 0"
            )
        if "normalized_category" not in mco_cols:
            conn.execute(
                "ALTER TABLE merchant_category_overrides "
                "ADD COLUMN normalized_category TEXT"
            )

    # category_proposals: add proposed_normalized for taxonomy proposals
    if "category_proposals" in tables:
        prop_cols = _table_columns(conn, "category_proposals")
        if "proposed_normalized" not in prop_cols:
            conn.execute(
                "ALTER TABLE category_proposals ADD COLUMN proposed_normalized TEXT"
            )

    # accounts columns added for multi-account support
    acct_cols = _table_columns(conn, "accounts")
    if "account_type" not in acct_cols:
        conn.execute(
            "ALTER TABLE accounts ADD COLUMN "
            "account_type TEXT NOT NULL DEFAULT 'checking'"
        )
    if "has_income" not in acct_cols:
        conn.execute(
            "ALTER TABLE accounts ADD COLUMN "
            "has_income INTEGER NOT NULL DEFAULT 0"
        )


def init_db(path: str = "finance_agent.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    migrate_schema(conn)
    conn.commit()
    return conn


if __name__ == "__main__":
    init_db()
    print("Schema created: finance_agent.db")
