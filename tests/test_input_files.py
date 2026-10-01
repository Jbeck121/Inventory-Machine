import configparser
from pathlib import Path

from PIL import Image

from inventory_machine.preprocessing.input import (
    extract_photo_metadata,
    find_image_files,
    resolve_location_name,
)


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
