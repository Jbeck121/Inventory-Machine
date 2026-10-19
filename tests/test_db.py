"""Tests for inventory_machine.db.Database against a fresh SQLite database."""
import configparser
import logging
import sqlite3
from pathlib import Path

import pytest

from inventory_machine.db import Database, adapt_schema_for_mariadb

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "schema.sql"
OPTION_A_SCHEMA_PATH = SCHEMA_PATH.with_name("option_a_home_organizer.sql")
CORE_TABLES = {
    "locations",
    "clusters",
    "items",
    "images",
    "tags",
    "item_tags",
    "confidence_components",
    "embeddings_index",
    "vision_model_outputs",
    "qr_labels",
    "processing_runs",
}


def sqlite_cfg(sqlite_path: str = ":memory:") -> configparser.ConfigParser:
    """
    Input: sqlite_path -- filesystem path or :memory:.
    Output: a ConfigParser with a sqlite [database] section.
    Details:
        Builds the config in memory. Does not read config.ini.
    """
    cfg = configparser.ConfigParser()
    cfg["database"] = {
        "backend": "sqlite",
        "sqlite_path": sqlite_path,
    }
    return cfg


@pytest.fixture
def db():
    """
    Input: None.
    Output: a Database with the core schema loaded on :memory: SQLite.
    Details:
        Closes the connection when the test ends.
    """
    database = Database(sqlite_cfg(":memory:"))
    database.load_schema(str(SCHEMA_PATH))
    yield database
    database.get_connection().close()


def test_load_schema_creates_core_tables(db):
    rows = db.fetch_all(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    )
    names = {row[0] for row in rows}
    assert names == CORE_TABLES
    assert len(names) == 11
    flag = db.fetch_one("PRAGMA foreign_keys")
    assert flag == (1,)


def test_execute_fetch_one_round_trip(db):
    cursor = db.execute("INSERT INTO locations (name) VALUES (?)", ("garage",))
    row = db.fetch_one(
        "SELECT name FROM locations WHERE id = ?",
        (cursor.lastrowid,),
    )
    assert row is not None
    assert row[0] == "garage"


def test_parameterized_query_stores_injection_string_as_data(db):
    payload = "'; DROP TABLE locations; --"
    db.execute("INSERT INTO locations (name) VALUES (?)", (payload,))
    row = db.fetch_one("SELECT name FROM locations WHERE name = ?", (payload,))
    assert row is not None
    assert row[0] == payload
    tables = db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("locations",),
    )
    assert tables == [("locations",)]


def test_adapt_schema_for_mariadb_rewrites_sqlite_syntax():
    sql = (
        "id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
        "created_at TEXT NOT NULL DEFAULT (datetime('now'))"
    )
    adapted = adapt_schema_for_mariadb(sql)
    assert adapted == (
        "id INTEGER PRIMARY KEY AUTO_INCREMENT,\n"
        "created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)"
    )


def test_option_a_condition_rating_and_foreign_key():
    cfg = sqlite_cfg()
    database = Database(cfg)
    try:
        database.load_schema(str(OPTION_A_SCHEMA_PATH))
        item_id = "123e4567-e89b-12d3-a456-426614174000"
        database.execute(
            "INSERT INTO items (id, description, confidence_score, date_processed) "
            "VALUES (?, ?, ?, ?)",
            (item_id, "wrench", 0.8, "2026-10-19"),
        )
        database.execute(
            "INSERT INTO condition_log (item_id, condition_rating, noted_at) "
            "VALUES (?, ?, ?)",
            (item_id, "good", "2026-10-19"),
        )
        assert database.fetch_one(
            "SELECT condition_rating FROM condition_log WHERE item_id = ?", (item_id,)
        ) == ("good",)
        with pytest.raises(sqlite3.IntegrityError):
            database.execute(
                "INSERT INTO condition_log (item_id, condition_rating, noted_at) "
                "VALUES (?, ?, ?)",
                (item_id, "unknown", "2026-10-19"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            database.execute(
                "INSERT INTO item_tags (item_id, tag_id) VALUES (?, ?)",
                ("00000000-0000-0000-0000-000000000000", 123),
            )
    finally:
        database.get_connection().close()


@pytest.mark.parametrize(
    "schema_file, table_count",
    [
        ("schema.sql", 11),
        ("option_a_home_organizer.sql", 24),
        ("option_b_university_it.sql", 28),
        ("option_c_spark_labs.sql", 30),
    ],
)
def test_all_schemas_share_images_columns(schema_file, table_count):
    database = Database(sqlite_cfg())
    try:
        database.load_schema(str(SCHEMA_PATH.with_name(schema_file)))
        rows = database.fetch_all("PRAGMA table_info(images)")
        assert [(row[1], row[2]) for row in rows] == [
            ("id", "INTEGER"),
            ("item_id", "VARCHAR(36)"),
            ("file_path", "TEXT"),
            ("original_filename", "TEXT"),
            ("width_px", "INTEGER"),
            ("height_px", "INTEGER"),
            ("date_taken", "TEXT"),
            ("gps_lat", "REAL"),
            ("gps_lon", "REAL"),
            ("created_at", "TEXT"),
        ]
        tables = database.fetch_all(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        assert len(tables) == table_count
    finally:
        database.get_connection().close()
