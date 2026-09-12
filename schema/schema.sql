-- Inventory Machine: core schema (MVP)
--
-- This schema is domain-agnostic. It holds only the tables the base
-- pipeline needs: photo ingestion, AI tagging, embeddings, clustering,
-- and printed QR labels. It does not include any business-specific
-- tables (an item, an employee record, a lab member, and so on). The
-- three files in this directory each add one domain on top of this
-- core set.
--
-- Target: SQLite for development. The team switches to MariaDB later
-- by changing only the connection string in the data access layer, not
-- this file's table shape. Two syntax notes for that later port:
--   1. INTEGER PRIMARY KEY AUTOINCREMENT becomes
--      INTEGER PRIMARY KEY AUTO_INCREMENT.
--   2. datetime('now') becomes CURRENT_TIMESTAMP.
--
-- Table count: 11.

PRAGMA foreign_keys = ON;

-- A location is a physical place: a room, a shelf, a drawer, or a bin.
-- Locations nest through parent_location_id. A drawer can sit inside a
-- shelf, and a shelf can sit inside a room.
CREATE TABLE locations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    parent_location_id  INTEGER REFERENCES locations(id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- A cluster groups items the embedding step found similar. label comes
-- from a follow-up vision model call over the cluster's most central
-- items. Noise items (HDBSCAN label -1) keep items.cluster_id NULL.
CREATE TABLE clusters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row per cataloged item. id is a UUID the pipeline generates once,
-- at first processing time, so a QR code can point at a stable value
-- even before the row exists in every downstream table.
CREATE TABLE items (
    id                 TEXT PRIMARY KEY,
    location_id        INTEGER REFERENCES locations(id),
    cluster_id          INTEGER REFERENCES clusters(id),
    description         TEXT NOT NULL,
    confidence_score    REAL NOT NULL,
    confidence_flag     TEXT NOT NULL DEFAULT 'ok' CHECK (confidence_flag IN ('ok', 'low')),
    date_processed      TEXT NOT NULL
);

-- An item can have more than one photo. Each row is one source photo.
CREATE TABLE images (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id            TEXT NOT NULL REFERENCES items(id),
    file_path          TEXT NOT NULL,
    original_filename  TEXT NOT NULL,
    width_px           INTEGER,
    height_px          INTEGER,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- A tag is a single AI-generated keyword (for example "wooden",
-- "power tool"). Tags stay separate from the curated category tables a
-- domain schema may add, because a tag comes from the model, not from
-- a person choosing a taxonomy.
CREATE TABLE tags (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE
);

-- Many-to-many bridge between items and tags.
CREATE TABLE item_tags (
    item_id  TEXT NOT NULL REFERENCES items(id),
    tag_id   INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (item_id, tag_id)
);

-- The two signals that make up an item's confidence score, stored
-- apart from items so the pipeline can re-weight or audit them later
-- without rewriting the items table.
CREATE TABLE confidence_components (
    item_id               TEXT PRIMARY KEY REFERENCES items(id),
    self_report           REAL NOT NULL,
    tag_coherence         REAL NOT NULL,
    self_report_weight    REAL NOT NULL,
    tag_coherence_weight  REAL NOT NULL,
    computed_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

-- The embedding vector itself lives in ChromaDB, not in SQL. This
-- table stores only the pointer the pipeline needs to fetch a vector
-- back from Chroma: which collection, which record, which model.
CREATE TABLE embeddings_index (
    item_id            TEXT PRIMARY KEY REFERENCES items(id),
    chroma_collection  TEXT NOT NULL,
    chroma_record_id   TEXT NOT NULL,
    model_name         TEXT NOT NULL,
    dims               INTEGER NOT NULL,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Audit trail of every raw vision model call, including failed
-- attempts the pipeline retried. This keeps the raw AI output separate
-- from the validated, normalized fields the pipeline writes to items.
CREATE TABLE vision_model_outputs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         TEXT NOT NULL REFERENCES items(id),
    model_name      TEXT NOT NULL,
    attempt_number  INTEGER NOT NULL,
    raw_response    TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- A label is a printed sheet: a short text description plus a QR code.
-- Most labels point at a location, because one container holds many
-- items and the label marks the container, not a single item. A label
-- can instead point at a single item when that item has no container
-- of its own. Every row must point at exactly one of the two.
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

-- One row per pipeline run. This lets the team trace which config
-- produced which items, and replay a run's settings later.
CREATE TABLE processing_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    input_dir        TEXT NOT NULL,
    config_snapshot  TEXT NOT NULL,
    item_count       INTEGER NOT NULL DEFAULT 0,
    started_at       TEXT NOT NULL,
    finished_at      TEXT
);
