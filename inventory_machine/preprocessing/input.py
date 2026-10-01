"""Input discovery and photo metadata extraction for the inventory pipeline."""

from __future__ import annotations

import configparser
from pathlib import Path

from PIL import Image

SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def find_image_files(input_dir: str | Path) -> list[Path]:
    """
    Input: input_dir -- root folder to scan for photos.
    Output: list of image paths, sorted by relative path.
    Details:
        Recurses through the folder and keeps only supported photo files.
        The function raises FileNotFoundError when the input folder is absent.
    """
    root = Path(input_dir)
    if not root.exists():
        raise FileNotFoundError(f"Input directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {root}")

    files = [
        path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
    ]
    return sorted(files, key=lambda path: str(path.relative_to(root)))


def _strip_folder_prefixes(name: str, prefixes: tuple[str, ...]) -> str:
    """Remove configured folder-name prefixes without changing the rest of the segment."""
    cleaned = name.strip()
    while True:
        changed = False
        for prefix in prefixes:
            prefix = prefix.strip()
            if not prefix:
                continue
            candidate = cleaned.lower()
            if candidate.startswith(prefix.lower()):
                cleaned = cleaned[len(prefix) :]
                changed = True
                break
        if not changed:
            return cleaned.strip()


def resolve_location_name(
    image_path: str | Path,
    input_dir: str | Path,
    cfg: configparser.ConfigParser | None = None,
) -> str:
    """
    Input: image_path -- photo file, input_dir -- configured image root,
        cfg -- loaded config containing the location section.
    Output: a nested location string built from the relative folder path.
    Details:
        Uses the input directory as the base. Each parent folder becomes one
        layer in the location path. The configured folder separator joins them,
        and any configured prefix values are stripped before the name is used.
    """
    source = Path(image_path)
    root = Path(input_dir).resolve()
    absolute_source = source.resolve()

    try:
        relative = absolute_source.relative_to(root)
    except ValueError:
        relative = absolute_source

    parts = [part for part in relative.parts[:-1] if part and part != "."]
    if not parts:
        return root.name

    separator = " > "
    prefixes: tuple[str, ...] = ()
    if cfg is not None:
        separator = cfg.get("location", "folder_separator", fallback=" > ")
        raw_prefixes = cfg.get("location", "strip_prefixes", fallback="")
        prefixes = tuple(part.strip() for part in raw_prefixes.split(",") if part.strip())

    cleaned_parts = [
        _strip_folder_prefixes(part, prefixes)
        for part in parts
    ]
    cleaned_parts = [part for part in cleaned_parts if part]
    if not cleaned_parts:
        return root.name
    return separator.join(cleaned_parts)


def _parse_exif_datetime(value):
    """Normalize common EXIF timestamps to ISO 8601 for storage in the database."""
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.count(":") >= 2 and "-" not in cleaned:
        if " " in cleaned:
            cleaned = cleaned.replace(":", "-", 2)
            cleaned = cleaned.replace(" ", "T", 1)
            return cleaned
        return cleaned.replace(":", "-", 2)
    return cleaned


def _gps_to_decimal(value, reference):
    """Convert a GPS tuple to decimal degrees, respecting the cardinal direction."""
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        return None
    try:
        degrees, minutes, seconds = (float(part) for part in value)
    except (TypeError, ValueError):
        return None
    decimal = degrees + (minutes / 60.0) + (seconds / 3600.0)
    if reference in {"S", "W"}:
        decimal *= -1
    return round(decimal, 6)


def extract_photo_metadata(image_path: str | Path) -> dict:
    """
    Input: image_path -- path to a photo to inspect.
    Output: metadata dict containing EXIF date_taken and optional gps lat/lon.
    Details:
        Reads EXIF data using Pillow. Missing or malformed metadata is treated
        as empty values rather than causing ingestion to fail.
    """
    path = Path(image_path)
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            if not exif:
                return {"date_taken": None, "gps_lat": None, "gps_lon": None}

            date_taken = None
            for tag in (36867, 306, 36868):
                value = exif.get(tag)
                if value:
                    date_taken = _parse_exif_datetime(value)
                    if date_taken:
                        break

            gps_lat = None
            gps_lon = None
            gps_info = exif.get(34853)
            if isinstance(gps_info, dict):
                gps_lat = _gps_to_decimal(gps_info.get(2), gps_info.get(1))
                gps_lon = _gps_to_decimal(gps_info.get(4), gps_info.get(3))

            width_px, height_px = image.size
            return {
                "date_taken": date_taken,
                "gps_lat": gps_lat,
                "gps_lon": gps_lon,
                "width_px": width_px,
                "height_px": height_px,
            }
    except (FileNotFoundError, OSError, ValueError):
        return {"date_taken": None, "gps_lat": None, "gps_lon": None, "width_px": None, "height_px": None}


def collect_input_files(cfg: configparser.ConfigParser) -> list[dict]:
    """Walk the configured input folder and return one metadata record per photo."""
    input_dir = cfg.get("paths", "input_dir")
    records: list[dict] = []
    for image_path in find_image_files(input_dir):
        metadata = extract_photo_metadata(image_path)
        records.append(
            {
                "file_path": str(image_path),
                "location": resolve_location_name(image_path, input_dir, cfg),
                "original_filename": image_path.name,
                "date_taken": metadata.get("date_taken"),
                "gps_lat": metadata.get("gps_lat"),
                "gps_lon": metadata.get("gps_lon"),
                "width_px": metadata.get("width_px"),
                "height_px": metadata.get("height_px"),
            }
        )
    return records
