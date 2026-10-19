"""
Author: DbLayer
Date:   2026

Description:
    Optional integration test for a fresh MariaDB inventory database.
"""
# Imports
import configparser
import logging
import os
from pathlib import Path

import pytest

from inventory_machine.db import Database

# Globals
logger = logging.getLogger(__name__)
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "option_a_home_organizer.sql"


# Functions
def test_option_a_round_trip_on_mariadb():
    """
    Input: IM_MARIADB_DSN -- connection URL for an empty MariaDB database.
    Output: None.
    Details:
        Checks schema loading, bound values, foreign keys, and row retrieval.
    """
    dsn = os.environ.get("IM_MARIADB_DSN")
    if not dsn:
        pytest.skip("Set IM_MARIADB_DSN to a fresh MariaDB database to run this test")

    cfg = configparser.ConfigParser(interpolation=None)
    cfg["database"] = {"backend": "mariadb", "mariadb_dsn": dsn}
    db = Database(cfg)
    try:
        db.load_schema(str(SCHEMA_PATH))
        assert len(db.fetch_all("SHOW TABLES")) == 24

        location_id = db.execute("INSERT INTO locations (name) VALUES (?)", ("garage",)).lastrowid
        child_id = db.execute(
            "INSERT INTO locations (name, parent_location_id) VALUES (?, ?)",
            ("drawer", location_id),
        ).lastrowid
        item_id = "123e4567-e89b-12d3-a456-426614174000"
        db.execute(
            "INSERT INTO items (id, location_id, description, confidence_score, date_processed) "
            "VALUES (?, ?, ?, ?, ?)",
            (item_id, child_id, "metal wrench", 0.85, "2026-10-19"),
        )
        db.execute(
            "INSERT INTO images (item_id, file_path, original_filename, date_taken, gps_lat, gps_lon) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (item_id, "wrench.jpg", "wrench.jpg", "2026-10-18", 30.4, -84.3),
        )
        payload = "'; DROP TABLE locations; --"
        tag_id = db.execute("INSERT INTO tags (name) VALUES (?)", (payload,)).lastrowid
        db.execute("INSERT INTO item_tags (item_id, tag_id) VALUES (?, ?)", (item_id, tag_id))

        assert db.fetch_one("SELECT parent_location_id FROM locations WHERE id = ?", (child_id,)) == (location_id,)
        assert db.fetch_one(
            "SELECT location_id, description, confidence_flag FROM items WHERE id = ?", (item_id,)
        ) == (child_id, "metal wrench", "ok")
        assert db.fetch_one("SELECT name FROM tags WHERE id = ?", (tag_id,)) == (payload,)
        assert db.fetch_all(
            "SELECT item_id, tag_id FROM item_tags WHERE item_id = ?", (item_id,)
        ) == ((item_id, tag_id),)
        assert db.fetch_one("SELECT COUNT(*) FROM locations") == (2,)
        assert db.fetch_one(
            "SELECT date_taken, gps_lat, gps_lon FROM images WHERE item_id = ?", (item_id,)
        ) == ("2026-10-18", 30.4, -84.3)
        assert db.fetch_one("SELECT created_at FROM locations WHERE id = ?", (location_id,))[0]
    finally:
        db.get_connection().close()
