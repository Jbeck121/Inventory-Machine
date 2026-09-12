-- Inventory Machine: Option C, FSU Spark Labs
--
-- This file is a full, standalone schema. It contains the 11 core
-- tables from schema.sql plus 19 tables for a university research and
-- makerspace lab. Spark Labs' actual equipment mix drove this design:
-- 3D printers and print supplies, servers, an arcade cabinet,
-- soldering and other hand-tool hardware, drones, radio systems, and
-- an active photolithography research effort.
--
-- Target: SQLite for development. See schema.sql's header for the
-- MariaDB port notes (AUTOINCREMENT, datetime('now')).
--
-- Table count: 30 (11 core + 19 domain).

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

-- Catalog of equipment kinds the lab owns (for example "3D Printer",
-- "Server", "Arcade Cabinet", "Soldering Station", "Drone", "Radio
-- Transceiver", "Photolithography Mask Aligner"). Individual items
-- link back to one equipment_type.
CREATE TABLE equipment_types (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    description  TEXT
);

CREATE TABLE items (
    id                 TEXT PRIMARY KEY,
    location_id        INTEGER REFERENCES locations(id),
    cluster_id         INTEGER REFERENCES clusters(id),
    equipment_type_id  INTEGER REFERENCES equipment_types(id),
    description        TEXT NOT NULL,
    confidence_score   REAL NOT NULL,
    confidence_flag    TEXT NOT NULL DEFAULT 'ok' CHECK (confidence_flag IN ('ok', 'low')),
    date_processed     TEXT NOT NULL
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

-- ===== Domain tables: Spark Labs =====

CREATE TABLE lab_members (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL,
    fsu_id  TEXT NOT NULL UNIQUE,
    email   TEXT NOT NULL,
    role    TEXT NOT NULL CHECK (role IN ('student', 'staff', 'faculty'))
);

-- A safety or skill certification, often tied to one equipment type
-- (for example "Laser Cutter Safety", "Solder Fume Safety", "FAA Part
-- 107 Small UAS", "RF Safety and FCC Rules").
CREATE TABLE certifications (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT NOT NULL,
    description        TEXT,
    equipment_type_id  INTEGER REFERENCES equipment_types(id)
);

CREATE TABLE training_sessions (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    certification_id          INTEGER NOT NULL REFERENCES certifications(id),
    held_at                   TEXT NOT NULL,
    instructor_lab_member_id  INTEGER NOT NULL REFERENCES lab_members(id),
    capacity                  INTEGER
);

CREATE TABLE training_attendance (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    training_session_id   INTEGER NOT NULL REFERENCES training_sessions(id),
    lab_member_id         INTEGER NOT NULL REFERENCES lab_members(id),
    attended              INTEGER NOT NULL DEFAULT 0 CHECK (attended IN (0, 1)),
    passed                INTEGER NOT NULL DEFAULT 0 CHECK (passed IN (0, 1))
);

-- A member's earned certification, traced back to the session that
-- granted it.
CREATE TABLE member_certifications (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    lab_member_id          INTEGER NOT NULL REFERENCES lab_members(id),
    certification_id       INTEGER NOT NULL REFERENCES certifications(id),
    training_attendance_id INTEGER REFERENCES training_attendance(id),
    certified_at           TEXT NOT NULL,
    expires_at             TEXT
);

CREATE TABLE projects (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    name                  TEXT NOT NULL,
    description           TEXT,
    lead_lab_member_id    INTEGER REFERENCES lab_members(id),
    started_at            TEXT NOT NULL,
    ended_at              TEXT,
    status                TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'paused'))
);

CREATE TABLE project_members (
    project_id     INTEGER NOT NULL REFERENCES projects(id),
    lab_member_id  INTEGER NOT NULL REFERENCES lab_members(id),
    role           TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('lead', 'member', 'collaborator')),
    PRIMARY KEY (project_id, lab_member_id)
);

-- A booking ahead of use, for equipment in high demand (the laser
-- cutter, the mask aligner).
CREATE TABLE reservations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id        TEXT NOT NULL REFERENCES items(id),
    lab_member_id  INTEGER NOT NULL REFERENCES lab_members(id),
    start_time     TEXT NOT NULL,
    end_time       TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'requested' CHECK (status IN ('requested', 'approved', 'denied', 'completed'))
);

-- The actual physical checkout. reservation_id is nullable because a
-- member can walk up and check out equipment with no prior booking.
CREATE TABLE checkouts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    reservation_id  INTEGER REFERENCES reservations(id),
    item_id         TEXT NOT NULL REFERENCES items(id),
    lab_member_id   INTEGER NOT NULL REFERENCES lab_members(id),
    checked_out_at  TEXT NOT NULL,
    due_at          TEXT,
    returned_at     TEXT
);

-- Consumables (filament, resin, solder, PCB stock, mask blanks) are
-- tracked by quantity on hand, not as one-off tagged items the way
-- durable equipment is.
CREATE TABLE consumables (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT NOT NULL,
    unit               TEXT NOT NULL,
    reorder_threshold  REAL NOT NULL DEFAULT 0
);

CREATE TABLE consumable_stock (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    consumable_id     INTEGER NOT NULL REFERENCES consumables(id),
    location_id       INTEGER NOT NULL REFERENCES locations(id),
    quantity_on_hand  REAL NOT NULL DEFAULT 0,
    last_counted_at   TEXT
);

CREATE TABLE consumable_usage_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    consumable_id  INTEGER NOT NULL REFERENCES consumables(id),
    lab_member_id  INTEGER NOT NULL REFERENCES lab_members(id),
    item_id        TEXT REFERENCES items(id),
    quantity_used  REAL NOT NULL,
    used_at        TEXT NOT NULL
);

CREATE TABLE maintenance_requests (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id        TEXT NOT NULL REFERENCES items(id),
    lab_member_id  INTEGER NOT NULL REFERENCES lab_members(id),
    status         TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'closed')),
    opened_at      TEXT NOT NULL,
    closed_at      TEXT,
    notes          TEXT
);

-- A safety incident: a burn from a soldering iron, a drone crash, a
-- lab chemical exposure during photolithography. Distinct from
-- maintenance_requests, which covers equipment condition, not injury
-- or hazard events.
CREATE TABLE incident_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id       INTEGER REFERENCES items(id),
    location_id   INTEGER REFERENCES locations(id),
    reported_by   INTEGER NOT NULL REFERENCES lab_members(id),
    severity      TEXT NOT NULL CHECK (severity IN ('minor', 'moderate', 'severe')),
    occurred_at   TEXT NOT NULL,
    description   TEXT NOT NULL,
    resolved_at   TEXT
);

-- One research process run on a piece of equipment (a photolithography
-- exposure, a spin-coat cycle, a print job with logged parameters).
-- Ties equipment use back to the project it supports.
CREATE TABLE experiment_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id       INTEGER NOT NULL REFERENCES projects(id),
    item_id          TEXT NOT NULL REFERENCES items(id),
    lab_member_id    INTEGER NOT NULL REFERENCES lab_members(id),
    run_at           TEXT NOT NULL,
    parameters_json  TEXT,
    outcome_notes    TEXT
);

-- Extension table for the subset of items that are servers. This is a
-- supertype/subtype split: every server is an item, but only servers
-- carry network fields.
CREATE TABLE server_assets (
    item_id           TEXT PRIMARY KEY REFERENCES items(id),
    hostname          TEXT NOT NULL UNIQUE,
    ip_address        TEXT NOT NULL,
    operating_system  TEXT NOT NULL,
    rack_location_id  INTEGER REFERENCES locations(id),
    role              TEXT
);

-- FAA Part 107 requires a logged flight record per drone flight.
CREATE TABLE drone_flight_logs (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id                  TEXT NOT NULL REFERENCES items(id),
    pilot_lab_member_id      INTEGER NOT NULL REFERENCES lab_members(id),
    flown_at                 TEXT NOT NULL,
    duration_minutes         INTEGER NOT NULL,
    faa_registration_number  TEXT NOT NULL,
    location_id              INTEGER REFERENCES locations(id),
    notes                    TEXT
);

-- FCC amateur radio licenses are held by a person, not by a piece of
-- equipment, so this ties to lab_members rather than to items.
CREATE TABLE radio_licenses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    lab_member_id  INTEGER NOT NULL REFERENCES lab_members(id),
    callsign       TEXT NOT NULL UNIQUE,
    license_class  TEXT NOT NULL CHECK (license_class IN ('technician', 'general', 'extra')),
    issued_at      TEXT NOT NULL,
    expires_at     TEXT
);
