"""Tests for inventory_machine.db.Database against a fresh SQLite database."""
import configparser
from pathlib import Path

import pytest

from inventory_machine.db import Database, adapt_schema_for_mariadb

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "schema.sql"

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
