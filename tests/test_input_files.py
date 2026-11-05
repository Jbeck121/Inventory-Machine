import configparser
import hashlib
import logging
from pathlib import Path

from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from inventory_machine.db import Database
from inventory_machine.preprocessing.input import (
    extract_photo_metadata,
    find_image_files,
    prepare_image,
    resolve_location_id,
    resolve_location_name,
)

logger = logging.getLogger(__name__)
SCHEMA = Path(__file__).resolve().parents[1] / "schema" / "option_a_home_organizer.sql"


def test_find_image_files_recurses_and_filters_supported_extensions(tmp_path):
    root = tmp_path / "inventory_input"
    nested = root / "garage" / "shelf_a"
    nested.mkdir(parents=True)
    (root / "note.txt").write_text("ignore me", encoding="utf-8")
    (nested / "img001.jpg").write_bytes(b"jpg")
    (nested / "img002.png").write_bytes(b"png")
    (nested / "img003.webp").write_bytes(b"webp")
    (nested / "ignored.gif").write_bytes(b"gif")

    result = find_image_files(root)

    paths = [str(path.relative_to(root)) for path in result]
    assert paths == [
        "garage/shelf_a/img001.jpg",
        "garage/shelf_a/img002.png",
        "garage/shelf_a/img003.webp",
    ]


def test_resolve_location_name_uses_nested_folder_structure_and_config_prefixes():
    cfg = configparser.ConfigParser()
    cfg["location"] = {
        "folder_separator": " > ",
        "strip_prefixes": "img_, scan_, batch_",
    }
    root = Path("/tmp/inventory_input")
    image_path = root / "scan_01" / "img_garage" / "batch_shelf_a" / "img004.jpg"

    result = resolve_location_name(image_path, root, cfg)

    assert result == "01 > garage > shelf_a"


def test_extract_photo_metadata_reads_exif_date_taken(tmp_path):
    image_path = tmp_path / "sample.jpg"
    image = Image.new("RGB", (32, 32), color="red")
    exif = image.getexif()
    exif[36867] = "2024:05:06 07:08:09"
    image.save(image_path, exif=exif)

    metadata = extract_photo_metadata(image_path)

    assert metadata["date_taken"] == "2024-05-06T07:08:09"
    assert metadata["gps_lat"] is None
    assert metadata["gps_lon"] is None


def test_extract_photo_metadata_reads_signed_gps_from_ifd(tmp_path):
    image_path = tmp_path / "gps.jpg"
    image = Image.new("RGB", (32, 32), color="red")
    exif = image.getexif()
    gps = exif.get_ifd(0x8825)
    gps[1] = "S"
    gps[2] = (IFDRational(37, 1), IFDRational(46, 1), IFDRational(30, 1))
    gps[3] = "W"
    gps[4] = (IFDRational(122, 1), IFDRational(25, 1), IFDRational(0, 1))
    image.save(image_path, exif=exif)

    metadata = extract_photo_metadata(image_path)

    assert metadata["gps_lat"] == -37.775
    assert metadata["gps_lon"] == -122.416667


def test_prepare_image_resizes_copies_and_avoids_name_collisions(tmp_path):
    cfg = configparser.ConfigParser()
    cfg["paths"] = {"prepared_dir": str(tmp_path / "prepared")}
    cfg["vision"] = {"image_max_px": "64"}

    large = tmp_path / "large.jpg"
    Image.new("RGB", (200, 100), "red").save(large)
    large_out = Path(prepare_image(str(large), cfg))
    assert large_out.parent == tmp_path / "prepared"
    with Image.open(large_out) as img:
        assert img.size == (64, 32)

    small = tmp_path / "small.jpg"
    Image.new("RGB", (10, 8), "blue").save(small)
    small_out = Path(prepare_image(str(small), cfg))
    assert small_out.parent == tmp_path / "prepared"
    with Image.open(small_out) as img:
        assert img.size == (10, 8)

    dir_a = tmp_path / "dir_a"
    dir_b = tmp_path / "dir_b"
    dir_a.mkdir()
    dir_b.mkdir()
    photo_a = dir_a / "photo.jpg"
    photo_b = dir_b / "photo.jpg"
    Image.new("RGB", (8, 8), "red").save(photo_a)
    Image.new("RGB", (8, 8), "green").save(photo_b)
    out_a = Path(prepare_image(str(photo_a), cfg))
    out_b = Path(prepare_image(str(photo_b), cfg))
    digest_a = hashlib.sha1(str(photo_a.resolve()).encode("utf-8")).hexdigest()[:16]
    digest_b = hashlib.sha1(str(photo_b.resolve()).encode("utf-8")).hexdigest()[:16]
    assert out_a.name == f"{digest_a}.jpg"
    assert out_b.name == f"{digest_b}.jpg"
    assert out_a.name != out_b.name


def test_resolve_location_id_creates_parent_chain_and_is_idempotent():
    cfg = configparser.ConfigParser()
    cfg["database"] = {"backend": "sqlite", "sqlite_path": ":memory:"}
    cfg["location"] = {"folder_separator": ">"}
    db = Database(cfg)
    try:
        db.load_schema(str(SCHEMA))
        assert resolve_location_id(db, None, cfg) is None
        assert resolve_location_id(db, "", cfg) is None

        inner = resolve_location_id(db, "garage > shelf_a", cfg)
        rows = db.fetch_all(
            "SELECT id, name, parent_location_id FROM locations ORDER BY id"
        )
        assert len(rows) == 2
        garage_id, garage_name, garage_parent = rows[0]
        shelf_id, shelf_name, shelf_parent = rows[1]
        assert garage_name == "garage"
        assert garage_parent is None
        assert shelf_name == "shelf_a"
        assert shelf_parent == garage_id
        assert inner == shelf_id

        again = resolve_location_id(db, "garage>shelf_a", cfg)
        assert again == inner
        assert db.fetch_all("SELECT id FROM locations") == [(garage_id,), (shelf_id,)]
    finally:
        db.get_connection().close()
