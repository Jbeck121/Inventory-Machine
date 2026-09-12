-- Inventory Machine: Option A, home organizer
--
-- This file is a full, standalone schema. It contains the 11 core
-- tables from schema.sql plus 13 tables for a household inventory:
-- a curated category tree, lending between household members,
-- condition and maintenance history, purchase and warranty records,
-- disposal tracking, value estimates, and insurance coverage.
--
-- Target: SQLite for development. See schema.sql's header for the
-- MariaDB port notes (AUTOINCREMENT, datetime('now')).
--
-- Table count: 24 (11 core + 13 domain).

PRAGMA foreign_keys = ON;

-- ===== Core tables (see schema.sql for full comments) =====

CREATE TABLE locations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    parent_location_id  INTEGER REFERENCES locations(id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE clusters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE items (
    id                TEXT PRIMARY KEY,
    location_id       INTEGER REFERENCES locations(id),
    cluster_id        INTEGER REFERENCES clusters(id),
    description       TEXT NOT NULL,
    confidence_score  REAL NOT NULL,
    confidence_flag   TEXT NOT NULL DEFAULT 'ok' CHECK (confidence_flag IN ('ok', 'low')),
    date_processed    TEXT NOT NULL
);

CREATE TABLE images (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id            TEXT NOT NULL REFERENCES items(id),
    file_path          TEXT NOT NULL,
    original_filename  TEXT NOT NULL,
    width_px           INTEGER,
    height_px          INTEGER,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE tags (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE
);

CREATE TABLE item_tags (
    item_id  TEXT NOT NULL REFERENCES items(id),
    tag_id   INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (item_id, tag_id)
);

CREATE TABLE confidence_components (
    item_id               TEXT PRIMARY KEY REFERENCES items(id),
    self_report           REAL NOT NULL,
    tag_coherence         REAL NOT NULL,
    self_report_weight    REAL NOT NULL,
    tag_coherence_weight  REAL NOT NULL,
    computed_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE embeddings_index (
    item_id            TEXT PRIMARY KEY REFERENCES items(id),
    chroma_collection  TEXT NOT NULL,
    chroma_record_id   TEXT NOT NULL,
    model_name         TEXT NOT NULL,
    dims               INTEGER NOT NULL,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE vision_model_outputs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         TEXT NOT NULL REFERENCES items(id),
    model_name      TEXT NOT NULL,
    attempt_number  INTEGER NOT NULL,
    raw_response    TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE qr_labels (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    location_id    INTEGER REFERENCES locations(id),
    item_id        TEXT REFERENCES items(id),
    label_text     TEXT NOT NULL,
    qr_url         TEXT NOT NULL,
    qr_image_path  TEXT NOT NULL,
    printed_at     TEXT,
    CHECK (
        (location_id IS NOT NULL AND item_id IS NULL)
        OR (location_id IS NULL AND item_id IS NOT NULL)
    )
);

CREATE TABLE processing_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    input_dir        TEXT NOT NULL,
    config_snapshot  TEXT NOT NULL,
    item_count       INTEGER NOT NULL DEFAULT 0,
    started_at       TEXT NOT NULL,
    finished_at      TEXT
);

-- ===== Domain tables: home organizer =====

-- A curated category tree (for example "Tools > Power Tools"), kept
-- apart from the AI-generated tags table. A person picks a category;
-- the vision model generates a tag.
CREATE TABLE categories (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    parent_category_id  INTEGER REFERENCES categories(id)
);

CREATE TABLE item_categories (
    item_id      TEXT NOT NULL REFERENCES items(id),
    category_id  INTEGER NOT NULL REFERENCES categories(id),
    PRIMARY KEY (item_id, category_id)
);

CREATE TABLE household_members (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name   TEXT NOT NULL,
    email  TEXT
);

-- Who currently has an item that left its usual container, and when
-- it is due back.
CREATE TABLE borrow_log (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id              TEXT NOT NULL REFERENCES items(id),
    household_member_id  INTEGER NOT NULL REFERENCES household_members(id),
    borrowed_at          TEXT NOT NULL,
    returned_at          TEXT
);

-- Actions taken on an item: cleaned, repaired, discarded, replaced.
CREATE TABLE maintenance_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     TEXT NOT NULL REFERENCES items(id),
    event_type  TEXT NOT NULL CHECK (event_type IN ('cleaned', 'repaired', 'discarded', 'replaced')),
    event_date  TEXT NOT NULL,
    notes       TEXT
);

-- Observed condition over time, separate from maintenance_log because
-- this tracks a state (worn, broken), not an action taken.
CREATE TABLE condition_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id      TEXT NOT NULL REFERENCES items(id),
    condition    TEXT NOT NULL CHECK (condition IN ('new', 'good', 'fair', 'poor', 'broken')),
    noted_at     TEXT NOT NULL,
    notes        TEXT
);

CREATE TABLE retailers (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,
    website  TEXT
);

-- Acquisition record: where an item came from, what it cost, and its
-- warranty window.
CREATE TABLE purchase_records (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id               TEXT NOT NULL REFERENCES items(id),
    retailer_id           INTEGER REFERENCES retailers(id),
    purchase_date         TEXT NOT NULL,
    price                 REAL NOT NULL,
    receipt_image_path    TEXT,
    warranty_expiration   TEXT
);

-- An item's value changes over time, so this is a series of
-- snapshots, not one fixed field on items.
CREATE TABLE item_value_estimates (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id          TEXT NOT NULL REFERENCES items(id),
    estimated_value  REAL NOT NULL,
    currency         TEXT NOT NULL DEFAULT 'USD',
    estimated_at     TEXT NOT NULL,
    source           TEXT NOT NULL CHECK (source IN ('purchase_price', 'appraisal', 'market_comparison'))
);

-- How an item permanently left the household: sold, donated, thrown
-- out, or recycled. Distinct from borrow_log, which is temporary.
CREATE TABLE disposal_records (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id      TEXT NOT NULL REFERENCES items(id),
    method       TEXT NOT NULL CHECK (method IN ('sold', 'donated', 'trashed', 'recycled')),
    disposed_at  TEXT NOT NULL,
    recipient    TEXT,
    notes        TEXT
);

CREATE TABLE insurance_policies (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    provider          TEXT NOT NULL,
    policy_number     TEXT NOT NULL UNIQUE,
    coverage_start    TEXT NOT NULL,
    coverage_end      TEXT
);

CREATE TABLE item_insurance (
    item_id     TEXT NOT NULL REFERENCES items(id),
    policy_id   INTEGER NOT NULL REFERENCES insurance_policies(id),
    PRIMARY KEY (item_id, policy_id)
);

-- A scheduled follow-up: a warranty about to expire, maintenance due,
-- a borrowed item overdue. due_at drives a simple reminder view across
-- otherwise unrelated tables.
CREATE TABLE reminders (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id        TEXT REFERENCES items(id),
    location_id    INTEGER REFERENCES locations(id),
    reminder_type  TEXT NOT NULL CHECK (reminder_type IN ('warranty_expiring', 'maintenance_due', 'borrow_overdue')),
    due_at         TEXT NOT NULL,
    completed_at   TEXT
);
