-- Inventory Machine: Option B, university IT asset management
--
-- This full, standalone schema contains the 11 core tables from schema.sql.
-- It adds 17 tables for a university IT department. The department
-- issues laptops, runs computer labs and classroom AV gear, and
-- handles support tickets from faculty, staff, and students across campus.
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

-- This catalog records make and model separately from each serialized unit.
-- Ten identical lab workstations share one asset_models row.
-- Each machine gets its own items row and serial tag.
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

-- Each row holds one cataloged asset with a serial tag.
-- asset_model_id links the unit to its catalog entry.
CREATE TABLE items (
    id                VARCHAR(36) PRIMARY KEY,
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

CREATE TABLE tags (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  VARCHAR(255) NOT NULL UNIQUE
);

CREATE TABLE item_tags (
    item_id  VARCHAR(36) NOT NULL REFERENCES items(id),
    tag_id   INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (item_id, tag_id)
);

CREATE TABLE confidence_components (
    item_id               VARCHAR(36) PRIMARY KEY REFERENCES items(id),
    self_report           REAL NOT NULL,
    tag_coherence         REAL NOT NULL,
    self_report_weight    REAL NOT NULL,
    tag_coherence_weight  REAL NOT NULL,
    computed_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE embeddings_index (
    item_id            VARCHAR(36) PRIMARY KEY REFERENCES items(id),
    chroma_collection  TEXT NOT NULL,
    chroma_record_id   TEXT NOT NULL,
    model_name         TEXT NOT NULL,
    dims               INTEGER NOT NULL,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE vision_model_outputs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         VARCHAR(36) NOT NULL REFERENCES items(id),
    model_name      TEXT NOT NULL,
    attempt_number  INTEGER NOT NULL,
    raw_response    TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

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

CREATE TABLE processing_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    input_dir        TEXT NOT NULL,
    config_snapshot  TEXT NOT NULL,
    item_count       INTEGER NOT NULL DEFAULT 0,
    started_at       TEXT NOT NULL,
    finished_at      TEXT
);

-- ===== Domain tables: university IT =====

-- Campus academic and administrative units include "Computer Science",
-- "Registrar", and "Housing". Both employees and cost_centers
-- belong to a department.
CREATE TABLE departments (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  VARCHAR(255) NOT NULL UNIQUE
);

-- IT staff include technicians, administrators, and help desk agents.
-- Patrons request support but do not manage assets.
CREATE TABLE employees (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    email          VARCHAR(255) NOT NULL UNIQUE,
    department_id  INTEGER REFERENCES departments(id),
    job_title      TEXT
);

-- Faculty, staff, and students request IT support or receive loaned assets.
-- patron_type identifies students separately from faculty and staff.
-- Students are not university employees. Faculty and staff can be employees.
CREATE TABLE patrons (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    fsu_id       VARCHAR(255) NOT NULL UNIQUE,
    email        TEXT NOT NULL,
    patron_type  TEXT NOT NULL CHECK (patron_type IN ('student', 'faculty', 'staff'))
);

-- A university funding source can be a state appropriation, a grant,
-- or an auxiliary account. Purchase orders and software licenses
-- charge against one, so a department can report its own IT spend.
CREATE TABLE cost_centers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    code           VARCHAR(255) NOT NULL UNIQUE,
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
-- specific serialized unit. The unit gets an items row after it arrives
-- and the pipeline tags it.
CREATE TABLE purchase_order_lines (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id),
    asset_model_id    INTEGER NOT NULL REFERENCES asset_models(id),
    quantity          INTEGER NOT NULL,
    unit_cost         REAL NOT NULL
);

CREATE TABLE warranties (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id           VARCHAR(36) NOT NULL REFERENCES items(id),
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

-- This log shows which machine has a license installed.
-- A seat can move between items over time, so this is not a fixed pair.
CREATE TABLE license_assignments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    license_id   INTEGER NOT NULL REFERENCES software_licenses(id),
    item_id      VARCHAR(36) NOT NULL REFERENCES items(id),
    assigned_at  TEXT NOT NULL,
    revoked_at   TEXT
);

-- This table records which patron has a loaned asset, such as a laptop.
CREATE TABLE asset_assignments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id      VARCHAR(36) NOT NULL REFERENCES items(id),
    patron_id    INTEGER NOT NULL REFERENCES patrons(id),
    assigned_at  TEXT NOT NULL,
    returned_at  TEXT
);

CREATE TABLE ticket_categories (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  VARCHAR(255) NOT NULL UNIQUE
);

-- item_id can be NULL because some tickets concern account access
-- instead of a tracked asset.
CREATE TABLE service_tickets (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id              VARCHAR(36) REFERENCES items(id),
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
    item_id      VARCHAR(36) NOT NULL REFERENCES items(id),
    employee_id  INTEGER REFERENCES employees(id),
    service_date TEXT NOT NULL,
    notes        TEXT,
    cost         REAL
);

CREATE TABLE depreciation_schedules (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id           VARCHAR(36) NOT NULL REFERENCES items(id),
    method            TEXT NOT NULL CHECK (method IN ('straight_line', 'declining_balance')),
    useful_life_months INTEGER NOT NULL,
    salvage_value     REAL NOT NULL DEFAULT 0,
    start_date        TEXT NOT NULL
);
