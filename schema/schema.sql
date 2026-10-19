-- Inventory Machine: core schema (MVP)
--
-- This schema does not depend on a domain. It holds only the 11 tables
-- the base pipeline needs for photo ingestion, AI tagging, embeddings,
-- clustering, and printed QR labels. It has no business-specific tables
-- for items, employees, lab members, or other domain records.
-- Each of the three other files adds one domain to this core set.
--
-- Target: SQLite for development. The team later switches to MariaDB
-- by changing only the connection string in the data access layer.
-- The table shape stays the same. The later port needs two syntax changes:
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

-- A cluster groups items that the embedding step found similar.
-- A later vision model call labels the cluster from its most central items.
-- Noise items (HDBSCAN label -1) keep items.cluster_id NULL.
CREATE TABLE clusters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Each row holds one cataloged item. The pipeline generates id as a UUID
-- once, when it first processes the item. A QR code can use this stable
-- value before the row exists in every downstream table.
CREATE TABLE items (
    id                 VARCHAR(36) PRIMARY KEY,
    location_id        INTEGER REFERENCES locations(id),
    cluster_id          INTEGER REFERENCES clusters(id),
    description         TEXT NOT NULL,
    confidence_score    REAL NOT NULL,
    confidence_flag     TEXT NOT NULL DEFAULT 'ok' CHECK (confidence_flag IN ('ok', 'low')),
    date_processed      TEXT NOT NULL
);

-- An item can have more than one photo. Each row holds one source photo.
-- The optional date_taken/gps_lat/gps_lon fields use the photo's EXIF data
-- when present. They stay NULL when the source has no such data.
-- These fields show where and when someone captured the photo.
-- The locations table shows the physical storage place.
CREATE TABLE images (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id            VARCHAR(36) NOT NULL REFERENCES items(id),
    file_path          TEXT NOT NULL,
    original_filename  TEXT NOT NULL,
    width_px           INTEGER,
    height_px          INTEGER,
    date_taken         TEXT,
    gps_lat            REAL,
    gps_lon            REAL,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- A tag is one AI-generated keyword (for example "wooden" or
-- "power tool"). Tags stay separate from curated category tables that
-- a domain schema can add. The model generates tags.
-- A person selects categories from a taxonomy.
CREATE TABLE tags (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  VARCHAR(255) NOT NULL UNIQUE
);

-- Many-to-many bridge between items and tags.
CREATE TABLE item_tags (
    item_id  VARCHAR(36) NOT NULL REFERENCES items(id),
    tag_id   INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (item_id, tag_id)
);

-- The two signals for an item's confidence score stay separate from items.
-- The pipeline can change their weights or audit them later without
-- changing the items table.
CREATE TABLE confidence_components (
    item_id               VARCHAR(36) PRIMARY KEY REFERENCES items(id),
    self_report           REAL NOT NULL,
    tag_coherence         REAL NOT NULL,
    self_report_weight    REAL NOT NULL,
    tag_coherence_weight  REAL NOT NULL,
    computed_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

-- The embedding vector lives in ChromaDB, not in SQL. This table stores
-- only the pointer that the pipeline needs to get the vector from Chroma.
-- The pointer records the collection, record, and model.
CREATE TABLE embeddings_index (
    item_id            VARCHAR(36) PRIMARY KEY REFERENCES items(id),
    chroma_collection  TEXT NOT NULL,
    chroma_record_id   TEXT NOT NULL,
    model_name         TEXT NOT NULL,
    dims               INTEGER NOT NULL,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- This table records every raw vision model call, including failed
-- attempts that the pipeline retried. It keeps raw AI output separate
-- from the checked, normalized fields that the pipeline writes to items.
CREATE TABLE vision_model_outputs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         VARCHAR(36) NOT NULL REFERENCES items(id),
    model_name      TEXT NOT NULL,
    attempt_number  INTEGER NOT NULL,
    raw_response    TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- A label is a printed sheet with a short text description and a QR code.
-- Most labels point to a location because one container holds many items.
-- The label marks the container, not one item.
-- A label can point to an item when that item has no container of its own.
-- Each row must point to exactly one location or one item.
CREATE TABLE qr_labels (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    location_id    INTEGER REFERENCES locations(id),
    item_id        VARCHAR(36) REFERENCES items(id),
    label_text     TEXT NOT NULL,
    qr_url         TEXT NOT NULL,
    qr_image_path  TEXT NOT NULL,
    printed_at     TEXT,
    CHECK (
        (location_id IS NOT NULL AND item_id IS NULL)
        OR (location_id IS NULL AND item_id IS NOT NULL)
    )
);

-- Each row holds one pipeline run. The team can trace which config
-- produced which items and later reuse a run's settings.
CREATE TABLE processing_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    input_dir        TEXT NOT NULL,
    config_snapshot  TEXT NOT NULL,
    item_count       INTEGER NOT NULL DEFAULT 0,
    started_at       TEXT NOT NULL,
    finished_at      TEXT
);
