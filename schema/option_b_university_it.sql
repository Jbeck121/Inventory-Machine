-- Inventory Machine: Option B, university IT asset management
--
-- This file is a full, standalone schema. It contains the 11 core
-- tables from schema.sql plus 17 tables for a university IT
-- department: the group that issues laptops, runs computer labs and
-- classroom AV gear, and fields support tickets from faculty, staff,
-- and students across campus.
--
-- Target: SQLite for development. See schema.sql's header for the
-- MariaDB port notes (AUTOINCREMENT, datetime('now')).
--
-- Table count: 28 (11 core + 17 domain).

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

-- Catalog of make and model, kept apart from a serialized unit. Ten
-- identical lab workstations share one asset_models row and get ten
-- separate items rows, one per serial-tagged machine.
CREATE TABLE asset_models (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer  TEXT NOT NULL,
    model_name    TEXT NOT NULL,
    asset_type    TEXT NOT NULL CHECK (asset_type IN (
                      'laptop', 'desktop', 'monitor', 'printer', 'projector',
                      'network_switch', 'server', 'tablet', 'other'
                  )),
    specs_json    TEXT
);

-- One row per cataloged, serial-tagged asset. asset_model_id links the
-- specific unit back to its catalog entry.
CREATE TABLE items (
    id                TEXT PRIMARY KEY,
    location_id       INTEGER REFERENCES locations(id),
    cluster_id        INTEGER REFERENCES clusters(id),
    asset_model_id    INTEGER REFERENCES asset_models(id),
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

-- ===== Domain tables: university IT =====

-- Academic and administrative units on campus (for example "Computer
-- Science", "Registrar", "Housing"). employees and cost_centers both
-- belong to a department.
CREATE TABLE departments (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE
);

-- IT staff: technicians, administrators, help desk agents. Distinct
-- from patrons, who request support but do not manage assets.
CREATE TABLE employees (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    email          TEXT NOT NULL UNIQUE,
    department_id  INTEGER REFERENCES departments(id),
    job_title      TEXT
);

-- Faculty, staff, and students who request IT support or receive a
-- checked-out asset. patron_type distinguishes a student, who is not
-- a university employee, from faculty or staff, who may be.
CREATE TABLE patrons (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    fsu_id       TEXT NOT NULL UNIQUE,
    email        TEXT NOT NULL,
    patron_type  TEXT NOT NULL CHECK (patron_type IN ('student', 'faculty', 'staff'))
);

-- A university funding source: state appropriation, grant, or
-- auxiliary account. Purchase orders and software licenses charge
-- against one, so a department can report its own IT spend.
CREATE TABLE cost_centers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    code           TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    fund_source    TEXT NOT NULL CHECK (fund_source IN ('state', 'grant', 'auxiliary', 'other')),
    department_id  INTEGER REFERENCES departments(id)
);

CREATE TABLE vendors (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    contact_email  TEXT,
    phone          TEXT
);

CREATE TABLE purchase_orders (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id      INTEGER NOT NULL REFERENCES vendors(id),
    cost_center_id INTEGER NOT NULL REFERENCES cost_centers(id),
    order_date     TEXT NOT NULL,
    total_cost     REAL NOT NULL,
    status         TEXT NOT NULL DEFAULT 'ordered' CHECK (status IN ('ordered', 'received', 'canceled'))
);

-- A purchase order lists a catalog model and a quantity, not a
-- specific serialized unit. The unit gets its own items row once it
-- arrives and the pipeline tags it.
CREATE TABLE purchase_order_lines (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id),
    asset_model_id    INTEGER NOT NULL REFERENCES asset_models(id),
    quantity          INTEGER NOT NULL,
    unit_cost         REAL NOT NULL
);

CREATE TABLE warranties (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id           TEXT NOT NULL REFERENCES items(id),
    provider          TEXT NOT NULL,
    start_date        TEXT NOT NULL,
    end_date          TEXT NOT NULL,
    terms             TEXT
);

CREATE TABLE software_licenses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name    TEXT NOT NULL,
    vendor_id       INTEGER REFERENCES vendors(id),
    cost_center_id  INTEGER REFERENCES cost_centers(id),
    seats_total     INTEGER NOT NULL,
    expires_at      TEXT
);

-- Which machine has which license installed. A seat can move from one
-- item to another over time, so this is a log, not a fixed pairing.
CREATE TABLE license_assignments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    license_id   INTEGER NOT NULL REFERENCES software_licenses(id),
    item_id      TEXT NOT NULL REFERENCES items(id),
    assigned_at  TEXT NOT NULL,
    revoked_at   TEXT
);

-- Which patron currently holds a checked-out asset, such as a loaner
-- laptop.
CREATE TABLE asset_assignments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id      TEXT NOT NULL REFERENCES items(id),
    patron_id    INTEGER NOT NULL REFERENCES patrons(id),
    assigned_at  TEXT NOT NULL,
    returned_at  TEXT
);

CREATE TABLE ticket_categories (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE
);

-- item_id is nullable because a ticket is not always about one
-- tracked asset (for example, an account access request).
CREATE TABLE service_tickets (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id              TEXT REFERENCES items(id),
    requester_patron_id  INTEGER NOT NULL REFERENCES patrons(id),
    assigned_employee_id INTEGER REFERENCES employees(id),
    category_id          INTEGER NOT NULL REFERENCES ticket_categories(id),
    priority             TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    status               TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'closed')),
    opened_at            TEXT NOT NULL,
    closed_at            TEXT,
    description          TEXT NOT NULL
);

CREATE TABLE ticket_comments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id    INTEGER NOT NULL REFERENCES service_tickets(id),
    employee_id  INTEGER NOT NULL REFERENCES employees(id),
    body         TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE maintenance_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id      TEXT NOT NULL REFERENCES items(id),
    employee_id  INTEGER REFERENCES employees(id),
    service_date TEXT NOT NULL,
    notes        TEXT,
    cost         REAL
);

CREATE TABLE depreciation_schedules (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id           TEXT NOT NULL REFERENCES items(id),
    method            TEXT NOT NULL CHECK (method IN ('straight_line', 'declining_balance')),
    useful_life_months INTEGER NOT NULL,
    salvage_value     REAL NOT NULL DEFAULT 0,
    start_date        TEXT NOT NULL
);
