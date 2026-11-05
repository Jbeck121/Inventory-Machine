"""pytest tests for 0.5 in QR stickers and the sticker page."""
# Imports
import configparser
import logging
from pathlib import Path

import pytest
from PIL import Image

from inventory_machine.db import Database
from inventory_machine.labels import generate_qr_for_sticker, generate_sticker_page

# Globals
logger = logging.getLogger(__name__)
SCHEMA = Path(__file__).resolve().parents[1] / "schema" / "option_a_home_organizer.sql"
STICKER_SIZE = (128, 128)  # 0.5 in at about 300 DPI
LETTER_PX = (2550, 3300)


# Functions
def _cfg(tmp_path) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser(interpolation=None)
    cfg["database"] = {"backend": "sqlite", "sqlite_path": ":memory:"}
    cfg["paths"] = {"qr_output_dir": str(tmp_path / "qr")}
    cfg["labels"] = {"qr_base_url": "http://localhost:5050/"}
    return cfg


def _db_with_items(cfg) -> Database:
    db = Database(cfg)
    db.load_schema(str(SCHEMA))
    for name in ("garage", "kitchen", "empty shelf"):
        db.execute("INSERT INTO locations (name) VALUES (?)", (name,))
    for item_id, location_id in (("item-1", 1), ("item-2", 1), ("item-3", 2), ("item-4", None)):
        db.execute(
            "INSERT INTO items (id, location_id, description, confidence_score, "
            "confidence_flag, date_processed) VALUES (?, ?, ?, ?, ?, ?)",
            (item_id, location_id, "thing", 0.9, "ok", "2026-01-01 00:00:00"),
        )
    return db


def test_saved_png_has_sticker_size(tmp_path):
    out = tmp_path / "test_qr.png"
    generate_qr_for_sticker("test_qr_342342342valid", out)

    assert out.exists(), f"File not created at {out}"
    with Image.open(out) as img:
        assert img.size == STICKER_SIZE


def test_returned_image_has_sticker_size():
    img = generate_qr_for_sticker("test_qr_asdasdvalid")
    assert img.size == STICKER_SIZE


def test_sticker_page_defaults_to_occupied_locations_and_writes_no_rows(tmp_path):
    cfg = _cfg(tmp_path)
    db = _db_with_items(cfg)

    page = generate_sticker_page(cfg, db)

    with Image.open(page) as img:
        assert img.size == LETTER_PX
    stickers = sorted(p.name for p in (tmp_path / "qr").glob("qr_location_*.png"))
    assert stickers == ["qr_location_1.png", "qr_location_2.png"]
    assert db.fetch_one("SELECT COUNT(*) FROM qr_labels") == (0,)


def test_sticker_page_rejects_more_than_one_sheet(tmp_path):
    cfg = _cfg(tmp_path)
    db = _db_with_items(cfg)

    with pytest.raises(ValueError, match="81 stickers"):
        generate_sticker_page(cfg, db, location_ids=range(1, 82))
