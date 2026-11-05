"""Tests for QR label images, qr_labels rows, and letter sheets."""
# Imports
import configparser
import logging
from pathlib import Path

from PIL import Image

from inventory_machine.db import Database
from inventory_machine.labels import build_label_sheets, generate_qr_image, write_qr_labels
from inventory_machine.labels.generate_page import (
    LABEL_GAP_PX,
    LETTER_DPI,
    LETTER_HEIGHT_IN,
    LETTER_MARGIN_IN,
    LETTER_WIDTH_IN,
)

# Globals
logger = logging.getLogger(__name__)
SCHEMA = Path(__file__).resolve().parents[1] / "schema" / "option_a_home_organizer.sql"


# Functions
def make_cfg(tmp_path) -> configparser.ConfigParser:
    """
    Input: tmp_path -- pytest temp directory.
    Output: sqlite :memory: config with label output under tmp_path.
    """
    cfg = configparser.ConfigParser(interpolation=None)
    cfg["database"] = {"backend": "sqlite", "sqlite_path": ":memory:"}
    cfg["paths"] = {
        "qr_output_dir": str(tmp_path / "inventory_output" / "qr_codes"),
    }
    cfg["labels"] = {
        "qr_base_url": "http://localhost:5000/",
        "label_width_mm": "62",
        "label_height_mm": "29",
    }
    return cfg


def mm_to_px(mm: float) -> int:
    """
    Input: mm -- millimetres.
    Output: pixels at 300 DPI.
    """
    return round(mm / 25.4 * 300)


def letter_capacity(label_w: int, label_h: int) -> int:
    """
    Input: label size in pixels.
    Output: labels that fit on one US Letter page.
    """
    page_w = round(LETTER_WIDTH_IN * LETTER_DPI)
    page_h = round(LETTER_HEIGHT_IN * LETTER_DPI)
    margin = round(LETTER_MARGIN_IN * LETTER_DPI)
    usable_w = page_w - 2 * margin
    usable_h = page_h - 2 * margin
    cols = max(1, (usable_w + LABEL_GAP_PX) // (label_w + LABEL_GAP_PX))
    rows = max(1, (usable_h + LABEL_GAP_PX) // (label_h + LABEL_GAP_PX))
    return cols * rows


def add_item(db, item_id: str, description: str, location_id=None) -> None:
    """
    Input: db, item id, description, optional location.
    Output: None.
    """
    db.execute(
        "INSERT INTO items (id, location_id, description, "
        "confidence_score, confidence_flag, date_processed) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (item_id, location_id, description, 0.9, "ok", "2026-01-01 00:00:00"),
    )


def open_db(cfg):
    """
    Input: cfg -- sqlite config.
    Output: Database with the Option A schema loaded.
    """
    database = Database(cfg)
    database.load_schema(str(SCHEMA))
    return database


def test_generate_qr_image_uses_requested_size():
    img = generate_qr_image("http://localhost:5000/location/1", 128)
    assert img.size == (128, 128)
    assert img.mode == "RGB"


def test_write_qr_labels_size_set_urls_path_and_idempotent(tmp_path):
    cfg = make_cfg(tmp_path)
    db = open_db(cfg)
    try:
        house = db.execute(
            "INSERT INTO locations (name) VALUES (?)", ("House",)
        ).lastrowid
        garage = db.execute(
            "INSERT INTO locations (name, parent_location_id) VALUES (?, ?)",
            ("Garage", house),
        ).lastrowid
        bin_id = db.execute(
            "INSERT INTO locations (name, parent_location_id) VALUES (?, ?)",
            ("Bin", garage),
        ).lastrowid
        db.execute("INSERT INTO locations (name) VALUES (?)", ("Attic",))
        add_item(db, "item-bin", "hammer", bin_id)
        add_item(db, "item-garage", "ladder", garage)
        add_item(
            db,
            "item-loose",
            "a very long description of a loose tool that needs a short caption",
            None,
        )
        count = write_qr_labels(db, cfg)
        assert count == 3
        width_px = mm_to_px(62)
        height_px = mm_to_px(29)
        out = Path(cfg.get("paths", "qr_output_dir"))
        loc_bin = out / f"location_{bin_id}.png"
        loc_garage = out / f"location_{garage}.png"
        item_png = out / "item_item-loose.png"
        assert Image.open(loc_bin).size == (width_px, height_px)
        assert Image.open(loc_garage).size == (width_px, height_px)
        assert Image.open(item_png).size == (width_px, height_px)
        assert not (out / f"location_{house}.png").exists()
        loc_rows = db.fetch_all(
            "SELECT location_id FROM qr_labels WHERE location_id IS NOT NULL "
            "ORDER BY location_id"
        )
        item_rows = db.fetch_all(
            "SELECT item_id FROM qr_labels WHERE item_id IS NOT NULL"
        )
        assert [row[0] for row in loc_rows] == [garage, bin_id]
        assert [row[0] for row in item_rows] == ["item-loose"]
        bin_row = db.fetch_one(
            "SELECT label_text, qr_url, qr_image_path FROM qr_labels "
            "WHERE location_id = ?",
            (bin_id,),
        )
        assert bin_row[0] == "House > Garage > Bin"
        assert bin_row[1] == f"http://localhost:5000/location/{bin_id}"
        assert bin_row[2] == str(loc_bin)
        loose = db.fetch_one(
            "SELECT label_text, qr_url FROM qr_labels WHERE item_id = ?",
            ("item-loose",),
        )
        assert loose[0].startswith("a very long description of a loose tool")
        assert loose[0].endswith("...")
        assert len(loose[0]) == 60
        assert loose[1] == "http://localhost:5000/item/item-loose"
        first_ids = db.fetch_all("SELECT id FROM qr_labels ORDER BY id")
        assert write_qr_labels(db, cfg) == 3
        second_ids = db.fetch_all("SELECT id FROM qr_labels ORDER BY id")
        assert first_ids == second_ids
        assert len(list(out.glob("label_sheet_*.png"))) == 1
    finally:
        db.get_connection().close()


def test_build_label_sheets_spans_two_pages(tmp_path):
    out = tmp_path / "sheets"
    out.mkdir()
    width_px = mm_to_px(62)
    height_px = mm_to_px(29)
    per_page = letter_capacity(width_px, height_px)
    n_labels = per_page + 1
    paths = []
    for i in range(n_labels):
        path = out / f"label_{i}.png"
        Image.new("RGB", (width_px, height_px), "white").save(path)
        paths.append(str(path))
    sheets = build_label_sheets(paths, str(out))
    assert len(sheets) == 2
    assert Path(sheets[0]).name == "label_sheet_1.png"
    assert Path(sheets[1]).name == "label_sheet_2.png"
    page_w = round(LETTER_WIDTH_IN * LETTER_DPI)
    page_h = round(LETTER_HEIGHT_IN * LETTER_DPI)
    assert Image.open(sheets[0]).size == (page_w, page_h)
    assert Image.open(sheets[1]).size == (page_w, page_h)


def test_build_label_sheets_does_not_delete_outside_output_dir(tmp_path, monkeypatch):
    cwd = tmp_path / "cwd"
    out = tmp_path / "out"
    cwd.mkdir()
    out.mkdir()
    sentinel = cwd / "keep.png"
    sibling = tmp_path / "outside.png"
    Image.new("RGB", (10, 10), "red").save(sentinel)
    Image.new("RGB", (10, 10), "red").save(sibling)
    label = out / "location_1.png"
    Image.new("RGB", (mm_to_px(62), mm_to_px(29)), "white").save(label)
    monkeypatch.chdir(cwd)
    build_label_sheets([str(label)], str(out))
    assert sentinel.exists()
    assert sibling.exists()
    assert label.exists()
